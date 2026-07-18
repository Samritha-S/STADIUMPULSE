"""
Tests for SimulationState in simulation_state.py.

All tests are deterministic (no real server required) and run fully offline.
We construct fresh SimulationState instances per test so module-level singleton
state does not leak between test cases.
"""

import sys
import os
import unittest

# Ensure backend modules are on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

from simulation_state import SimulationState, ZONE_DEFS, MAX_HISTORY_LEN


# ---------------------------------------------------------------------------
# Helper: minimal zone-def list for unit tests (fewer zones = faster tests)
# ---------------------------------------------------------------------------

MINIMAL_ZONE_DEFS = [
    {
        "zone_id": "zone_normal",
        "zone_name": "Normal Zone",
        "capacity": 1000,
        "scenario_type": "normal",
        "metadata": {
            "zone_id": "zone_normal",
            "zone_name": "Normal Zone",
            "connected_gates": ["gate_1"],
            "accessible_routes": ["route_1"],
        },
    },
    {
        "zone_id": "zone_escalating",
        "zone_name": "Escalating Zone",
        "capacity": 800,
        "scenario_type": "escalating",
        "metadata": {
            "zone_id": "zone_escalating",
            "zone_name": "Escalating Zone",
            "connected_gates": ["gate_2"],
            "accessible_routes": ["route_2"],
        },
    },
]

ESCALATING_ONLY_DEFS = [
    {
        "zone_id": "zone_south_main",
        "zone_name": "South Main Concourse",
        "capacity": 800,
        "scenario_type": "escalating",
        "metadata": {
            "zone_id": "zone_south_main",
            "zone_name": "South Main Concourse",
            "connected_gates": ["gate_1", "gate_2"],
            "accessible_routes": ["ramp_south_1", "elevator_south"],
        },
    }
]


class TestTickAdvancesZoneCounts(unittest.TestCase):
    """tick() must produce a different (and monotonically meaningful) count each call."""

    def test_tick_appends_to_history(self):
        """Each tick() call adds exactly one point to each zone's history."""
        sim = SimulationState(MINIMAL_ZONE_DEFS)
        initial_len = len(sim.get_history("zone_normal"))
        sim.tick()
        self.assertEqual(len(sim.get_history("zone_normal")), initial_len + 1)

    def test_multiple_ticks_produce_different_counts(self):
        """
        After several ticks the escalating zone's latest count should be higher
        than its seed count (proving the curve is climbing, not flat).

        We use the escalating curve which is deterministic in direction (always
        increases) but not in exact value due to noise.  We sample across 8 ticks
        and assert the last count is greater than the seed.
        """
        sim = SimulationState(ESCALATING_ONLY_DEFS)
        seed_count = sim.get_history("zone_south_main")[0]

        for _ in range(8):
            sim.tick()

        latest_count = sim.get_history("zone_south_main")[-1]
        # The escalating curve adds ~2.5% of 800 (~20) per tick before noise;
        # over 8 ticks from seed tick ≥5, the count should be clearly higher.
        self.assertGreater(latest_count, seed_count,
            msg=f"Expected count to climb over 8 ticks; seed={seed_count}, latest={latest_count}")

    def test_tick_counter_increments(self):
        """get_tick_counter() should reflect the number of ticks since init."""
        sim = SimulationState(MINIMAL_ZONE_DEFS)
        initial_tick = sim.get_tick_counter("zone_normal")
        sim.tick()
        sim.tick()
        self.assertEqual(sim.get_tick_counter("zone_normal"), initial_tick + 2)


class TestHistoryBound(unittest.TestCase):
    """History must never exceed MAX_HISTORY_LEN entries, no matter how many ticks."""

    def test_history_stays_bounded_after_many_ticks(self):
        """Run 3× MAX_HISTORY_LEN ticks and confirm history never exceeds the cap."""
        sim = SimulationState(MINIMAL_ZONE_DEFS)
        for _ in range(MAX_HISTORY_LEN * 3):
            sim.tick()

        for zdef in MINIMAL_ZONE_DEFS:
            hist = sim.get_history(zdef["zone_id"])
            self.assertLessEqual(
                len(hist), MAX_HISTORY_LEN,
                msg=f"{zdef['zone_id']} history has {len(hist)} points (limit {MAX_HISTORY_LEN})"
            )

    def test_history_never_empty(self):
        """Even before ticking, history should be seeded with at least one point."""
        sim = SimulationState(MINIMAL_ZONE_DEFS)
        for zdef in MINIMAL_ZONE_DEFS:
            self.assertGreater(len(sim.get_history(zdef["zone_id"])), 0)


