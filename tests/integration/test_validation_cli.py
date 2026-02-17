"""CLI validation — verify entry points work against synthetic data."""

import subprocess
import sys
from pathlib import Path

from tests.synthetic.pipeline import PipelineRunner
from tests.synthetic.simulator import HouseholdSimulator


class TestCLIImports:
    """CLI entry points should be importable."""

    def test_main_importable(self):
        from aria.cli import main

        assert callable(main)

    def test_engine_cli_importable(self):
        from aria.engine.cli import main as engine_main

        assert callable(engine_main)


class TestCLIStatus:
    """aria status should work (may require hub not running)."""

    def test_status_exits_cleanly(self):
        """Status with no running hub should exit without traceback."""
        result = subprocess.run(
            [sys.executable, "-c", "from aria.cli import main; main()"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(Path(__file__).resolve().parents[2]),
            env={**__import__("os").environ, "COLUMNS": "80"},
            input="",
        )
        # With no args, main() prints help and exits 0 or 2 — either is fine
        # The key assertion: no unhandled traceback
        assert "Traceback" not in result.stderr or "SystemExit" in result.stderr, f"CLI tracebacked:\n{result.stderr}"

    def test_status_subcommand_no_traceback(self):
        """Status subcommand with no running hub should not traceback."""
        result = subprocess.run(
            [sys.executable, "-c", "import sys; sys.argv = ['aria', 'status']; from aria.cli import main; main()"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        # May exit non-zero if hub not running, but should not traceback
        assert "Traceback" not in result.stderr, f"Status command tracebacked:\n{result.stderr}"


class TestCLIPipelineIntegration:
    """Engine CLI commands should work with synthetic data directories."""

    def test_engine_produces_models(self, tmp_path):
        """Verify the engine pipeline produces model files via Python API."""
        sim = HouseholdSimulator(scenario="stable_couple", days=21, seed=42)
        snapshots = sim.generate()
        runner = PipelineRunner(snapshots, data_dir=tmp_path)
        runner.save_snapshots()
        runner.train_models()
        models_dir = runner.paths.models_dir
        assert models_dir.exists()
        pkl_files = list(models_dir.glob("*.pkl"))
        assert len(pkl_files) >= 1, "Training should produce at least one model file"

    def test_engine_produces_predictions(self, tmp_path):
        """Verify predictions are written to disk."""
        sim = HouseholdSimulator(scenario="stable_couple", days=21, seed=42)
        snapshots = sim.generate()
        runner = PipelineRunner(snapshots, data_dir=tmp_path)
        runner.run_full()
        predictions_path = runner.paths.predictions_path
        assert predictions_path.exists(), "Predictions file should be written to disk"
