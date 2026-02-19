"""Known-answer test infrastructure — golden comparison + shared fixtures."""

import json
from pathlib import Path
from typing import Any

import pytest

from aria.hub.core import IntelligenceHub

GOLDEN_DIR = Path(__file__).parent / "golden"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


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

        diff_keys = []
        if isinstance(actual, dict) and isinstance(golden, dict):
            all_keys = set(actual.keys()) | set(golden.keys())
            for key in sorted(all_keys):
                if actual.get(key) != golden.get(key):
                    diff_keys.append(key)
        warnings.warn(
            f"Golden drift in {golden_name}.json: "
            f"keys differ: {diff_keys or 'structure mismatch'}. "
            f"Run with --update-golden to re-baseline.",
            stacklevel=2,
        )

    return golden


@pytest.fixture
async def hub(tmp_path):
    """Create a minimal IntelligenceHub for known-answer tests."""
    h = IntelligenceHub(cache_path=str(tmp_path / "hub.db"))
    await h.initialize()
    yield h
    await h.shutdown()
