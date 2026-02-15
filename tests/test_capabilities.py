"""Tests for the capability registry and CLI commands."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from aria.capabilities import Capability, CapabilityRegistry

PROJECT_ROOT = str(Path(__file__).parent.parent)


class TestCapabilityDataclass:
    """Tests for the Capability frozen dataclass."""

    def test_valid_capability(self):
        cap = Capability(
            id="test_cap",
            name="Test Capability",
            description="A test capability",
            module="test_module",
            layer="hub",
        )
        assert cap.id == "test_cap"
        assert cap.layer == "hub"
        assert cap.status == "stable"

    def test_invalid_layer_raises(self):
        with pytest.raises(ValueError, match="layer must be one of"):
            Capability(
                id="bad", name="Bad", description="x", module="m", layer="invalid"
            )

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="status must be one of"):
            Capability(
                id="bad", name="Bad", description="x", module="m", layer="hub", status="bad"
            )

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="id must not be empty"):
            Capability(id="", name="Name", description="x", module="m", layer="hub")


class TestCapabilityRegistry:
    """Tests for the CapabilityRegistry."""

    def test_register_and_list(self):
        reg = CapabilityRegistry()
        cap = Capability(id="a", name="A", description="x", module="m", layer="hub")
        reg.register(cap)
        assert reg.list_ids() == ["a"]
        assert reg.list_all() == [cap]

    def test_duplicate_raises(self):
        reg = CapabilityRegistry()
        cap = Capability(id="a", name="A", description="x", module="m", layer="hub")
        reg.register(cap)
        with pytest.raises(ValueError, match="already registered"):
            reg.register(cap)

    def test_collect_from_modules(self):
        reg = CapabilityRegistry()
        reg.collect_from_modules()
        caps = reg.list_all()
        assert len(caps) >= 22
        ids = reg.list_ids()
        assert "discovery" in ids
        assert "snapshot" in ids
        assert "shadow_predictions" in ids

    def test_list_by_layer(self):
        reg = CapabilityRegistry()
        reg.collect_from_modules()
        engine_caps = reg.list_by_layer("engine")
        assert all(c.layer == "engine" for c in engine_caps)
        assert any(c.id == "snapshot" for c in engine_caps)

    def test_list_by_status(self):
        reg = CapabilityRegistry()
        reg.collect_from_modules()
        stable = reg.list_by_status("stable")
        assert all(c.status == "stable" for c in stable)
        assert len(stable) > 0


class TestCapabilitiesCLI:
    """Tests for the `aria capabilities` CLI subcommand."""

    def test_list_command(self):
        result = subprocess.run(
            [sys.executable, "-m", "aria.cli", "capabilities", "list"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "discovery" in result.stdout
        assert "shadow_predictions" in result.stdout

    def test_list_layer_filter(self):
        result = subprocess.run(
            [sys.executable, "-m", "aria.cli", "capabilities", "list", "--layer", "engine"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "snapshot" in result.stdout
        assert "shadow_predictions" not in result.stdout

    def test_list_status_filter(self):
        result = subprocess.run(
            [sys.executable, "-m", "aria.cli", "capabilities", "list", "--status", "stable"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "stable" in result.stdout

    def test_list_verbose(self):
        result = subprocess.run(
            [sys.executable, "-m", "aria.cli", "capabilities", "list", "--verbose"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        # Verbose output should include description text
        assert len(result.stdout) > 500

    def test_verify_command(self):
        result = subprocess.run(
            [sys.executable, "-m", "aria.cli", "capabilities", "verify"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_export_json(self):
        result = subprocess.run(
            [sys.executable, "-m", "aria.cli", "capabilities", "export"],
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert "capabilities" in data
        assert data["total"] >= 22
        assert "by_layer" in data
        assert "by_status" in data
