"""Pattern Recognition validation — behavioral pattern detection from synthetic events."""

from collections import defaultdict
from datetime import datetime

from tests.synthetic.events import EventStreamGenerator
from tests.synthetic.simulator import HouseholdSimulator


class TestPatternRecognitionValidation:
    """Pattern recognition should detect patterns in synthetic event streams."""

    def test_stable_scenario_has_repeating_sequences(self):
        """Stable couple should produce repeating daily patterns."""
        sim = HouseholdSimulator(scenario="stable_couple", days=14, seed=42)
        events = EventStreamGenerator(sim.generate()).generate()
        hourly_patterns = defaultdict(lambda: defaultdict(int))
        for event in events:
            ts = datetime.fromisoformat(event["timestamp"])
            hourly_patterns[event["entity_id"]][ts.hour] += 1
        multi_hour = [eid for eid, hours in hourly_patterns.items() if len(hours) >= 3]
        assert len(multi_hour) > 0, "Should have entities active across multiple hours"

    def test_event_sequences_are_deterministic(self):
        """Same seed should produce identical event sequences."""
        sim1 = HouseholdSimulator(scenario="stable_couple", days=7, seed=42)
        sim2 = HouseholdSimulator(scenario="stable_couple", days=7, seed=42)
        events1 = EventStreamGenerator(sim1.generate(), seed=42).generate()
        events2 = EventStreamGenerator(sim2.generate(), seed=42).generate()
        assert len(events1) == len(events2), "Same seed should produce same count"
        for e1, e2 in zip(events1[:20], events2[:20], strict=False):
            assert e1["entity_id"] == e2["entity_id"]
            assert e1["new_state"] == e2["new_state"]

    def test_wfh_has_different_daytime_patterns(self):
        """WFH scenario should show more daytime activity than vacation."""
        sim_wfh = HouseholdSimulator(scenario="work_from_home", days=14, seed=42)
        sim_vacation = HouseholdSimulator(scenario="vacation", days=14, seed=42)
        events_wfh = EventStreamGenerator(sim_wfh.generate()).generate()
        events_vacation = EventStreamGenerator(sim_vacation.generate()).generate()

        def daytime_events(events):
            return [e for e in events if 9 <= datetime.fromisoformat(e["timestamp"]).hour <= 17]

        assert len(daytime_events(events_wfh)) >= len(daytime_events(events_vacation)), (
            "WFH should have >= daytime events than vacation"
        )

    def test_all_scenarios_produce_sequences(self, all_scenario_results):
        """Every scenario should produce event sequences."""
        for scenario, data in all_scenario_results.items():
            events = EventStreamGenerator(data["snapshots"]).generate()
            assert len(events) >= 10, f"{scenario}: should produce >=10 events"
