"""Automation API routes — shadow sync, status, compare, health, delete.

Batch 11 endpoints for the automation suggestion pipeline.
Registered via _register_automation_routes() in create_api().
"""

import logging

from fastapi import APIRouter, HTTPException

from aria.hub.core import IntelligenceHub

logger = logging.getLogger(__name__)


def _register_automation_routes(router: APIRouter, hub: IntelligenceHub) -> None:
    """Register automation management endpoints on the router."""
    _register_shadow_sync_routes(router, hub)
    _register_shadow_info_routes(router, hub)
    _register_automation_mgmt_routes(router, hub)


def _register_shadow_sync_routes(router: APIRouter, hub: IntelligenceHub) -> None:
    """Register shadow sync endpoint."""

    @router.post("/api/shadow/sync")
    async def shadow_sync():
        """Trigger a sync of HA automations for shadow comparison.

        Delegates to HaAutomationSync.sync() via the orchestrator module's
        session, then regenerates suggestions via the automation_generator.
        """
        try:
            orchestrator = hub.get_module("orchestrator")
            if not orchestrator:
                raise HTTPException(
                    status_code=503,
                    detail="Orchestrator module not loaded",
                )

            ha_url = getattr(orchestrator, "ha_url", None)
            ha_token = getattr(orchestrator, "ha_token", None)
            if not ha_url or not ha_token:
                raise HTTPException(
                    status_code=503,
                    detail="HA credentials not available on orchestrator",
                )

            from aria.shared.ha_automation_sync import HaAutomationSync

            syncer = HaAutomationSync(hub, ha_url, ha_token)
            result = await syncer.sync()

            # Trigger suggestion regeneration if sync succeeded
            if result.get("success"):
                generator = hub.get_module("automation_generator")
                if generator:
                    try:
                        await generator.generate_suggestions()
                    except Exception as e:
                        logger.warning("Post-sync suggestion regeneration failed: %s", e)

            return result

        except HTTPException:
            raise
        except Exception:
            logger.exception("Error during shadow sync")
            raise HTTPException(status_code=500, detail="Internal server error") from None


def _register_shadow_info_routes(router: APIRouter, hub: IntelligenceHub) -> None:
    """Register shadow status and compare endpoints."""

    @router.get("/api/shadow/status")
    async def shadow_status():
        """Return shadow comparison pipeline status."""
        try:
            ha_cache = await hub.get_cache("ha_automations")
            suggestions_cache = await hub.get_cache("automation_suggestions")
            pipeline = await hub.cache.get_pipeline_state()

            ha_data = ha_cache.get("data", {}) if ha_cache else {}
            sug_data = suggestions_cache.get("data", {}) if suggestions_cache else {}

            return {
                "ha_automations_count": len(ha_data.get("automations", {})),
                "ha_automations_last_synced": ha_cache.get("last_updated") if ha_cache else None,
                "suggestions_count": sug_data.get("count", 0),
                "suggestions_last_generated": (suggestions_cache.get("last_updated") if suggestions_cache else None),
                "pipeline_stage": pipeline.get("current_stage", "shadow") if pipeline else "shadow",
            }
        except Exception:
            logger.exception("Error getting shadow status")
            raise HTTPException(status_code=500, detail="Internal server error") from None

    @router.get("/api/shadow/compare")
    async def shadow_compare():
        """Compare current suggestions against existing HA automations."""
        try:
            suggestions_cache = await hub.get_cache("automation_suggestions")
            ha_cache = await hub.get_cache("ha_automations")

            suggestions = suggestions_cache.get("data", {}).get("suggestions", []) if suggestions_cache else []
            ha_automations = ha_cache.get("data", {}).get("automations", {}) if ha_cache else {}

            comparisons = []
            status_counts: dict[str, int] = {}

            for s in suggestions:
                shadow_status = s.get("shadow_status", "unknown")
                status_counts[shadow_status] = status_counts.get(shadow_status, 0) + 1
                comparisons.append(
                    {
                        "suggestion_id": s.get("suggestion_id"),
                        "trigger_entity": s.get("metadata", {}).get("trigger_entity", ""),
                        "shadow_status": shadow_status,
                        "shadow_reason": s.get("shadow_reason", ""),
                        "combined_score": s.get("combined_score", 0),
                        "status": s.get("status", "pending"),
                    }
                )

            ha_count = len(ha_automations) if isinstance(ha_automations, list | dict) else 0

            return {
                "comparisons": comparisons,
                "total_suggestions": len(suggestions),
                "total_ha_automations": ha_count,
                "status_counts": status_counts,
            }
        except Exception:
            logger.exception("Error comparing shadow automations")
            raise HTTPException(status_code=500, detail="Internal server error") from None


