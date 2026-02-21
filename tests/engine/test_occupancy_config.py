"""Tests for BayesianOccupancy instance-level sensor config."""

from aria.engine.analysis.occupancy import (
    DEFAULT_PRIOR,
    SENSOR_CONFIG,
    BayesianOccupancy,
)


class TestInstanceSensorConfig:
    def test_default_config_matches_module_constant(self):
        occ = BayesianOccupancy()
        assert occ.sensor_config == SENSOR_CONFIG

    def test_update_sensor_config_overrides(self):
        occ = BayesianOccupancy()
        custom = {"motion": {"weight": 0.5, "decay_seconds": 60}}
        occ.update_sensor_config(custom)
        assert occ.sensor_config["motion"]["weight"] == 0.5
        assert occ.sensor_config["motion"]["decay_seconds"] == 60
        # Other signal types unchanged
        assert occ.sensor_config["door"]["weight"] == SENSOR_CONFIG["door"]["weight"]

    def test_update_partial_fields(self):
        """Updating only weight keeps existing decay_seconds."""
        occ = BayesianOccupancy()
        occ.update_sensor_config({"motion": {"weight": 0.5}})
        assert occ.sensor_config["motion"]["weight"] == 0.5
        assert occ.sensor_config["motion"]["decay_seconds"] == SENSOR_CONFIG["motion"]["decay_seconds"]

    def test_unknown_signal_type_ignored(self):
        """Unknown signal types in overrides are silently ignored."""
        occ = BayesianOccupancy()
        occ.update_sensor_config({"nonexistent_sensor": {"weight": 0.9}})
        assert "nonexistent_sensor" not in occ.sensor_config

    def test_bayesian_fuse_uses_instance_config(self):
        occ = BayesianOccupancy()
        # Low motion weight = less posterior shift
        occ.update_sensor_config({"motion": {"weight": 0.1, "decay_seconds": 300}})
        low_result = occ._bayesian_fuse(
            DEFAULT_PRIOR,
            [("motion", 0.95, "test")],
        )
        occ.update_sensor_config({"motion": {"weight": 0.9, "decay_seconds": 300}})
        high_result = occ._bayesian_fuse(
            DEFAULT_PRIOR,
            [("motion", 0.95, "test")],
        )
        assert high_result > low_result

    def test_independent_instances(self):
        """Two BayesianOccupancy instances don't share sensor_config."""
        occ1 = BayesianOccupancy()
        occ2 = BayesianOccupancy()
        occ1.update_sensor_config({"motion": {"weight": 0.1}})
        assert occ2.sensor_config["motion"]["weight"] == SENSOR_CONFIG["motion"]["weight"]
