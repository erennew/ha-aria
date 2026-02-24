"""Shared utility functions for ARIA modules."""

import asyncio
import logging

logger = logging.getLogger(__name__)


def log_task_exception(task: asyncio.Task) -> None:
    """Done callback that logs unhandled exceptions from fire-and-forget tasks.

    Attach via ``task.add_done_callback(log_task_exception)`` to ensure
    exceptions in background tasks are always visible in logs (lesson #43).
    """
    if not task.cancelled() and task.exception():
        logger.error(
            "Unhandled exception in task %s",
            task.get_name(),
            exc_info=task.exception(),
        )
