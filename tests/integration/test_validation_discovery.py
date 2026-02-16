"""Discovery module validation — verify entity/capability detection with synthetic data."""

from tests.synthetic.events import EventStreamGenerator
from tests.synthetic.simulator import HouseholdSimulator


class TestDiscoveryWithSyntheticData:
    """Discovery should detect entities and capabilities from synthetic HA data."""

    def test_synthetic_data_has_entity_domains(self):
        """Synthetic snapshots should contain entity-relevant data sections."""
        sim = HouseholdSimulator(scenario="stable_couple", days=3, seed=42)
        snapshots = sim.generate()
        last = snapshots[-1]
        # Check for domain-relevant sections
        has_lights = "lights" in last
        has_motion = "motion" in last
        has_climate = "climate" in last
        assert has_lights or has_motion or has_climate, (
            f"Snapshot should have entity sections, got keys: {list(last.keys())}"
        )

    def test_entity_extraction_covers_multiple_domains(self):
        """EventStreamGenerator should extract entities from multiple domains."""
        sim = HouseholdSimulator(scenario="stable_couple", days=3, seed=42)
        snapshots = sim.generate()
        gen = EventStreamGenerator(snapshots)
        events = gen.generate()
        domains = {e["domain"] for e in events}
        assert len(domains) >= 3, f"Should cover >=3 domains, found: {domains}"

    def test_degradation_scenario_still_discoverable(self):
        """Sensor degradation should not prevent entity discovery."""
        sim = HouseholdSimulator(scenario="sensor_degradation", days=7, seed=42)
        snapshots = sim.generate()
        gen = EventStreamGenerator(snapshots)
        events = gen.generate()
        assert len(events) > 0, "Degradation scenario should still produce events"
        domains = {e["domain"] for e in events}
        assert len(domains) >= 2, "Should still find >=2 domains despite degradation"

    def test_all_scenarios_produce_discoverable_entities(self, all_scenario_results):
        """Every scenario should produce entities from multiple domains."""
        for scenario, data in all_scenario_results.items():
            snapshots = data["snapshots"]
            gen = EventStreamGenerator(snapshots)
            events = gen.generate()
            domains = {e["domain"] for e in events}
            assert len(domains) >= 2, f"{scenario}: should have >=2 domains, found {domains}"
