"""Tests for aria demo mode CLI integration."""

from tests.demo.generate import generate_checkpoint
from tests.synthetic.simulator import INTRADAY_HOURS


class TestDemoGenerate:
    def test_generate_checkpoint(self, tmp_path):
        output = generate_checkpoint(
            scenario="stable_couple",
            days=14,
            seed=42,
            output_dir=tmp_path / "day_14",
        )
        assert (tmp_path / "day_14").exists()
        assert (tmp_path / "day_14" / "daily").exists()
        # Multiple intraday snapshots per day overwrite the same {date}.json on disk
        assert len(list((tmp_path / "day_14" / "daily").glob("*.json"))) == 14
        assert output["snapshots_saved"] == 14 * len(INTRADAY_HOURS)

    def test_generate_multiple_checkpoints(self, tmp_path):
        for name, days in [("day_07", 7), ("day_14", 14)]:
            output = generate_checkpoint(
                scenario="stable_couple",
                days=days,
                seed=42,
                output_dir=tmp_path / name,
            )
            assert output["snapshots_saved"] == days * len(INTRADAY_HOURS)
