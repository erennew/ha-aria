"""Tests for pattern scale classification."""

from aria.engine.pattern_scale import PatternScale


class TestPatternScale:
    """Test time-scale classification for patterns."""

    def test_enum_values(self):
        """Three scales exist with correct string values."""
        assert PatternScale.MICRO.value == "micro"
        assert PatternScale.MESO.value == "meso"
        assert PatternScale.MACRO.value == "macro"

    def test_from_duration_micro(self):
        """Durations under 5 minutes classify as micro."""
        assert PatternScale.from_duration_seconds(10) == PatternScale.MICRO
        assert PatternScale.from_duration_seconds(60) == PatternScale.MICRO
        assert PatternScale.from_duration_seconds(299) == PatternScale.MICRO

    def test_from_duration_meso(self):
        """Durations from 5 minutes to 4 hours classify as meso."""
        assert PatternScale.from_duration_seconds(300) == PatternScale.MESO
        assert PatternScale.from_duration_seconds(3600) == PatternScale.MESO
        assert PatternScale.from_duration_seconds(14399) == PatternScale.MESO

    def test_from_duration_macro(self):
        """Durations 4 hours and above classify as macro."""
        assert PatternScale.from_duration_seconds(14400) == PatternScale.MACRO
        assert PatternScale.from_duration_seconds(86400) == PatternScale.MACRO

    def test_from_duration_zero(self):
        """Zero duration is micro."""
        assert PatternScale.from_duration_seconds(0) == PatternScale.MICRO

    def test_scale_description(self):
        """Each scale has a human-readable description."""
        assert PatternScale.MICRO.description  # Not empty
        assert PatternScale.MESO.description
        assert PatternScale.MACRO.description

    def test_scale_window_range(self):
        """Each scale reports its duration range as (min_s, max_s)."""
        micro_range = PatternScale.MICRO.window_range
        assert micro_range == (0, 300)
        meso_range = PatternScale.MESO.window_range
        assert meso_range == (300, 14400)
        macro_range = PatternScale.MACRO.window_range
        assert macro_range == (14400, None)  # Unbounded upper
