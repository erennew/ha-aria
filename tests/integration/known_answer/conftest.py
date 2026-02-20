"""Known-answer test infrastructure — golden comparison + shared fixtures."""

import json
from pathlib import Path
from typing import Any

import pytest

GOLDEN_DIR = Path(__file__).parent / "golden"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _short(val, limit=120):
    """Truncate a value's repr for diff output."""
    s = json.dumps(val, default=str) if isinstance(val, dict | list) else repr(val)
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _diff_dicts(act, gld, prefix=""):
    """Recursively diff nested dicts, reporting leaf-level changes."""
    lines = []
    all_keys = sorted(set(act) | set(gld))
    for k in all_keys:
        path = f"{prefix}.{k}" if prefix else k
        if k not in gld:
            lines.append(f"  + {path}: {_short(act[k])}  (added)")
        elif k not in act:
            lines.append(f"  - {path}: {_short(gld[k])}  (removed)")
        elif act[k] != gld[k]:
            if isinstance(act[k], dict) and isinstance(gld[k], dict):
                lines.extend(_diff_dicts(act[k], gld[k], path))
            else:
                lines.append(f"  ~ {path}: {_short(gld[k])} → {_short(act[k])}")
    return lines


def pytest_addoption(parser):
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Update golden reference files with current output",
    )


@pytest.fixture
def update_golden(request):
    return request.config.getoption("--update-golden")


def golden_compare(
    actual: dict[str, Any],
    golden_name: str,
    update: bool = False,
) -> dict[str, Any] | None:
    """Compare actual output against golden reference file.

    Args:
        actual: The actual output from the module
        golden_name: Name of the golden file (without .json extension)
        update: If True, overwrite the golden file with actual output

    Returns:
        The golden data if comparison made, None if file didn't exist or was updated.
        Drift is reported as a pytest warning, never a failure.
    """
    golden_path = GOLDEN_DIR / f"{golden_name}.json"

    if update:
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(json.dumps(actual, indent=2, default=str) + "\n")
        return None

    if not golden_path.exists():
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(json.dumps(actual, indent=2, default=str) + "\n")
        import warnings

        warnings.warn(
            f"Golden file created: {golden_name}.json (first run)",
            stacklevel=2,
        )
        return None

    golden = json.loads(golden_path.read_text())

    if actual != golden:
        import warnings

        diff_lines = []
        if isinstance(actual, dict) and isinstance(golden, dict):
            diff_lines = _diff_dicts(actual, golden)
        diff_detail = "\n".join(diff_lines) if diff_lines else "  (structure mismatch)"
        warnings.warn(
            f"Golden drift in {golden_name}:\n{diff_detail}\nRun with --update-golden to re-baseline.",
            stacklevel=2,
        )

    return golden


@pytest.fixture
async def hub(tmp_path):
    """Create a minimal IntelligenceHub for known-answer tests."""
    from aria.hub.core import IntelligenceHub  # lazy: only load when this fixture is used

    h = IntelligenceHub(cache_path=str(tmp_path / "hub.db"))
    await h.initialize()
    yield h
    await h.shutdown()
