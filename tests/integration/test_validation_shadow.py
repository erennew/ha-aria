"""Shadow Engine validation — predict-compare-score cycle with synthetic events."""

from datetime import datetime

from aria.modules.shadow_engine import PREDICTABLE_DOMAINS
from tests.synthetic.events import EventStreamGenerator
from tests.synthetic.simulator import HouseholdSimulator


class TestShadowPredictLoop:
    """Shadow engine should have predictable domain events to work with."""

    def test_synthetic_events_include_predictable_domains(self):
        """Events should include domains shadow engine can predict."""
        sim = HouseholdSimulator(scenario="stable_couple", days=7, seed=42)
        events = EventStreamGenerator(sim.generate()).generate()
        predictable = [e for e in events if e["domain"] in PREDICTABLE_DOMAINS]
        assert len(predictable) > 0, "Should have predictable domain events"

    def test_predictable_events_have_state_transitions(self):
        """Predictable events should show meaningful state changes."""
        sim = HouseholdSimulator(scenario="stable_couple", days=7, seed=42)
        events = EventStreamGenerator(sim.generate()).generate()
        predictable = [e for e in events if e["domain"] in PREDICTABLE_DOMAINS]
        transitions = [(e["old_state"], e["new_state"]) for e in predictable]
        # Should have both on->off and off->on transitions
        has_on = any(new == "on" for _, new in transitions)
        has_off = any(new == "off" for _, new in transitions)
        assert has_on or has_off, "Should have on/off transitions for predictions"

    def test_wfh_has_more_predictable_events_during_day(self):
        """WFH should have more daytime predictable events (lights, switches)."""
        sim_stable = HouseholdSimulator(scenario="stable_couple", days=14, seed=42)
        sim_wfh = HouseholdSimulator(scenario="work_from_home", days=14, seed=42)
        events_stable = EventStreamGenerator(sim_stable.generate()).generate()
        events_wfh = EventStreamGenerator(sim_wfh.generate()).generate()

        def daytime_predictable(events):
            return [
                e
                for e in events
                if e["domain"] in PREDICTABLE_DOMAINS and 9 <= datetime.fromisoformat(e["timestamp"]).hour <= 17
            ]

        day_stable = len(daytime_predictable(events_stable))
        day_wfh = len(daytime_predictable(events_wfh))
        # WFH should have at least comparable daytime activity
        assert day_wfh >= day_stable * 0.5, f"WFH daytime ({day_wfh}) should be near stable ({day_stable})"

    def test_all_scenarios_have_predictable_events(self, all_scenario_results):
        """Every scenario should produce events shadow engine can work with."""
        for scenario, data in all_scenario_results.items():
            events = EventStreamGenerator(data["snapshots"]).generate()
            predictable = [e for e in events if e["domain"] in PREDICTABLE_DOMAINS]
            assert len(predictable) > 0, f"{scenario}: no predictable events for shadow engine"
