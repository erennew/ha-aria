"""Activity Monitor validation — verify event processing with synthetic data."""

from aria.modules.activity_monitor import TRACKED_DOMAINS
from tests.synthetic.events import EventStreamGenerator
from tests.synthetic.simulator import HouseholdSimulator


class TestActivityMonitorWithSyntheticEvents:
    """Activity monitor should process synthetic events into activity windows."""

    def test_events_match_tracked_domains(self):
        """Synthetic events should include domains the activity monitor tracks."""
        sim = HouseholdSimulator(scenario="stable_couple", days=7, seed=42)
        events = EventStreamGenerator(sim.generate()).generate()
        event_domains = {e["domain"] for e in events}
        tracked = event_domains & TRACKED_DOMAINS
        assert len(tracked) >= 2, f"Should have >=2 tracked domains, found: {tracked}"

    def test_event_volume_reasonable(self):
        """30 days of stable_couple should produce substantial events."""
        sim = HouseholdSimulator(scenario="stable_couple", days=30, seed=42)
        events = EventStreamGenerator(sim.generate()).generate()
        tracked = [e for e in events if e["domain"] in TRACKED_DOMAINS]
        assert len(tracked) >= 50, f"30 days should have >=50 tracked events, got {len(tracked)}"

    def test_stable_has_more_activity_than_vacation(self):
        """Stable household should produce more activity events than vacation."""
        sim_stable = HouseholdSimulator(scenario="stable_couple", days=14, seed=42)
        sim_vacation = HouseholdSimulator(scenario="vacation", days=14, seed=42)
        events_stable = EventStreamGenerator(sim_stable.generate()).generate()
        events_vacation = EventStreamGenerator(sim_vacation.generate()).generate()
        tracked_stable = [e for e in events_stable if e["domain"] in TRACKED_DOMAINS]
        tracked_vacation = [e for e in events_vacation if e["domain"] in TRACKED_DOMAINS]
        assert len(tracked_stable) >= len(tracked_vacation), (
            f"Stable ({len(tracked_stable)}) should have >= vacation ({len(tracked_vacation)}) events"
        )

    def test_all_scenarios_produce_activity_events(self, all_scenario_results):
        """Every scenario should produce events matching tracked domains."""
        for scenario, data in all_scenario_results.items():
            events = EventStreamGenerator(data["snapshots"]).generate()
            tracked = [e for e in events if e["domain"] in TRACKED_DOMAINS]
            assert len(tracked) > 0, f"{scenario}: no tracked activity events"
