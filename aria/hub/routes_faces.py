"""FastAPI routes for face recognition pipeline."""

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class LabelRequest(BaseModel):
    queue_id: int
    person_name: str


def _register_face_routes(router: APIRouter, hub: Any) -> None:  # noqa: PLR0912, C901, PLR0915
    """Register /api/faces/* endpoints on the given router."""

    def _store():
        store = getattr(hub, "faces_store", None)
        if store is None:
            raise HTTPException(status_code=503, detail="Face store not initialized")
        return store

    @router.get("/api/faces/queue")
    async def get_face_queue(limit: int = 20):
        """Return pending review queue, highest priority first."""
        try:
            store = _store()
            items = store.get_review_queue(limit=limit)
            # Strip embedding blob from API response (not serializable, not needed by UI)
            for item in items:
                item.pop("embedding", None)
            return {"items": items, "depth": store.get_queue_depth()}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error fetching face queue")
            raise HTTPException(status_code=500, detail="Internal server error") from None

    @router.post("/api/faces/label")
    async def label_face(req: LabelRequest):
        """Label a queued face and save embedding to training store."""
        try:
            store = _store()
            # Fetch only pending items (reviewed_at IS NULL)
            queue_items = store.get_review_queue(limit=1000)
            item = next((q for q in queue_items if q["id"] == req.queue_id), None)
            if item is None:
                raise HTTPException(status_code=404, detail="Queue item not found or already reviewed")

            # Capture embedding before marking reviewed
            embedding = item["embedding"]

            # mark_reviewed returns nothing but logs warning if rowcount == 0 (race condition)
            # If already reviewed by a concurrent request, this is a no-op with warning
            store.mark_reviewed(req.queue_id, person_name=req.person_name)

            # Save the labeled embedding — use INSERT OR IGNORE in case of concurrent label
            try:
                store.add_embedding(
                    person_name=req.person_name,
                    embedding=embedding,
                    event_id=item["event_id"],
                    image_path=item["image_path"],
                    confidence=1.0,
                    source="manual",
                    verified=True,
                )
            except Exception:
                logger.warning("label_face: duplicate embedding insert for queue_id=%d, skipping", req.queue_id)

            return {"status": "ok", "person_name": req.person_name}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error labeling face")
            raise HTTPException(status_code=500, detail="Internal server error") from None

    @router.get("/api/faces/people")
    async def get_known_people():
        """Return all known people with embedding counts."""
        try:
            store = _store()
            return {"people": store.get_known_people()}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error fetching known people")
            raise HTTPException(status_code=500, detail="Internal server error") from None

    @router.get("/api/faces/stats")
    async def get_face_stats():
        """Return queue depth and known people count."""
        try:
            store = _store()
            return {
                "queue_depth": store.get_queue_depth(),
                "known_people": len(store.get_known_people()),
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error fetching face stats")
            raise HTTPException(status_code=500, detail="Internal server error") from None

    @router.post("/api/faces/bootstrap")
    async def trigger_bootstrap():
        """Kick off bootstrap batch extraction as a background task."""
        import asyncio

        from aria.faces.bootstrap import BootstrapPipeline

        try:
            store = _store()
            clips_dir = os.environ.get("FRIGATE_CLIPS_DIR", str(Path.home() / "frigate/media/clips"))

            async def _run():
                pipeline = BootstrapPipeline(clips_dir=clips_dir, store=store)
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, pipeline.run)

            from aria.shared.utils import log_task_exception

            task = asyncio.create_task(_run())
            task.add_done_callback(log_task_exception)
            return {"status": "started", "clips_dir": clips_dir}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error starting bootstrap")
            raise HTTPException(status_code=500, detail="Internal server error") from None

    @router.post("/api/faces/deploy")
    async def deploy_to_frigate():
        """Copy best N images per person to Frigate faces dir."""
        import shutil
        from pathlib import Path

        try:
            store = _store()
            frigate_faces = (
                Path(os.environ.get("FRIGATE_CLIPS_DIR", str(Path.home() / "frigate/media/clips"))) / "faces"
            )
            people = store.get_known_people()
            deployed = []
            for person in people:
                name = person["person_name"]
                embeddings = store.get_embeddings_for_person(name)
                top = sorted(
                    [e for e in embeddings if e.get("verified") and e.get("image_path")],
                    key=lambda x: x.get("confidence", 0),
                    reverse=True,
                )[:10]
                dest_dir = frigate_faces / name
                dest_dir.mkdir(parents=True, exist_ok=True)
                for i, entry in enumerate(top):
                    src = Path(entry["image_path"])
                    if src.exists():
                        shutil.copy2(src, dest_dir / f"{i:03d}.jpg")
                deployed.append({"person": name, "images": len(top)})
            return {"deployed": deployed}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error deploying to Frigate")
            raise HTTPException(status_code=500, detail="Internal server error") from None