class TestEscalatingZoneReachesCritical(unittest.TestCase):
    """
    The 'escalating' zone must reach 'critical' status (>90% capacity forecast)
    within 8–12 ticks from a fresh SimulationState, making the demo visually
    interesting within a short polling window.
    """

    def test_escalating_zone_goes_critical_within_12_ticks(self):
        """
        Tick up to 20 times maximum and verify 'critical' status is seen by
        tick 12 at the latest.  The escalating curve ramps from ~70% to ~95%
        capacity over 10 ticks, so forecast_zone (which extrapolates 15 min
        ahead) should flag 'critical' well before tick 12.
        """
        sim = SimulationState(ESCALATING_ONLY_DEFS)
        reached_critical = False
        ticks_to_critical = None

        for t in range(1, 21):  # allow up to 20 ticks as a safety margin
            sim.tick()
            states = sim.get_current_zone_states()
            zone_state = next(z for z in states if z["zone_id"] == "zone_south_main")
            if zone_state["status"] == "critical":
                reached_critical = True
                ticks_to_critical = t
                break

        self.assertTrue(
            reached_critical,
            "Escalating zone never reached 'critical' status within 20 ticks"
        )
        self.assertLessEqual(
            ticks_to_critical, 12,
            f"Expected 'critical' by tick 12 but reached it at tick {ticks_to_critical}"
        )


class TestGetCurrentZoneStates(unittest.TestCase):
    """get_current_zone_states() must return valid ZoneState dicts for every zone."""

    REQUIRED_KEYS = {
        "zone_id", "zone_name", "current_count", "capacity",
        "forecast_count_15min", "forecast_count_30min", "status",
        "connected_gates", "accessible_routes",
    }
    VALID_STATUSES = {"normal", "watch", "critical"}

    def test_returns_one_state_per_zone(self):
        """Should return exactly as many states as zone definitions."""
        sim = SimulationState(MINIMAL_ZONE_DEFS)
        states = sim.get_current_zone_states()
        self.assertEqual(len(states), len(MINIMAL_ZONE_DEFS))

    def test_state_has_all_required_keys(self):
        """Every returned ZoneState must contain all schema-required keys."""
        sim = SimulationState(MINIMAL_ZONE_DEFS)
        for state in sim.get_current_zone_states():
            missing = self.REQUIRED_KEYS - state.keys()
            self.assertFalse(
                missing,
                msg=f"Zone {state.get('zone_id')} missing keys: {missing}"
            )

    def test_state_has_valid_status(self):
        """Status field must be one of the three allowed values."""
        sim = SimulationState(MINIMAL_ZONE_DEFS)
        for state in sim.get_current_zone_states():
            self.assertIn(state["status"], self.VALID_STATUSES)

    def test_forecasts_are_non_negative(self):
        """Forecast counts must never be negative."""
        sim = SimulationState(MINIMAL_ZONE_DEFS)
        for state in sim.get_current_zone_states():
            self.assertGreaterEqual(state["forecast_count_15min"], 0)
            self.assertGreaterEqual(state["forecast_count_30min"], 0)

    def test_get_state_is_idempotent_without_tick(self):
        """
        Calling get_current_zone_states() twice without ticking in between
        must return identical current_count values (no side effects).
        """
        sim = SimulationState(MINIMAL_ZONE_DEFS)
        first = {z["zone_id"]: z["current_count"] for z in sim.get_current_zone_states()}
        second = {z["zone_id"]: z["current_count"] for z in sim.get_current_zone_states()}
        self.assertEqual(first, second)


class TestFullZoneDefsIntegration(unittest.TestCase):
    """Smoke-test using the exact ZONE_DEFS from simulation_state to ensure no import errors."""

    def test_full_zone_defs_initialise_and_tick(self):
        """Create a SimulationState with the production ZONE_DEFS and run 3 ticks."""
        sim = SimulationState(ZONE_DEFS)
        for _ in range(3):
            sim.tick()
        states = sim.get_current_zone_states()
        self.assertEqual(len(states), len(ZONE_DEFS))
        for state in states:
            self.assertIn("current_count", state)
            self.assertIn("status", state)


if __name__ == '__main__':
    unittest.main()
