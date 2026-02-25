"""Live face pipeline: Frigate event → embed → match → auto-label or queue."""

import logging
from typing import Any

import numpy as np

from aria.faces.extractor import FaceExtractor
from aria.faces.store import FaceEmbeddingStore

logger = logging.getLogger(__name__)


class FacePipeline:
    """Process live Frigate face events — match against store, queue uncertain."""

    def __init__(self, store: FaceEmbeddingStore, frigate_url: str):
        self.store = store
        self.frigate_url = frigate_url
        self.extractor = FaceExtractor()

    def process_embedding(
        self,
        embedding: np.ndarray,
        event_id: str,
        image_path: str = "",
    ) -> dict[str, Any]:
        """Match embedding against known people. Auto-label or queue for review.

        Returns one of:
            {"action": "auto_label", "person_name": str, "confidence": float}
            {"action": "queued", "queue_id": int}
        """
        named = self.store.get_all_named_embeddings()
        if not named:
            # No training data yet — queue everything at max priority
            qid = self.store.add_to_review_queue(
                event_id=event_id,
                image_path=image_path,
                embedding=embedding,
                top_candidates=[],
                priority=1.0,
            )
            return {"action": "queued", "queue_id": qid}

        candidates = self.extractor.find_best_match(embedding, named, min_threshold=0.0)
        if not candidates:
            qid = self.store.add_to_review_queue(
                event_id=event_id,
                image_path=image_path,
                embedding=embedding,
                top_candidates=[],
                priority=1.0,
            )
            return {"action": "queued", "queue_id": qid}

        top = candidates[0]
        person_name = top["person_name"]
        confidence = top["confidence"]

        # Per-person adaptive threshold — tightens as sample count grows
        # Use only verified embeddings to avoid feedback loop from auto-labels
        count = sum(1 for e in named if e["person_name"] == person_name and e.get("verified"))
        threshold = self.store.get_threshold_for_person(person_name, labeled_count=count)

        if confidence >= threshold:
            # Auto-label — save to grow training set
            try:
                self.store.add_embedding(
                    person_name=person_name,
                    embedding=embedding,
                    event_id=event_id,
                    image_path=image_path,
                    confidence=confidence,
                    source="live",
                    verified=False,
                )
            except Exception:
                logger.debug("Face auto-label: duplicate event_id=%s, skipping insert", event_id)
            logger.debug("Face auto-labeled: %s (conf=%.3f, threshold=%.3f)", person_name, confidence, threshold)
            return {"action": "auto_label", "person_name": person_name, "confidence": confidence}

        # Below threshold — queue for human review
        priority = 1.0 - confidence  # higher uncertainty = higher priority
        qid = self.store.add_to_review_queue(
            event_id=event_id,
            image_path=image_path,
            embedding=embedding,
            top_candidates=candidates[:3],
            priority=priority,
        )
        logger.debug("Face queued for review: %s (conf=%.3f, threshold=%.3f)", person_name, confidence, threshold)
        return {"action": "queued", "queue_id": qid}
