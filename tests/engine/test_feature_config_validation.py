"""Tests for feature config validation — pattern_features included."""

import copy

from aria.engine.features.feature_config import (
    DEFAULT_FEATURE_CONFIG,
    validate_feature_config,
)


class TestValidateFeatureConfig:
    """Validation catches malformed configs."""

    def test_valid_default_config(self):
        """Default config passes validation."""
        errors = validate_feature_config(copy.deepcopy(DEFAULT_FEATURE_CONFIG))
        assert errors == []

    def test_missing_pattern_features_section(self):
        """Missing pattern_features is an error."""
        config = copy.deepcopy(DEFAULT_FEATURE_CONFIG)
        del config["pattern_features"]
        errors = validate_feature_config(config)
        assert any("pattern_features" in e for e in errors)

    def test_pattern_features_non_bool_rejected(self):
        """Non-bool value in pattern_features is caught."""
        config = copy.deepcopy(DEFAULT_FEATURE_CONFIG)
        config["pattern_features"]["trajectory_class"] = "yes"
        errors = validate_feature_config(config)
        assert any("pattern_features.trajectory_class" in e for e in errors)

    def test_pattern_features_bool_accepted(self):
        """Bool values in pattern_features pass validation."""
        config = copy.deepcopy(DEFAULT_FEATURE_CONFIG)
        config["pattern_features"]["trajectory_class"] = False
        errors = validate_feature_config(config)
        assert errors == []
