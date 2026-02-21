"""Tests for entity health scoring."""

from aria.shared.entity_health import compute_entity_health


class TestEntityHealthScoring:
    def test_healthy_entity(self):
        """Entity with <5% unavailable time is healthy."""
        events = [
            {"entity_id": "light.bed", "new_state": "on"},
            {"entity_id": "light.bed", "new_state": "off"},
        ] * 50  # 100 normal transitions, 0 unavailable
        result = compute_entity_health("light.bed", events, total_events=100)
        assert result.health_grade == "healthy"
        assert result.availability_pct > 0.95

    def test_flaky_entity(self):
        """Entity with 10-20% unavailable transitions is flaky."""
        normal = [{"entity_id": "sensor.x", "new_state": "on"}] * 85
        bad = [{"entity_id": "sensor.x", "new_state": "unavailable"}] * 15
        result = compute_entity_health("sensor.x", normal + bad, total_events=100)
        assert result.health_grade == "flaky"

    def test_unreliable_entity(self):
        """Entity with >20% unavailable transitions is unreliable."""
        normal = [{"entity_id": "sensor.x", "new_state": "on"}] * 60
        bad = [{"entity_id": "sensor.x", "new_state": "unavailable"}] * 40
        result = compute_entity_health("sensor.x", normal + bad, total_events=100)
        assert result.health_grade == "unreliable"

    def test_zero_events_is_unreliable(self):
        result = compute_entity_health("sensor.x", [], total_events=0)
        assert result.health_grade == "unreliable"

    def test_custom_threshold_raises_floor(self):
        """With min_available_pct=0.90, 85% available is unreliable (below floor)."""
        normal = [{"entity_id": "sensor.x", "new_state": "on"}] * 85
        bad = [{"entity_id": "sensor.x", "new_state": "unavailable"}] * 15
        result = compute_entity_health(
            "sensor.x", normal + bad, total_events=100, min_healthy_pct=0.95, min_available_pct=0.90
        )
        assert result.health_grade == "unreliable"

    def test_custom_threshold_flaky_band(self):
        """With min_available_pct=0.80, 92% available is flaky (between 80-95)."""
        normal = [{"entity_id": "sensor.x", "new_state": "on"}] * 92
        bad = [{"entity_id": "sensor.x", "new_state": "unavailable"}] * 8
        result = compute_entity_health(
            "sensor.x", normal + bad, total_events=100, min_healthy_pct=0.95, min_available_pct=0.80
        )
        assert result.health_grade == "flaky"
