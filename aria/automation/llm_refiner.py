"""LLM refiner — Ollama polish for automation alias and description.

Sends the automation dict to a local LLM for human-friendly text
improvements. Strict post-refinement validation ensures only alias
and description can change — any structural modification triggers
a silent fallback to the original template output.
"""

import asyncio
import json
import logging

from aria.engine.config import OllamaConfig
from aria.engine.llm.client import ollama_chat

logger = logging.getLogger(__name__)

# Fields that the LLM is never allowed to modify.
IMMUTABLE_KEYS = frozenset({"id", "triggers", "conditions", "actions", "mode"})

# Fields the LLM may refine.
MUTABLE_KEYS = frozenset({"alias", "description"})

_REFINE_PROMPT = """\
You are a Home Assistant automation naming assistant.

Given this automation, write a better alias (short, human-friendly name)
and description (1-2 sentences explaining what it does and when).

Rules:
- Return ONLY a JSON object with "alias" and "description" keys.
- Do NOT include any other keys.
- Do NOT modify triggers, conditions, actions, mode, or id.
- Keep alias under 60 characters.
- Keep description under 200 characters.
- Use plain English, no jargon.

Automation:
{automation_json}

Return JSON only, no markdown fences:"""


async def refine_automation(
    automation: dict,
    model: str = "qwen2.5-coder:14b",
    timeout: int = 30,
) -> dict:
    """Refine an automation's alias and description via Ollama.

    Sends the automation dict to a local LLM for text polish.
    Falls back to the original dict on any failure or if the LLM
    attempts to modify structural fields.

    Args:
        automation: Complete HA automation dict from template engine.
        model: Ollama model name.
        timeout: Request timeout in seconds.

    Returns:
        Automation dict with potentially refined alias/description,
        or the original dict unchanged on failure.
    """
    config = OllamaConfig(model=model, timeout=timeout)
    prompt = _REFINE_PROMPT.format(automation_json=json.dumps(automation, indent=2))

    try:
        raw_response = await asyncio.to_thread(ollama_chat, prompt, config)
    except Exception:
        logger.warning("LLM refiner call failed, using template output")
        return automation

    if not raw_response:
        logger.debug("LLM refiner returned empty response")
        return automation

    return _apply_refinement(automation, raw_response)


def _apply_refinement(original: dict, raw_response: str) -> dict:
    """Parse LLM response and apply only safe text changes.

    Returns the original dict if the response is invalid or
    attempts structural modifications.
    """
    parsed = _parse_response(raw_response)
    if parsed is None:
        return original

    # Reject if LLM returned any immutable key
    if any(key in parsed for key in IMMUTABLE_KEYS):
        logger.warning("LLM refiner attempted structural change, rejecting")
        return original

    # Apply only mutable text fields
    refined = dict(original)
    for key in MUTABLE_KEYS:
        if key in parsed and isinstance(parsed[key], str) and parsed[key].strip():
            refined[key] = parsed[key].strip()

    return refined


def _parse_response(raw: str) -> dict | None:
    """Parse the LLM JSON response, stripping markdown fences if present."""
    text = raw.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last fence lines
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.debug("LLM refiner returned non-JSON: %.100s", text)
        return None

    if not isinstance(parsed, dict):
        logger.debug("LLM refiner returned non-dict type: %s", type(parsed).__name__)
        return None

    return parsed