def _register_automation_mgmt_routes(router: APIRouter, hub: IntelligenceHub) -> None:
    """Register automation health and delete endpoints."""

    @router.get("/api/automations/health")
    async def automations_health():
        """Return automation system health summary.

        Reads from the automation_system_health cache if available,
        otherwise builds a live summary from component caches.
        """
        try:
            # Try cached health first (populated by AutomationGeneratorModule)
            health_cache = await hub.get_cache("automation_system_health")
            if health_cache and health_cache.get("data"):
                return health_cache["data"]

            # Fallback: build live
            return await _build_live_health(hub)
        except Exception:
            logger.exception("Error getting automations health")
            raise HTTPException(status_code=500, detail="Internal server error") from None

    @router.delete("/api/automations/{suggestion_id}")
    async def delete_automation(suggestion_id: str):
        """Delete a suggestion by ID from the automation_suggestions cache."""
        try:
            cached = await hub.get_cache("automation_suggestions")
            if not cached or not cached.get("data"):
                raise HTTPException(status_code=404, detail="No suggestions found")

            suggestions = cached["data"].get("suggestions", [])
            original_count = len(suggestions)
            filtered = [s for s in suggestions if s.get("suggestion_id") != suggestion_id]

            if len(filtered) == original_count:
                raise HTTPException(
                    status_code=404,
                    detail=f"Suggestion '{suggestion_id}' not found",
                )

            await hub.set_cache(
                "automation_suggestions",
                {"suggestions": filtered, "count": len(filtered)},
                {"source": "api_delete"},
            )

            return {
                "status": "deleted",
                "suggestion_id": suggestion_id,
                "remaining": len(filtered),
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error deleting automation suggestion")
            raise HTTPException(status_code=500, detail="Internal server error") from None


async def _build_live_health(hub: IntelligenceHub) -> dict:
    """Build live automation health summary from component caches."""
    suggestions_cache = await hub.get_cache("automation_suggestions")
    ha_cache = await hub.get_cache("ha_automations")
    pipeline = await hub.cache.get_pipeline_state()
    feedback_cache = await hub.get_cache("automation_feedback")

    sug_data = suggestions_cache.get("data", {}) if suggestions_cache else {}
    ha_data = ha_cache.get("data", {}) if ha_cache else {}
    fb_data = feedback_cache.get("data", {}) if feedback_cache else {}

    suggestions = sug_data.get("suggestions", [])
    pending = sum(1 for s in suggestions if s.get("status") == "pending")
    approved = sum(1 for s in suggestions if s.get("status") == "approved")
    rejected = sum(1 for s in suggestions if s.get("status") == "rejected")

    return {
        "suggestions_total": len(suggestions),
        "suggestions_pending": pending,
        "suggestions_approved": approved,
        "suggestions_rejected": rejected,
        "ha_automations_count": len(ha_data.get("automations", {})),
        "ha_automations_last_synced": ha_cache.get("last_updated") if ha_cache else None,
        "pipeline_stage": pipeline.get("current_stage", "shadow") if pipeline else "shadow",
        "feedback_count": len(fb_data.get("suggestions", {})),
        "generator_loaded": hub.get_module("automation_generator") is not None,
        "orchestrator_loaded": hub.get_module("orchestrator") is not None,
    }
