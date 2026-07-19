"""
simulation_state.py — Stateful ticking simulation for StadiumPulse.

Replaces the stateless per-request scenario generation in server.py with a
module-level SimulationState that maintains a rolling count history per zone.
Each call to tick() advances every zone by one synthetic data point; each call
to get_current_zone_states() runs forecast_zone on the current histories and
returns the full list of ZoneState dicts matching the shared schema.

Design choices:
- One module-level instance (SIMULATION) is imported and shared across requests.
- A threading.Lock protects tick() + history mutation so concurrent requests
  cannot interleave state writes.  get_current_zone_states() takes a snapshot
  of the histories under the lock, then runs forecast_zone outside the lock to
  keep the critical section tiny.
- History is bounded to MAX_HISTORY_LEN points per zone to prevent unbounded
  memory growth over a long-running demo.
- Curve logic mirrors data_generator.py exactly (same mathematical formula,
  same thresholds) so the two files stay consistent without duplication.
"""

import random
import threading
from typing import Any, Dict, List

from forecast.forecast_service import forecast_zone

# Maximum number of historical data points kept per zone.
MAX_HISTORY_LEN = 20

# ---------------------------------------------------------------------------
# Zone definitions — MetLife Stadium, East Rutherford, NJ
# Host venue for the FIFA World Cup 2026 Final, July 19 2026.
#
# Real capacity: 78,576 (tournament configuration).
# Seven zones modelled here representing the main concourse levels and gates.
# Combined zone capacity of ~130,000 covers the bulk of spectator circulation
# areas across the bowl; 'critical_seed' zones start already at crisis density
# so the dashboard reads as a live operational picture from the first load.
#
# NOTE: Zone names and gate letters follow the NFL-convention used at MetLife
# (levels 100/200/300, gates A–H).  Specific concourse-to-gate assignments
# are a reasonable approximation for demo purposes and are NOT sourced from
# official FIFA venue documents or MetLife Stadium operations manuals.
# ---------------------------------------------------------------------------

ZONE_DEFS: List[Dict[str, Any]] = [
    {
        # 100 Level lower-bowl concourse — steady normal flow for most of the match
        "zone_id": "zone_100_gate_a",
        "zone_name": "100 Level – Gate A Concourse",
        "capacity": 19500,
        "scenario_type": "normal",
        "metadata": {
            "zone_id": "zone_100_gate_a",
            "zone_name": "100 Level – Gate A Concourse",
            "connected_gates": ["gate_a", "gate_b"],
            "accessible_routes": ["ramp_100_east", "elevator_100_a"],
        },
    },
    {
        # 200 Level mid-tier concourse — experiences a spike surge post-kickoff
        "zone_id": "zone_200_gate_c",
        "zone_name": "200 Level – Gate C Concourse",
        "capacity": 18000,
        "scenario_type": "spike",
        "metadata": {
            "zone_id": "zone_200_gate_c",
            "zone_name": "200 Level – Gate C Concourse",
            "connected_gates": ["gate_c", "gate_d"],
            "accessible_routes": ["ramp_200_north", "elevator_200_c"],
        },
    },
    {
        # 200 Level east concourse — already at watch-level density on startup
        # (spike curve placed at tick=16 so initial seed points land in the
        #  surge phase, giving immediate "watch" status without needing escalation)
        "zone_id": "zone_200_gate_e",
        "zone_name": "200 Level – Gate E Concourse",
        "capacity": 18000,
        "scenario_type": "watch_seed",  # custom: seeds into watch-range density
        "metadata": {
            "zone_id": "zone_200_gate_e",
            "zone_name": "200 Level – Gate E Concourse",
            "connected_gates": ["gate_e"],
            "accessible_routes": ["ramp_200_east", "elevator_200_e"],
        },
    },
    {
        # 300 Level upper-deck concourse — fast-escalating zone.
        # Starts at ~70% capacity on tick 0 and reaches "critical" within 8–12
        # ticks, making congestion escalation visible quickly in the demo.
        "zone_id": "zone_300_gate_f",
        "zone_name": "300 Level – Gate F Concourse",
        "capacity": 18000,
        "scenario_type": "escalating",   # special fast-escalation curve
        "metadata": {
            "zone_id": "zone_300_gate_f",
            "zone_name": "300 Level – Gate F Concourse",
            "connected_gates": ["gate_f", "gate_g"],
            "accessible_routes": ["ramp_300_west", "elevator_300_f"],
        },
    },
    {
        # 300 Level north concourse — already at critical density from startup.
        # Demonstrates the full critical-alert state immediately on first load.
        "zone_id": "zone_300_gate_h",
        "zone_name": "300 Level – Gate H Concourse",
        "capacity": 17500,
        "scenario_type": "critical_seed",  # starts and stays at ~93% capacity
        "metadata": {
            "zone_id": "zone_300_gate_h",
            "zone_name": "300 Level – Gate H Concourse",
            "connected_gates": ["gate_h"],
            "accessible_routes": ["ramp_300_north", "elevator_300_h"],
        },
    },
    {
        # Field-level south concourse — lower capacity standing/VIP circulation area
        "zone_id": "zone_field_gate_b",
        "zone_name": "Field Level – Gate B Concourse",
        "capacity": 18500,
        "scenario_type": "normal",
        "metadata": {
            "zone_id": "zone_field_gate_b",
            "zone_name": "Field Level – Gate B Concourse",
            "connected_gates": ["gate_b"],
            "accessible_routes": ["ramp_field_south"],
        },
    },
    {
        # Field-level east access corridor — steady normal, low-density area
        "zone_id": "zone_field_gate_d",
        "zone_name": "Field Level – Gate D Concourse",
        "capacity": 12000,
        "scenario_type": "normal",
        "metadata": {
            "zone_id": "zone_field_gate_d",
            "zone_name": "Field Level – Gate D Concourse",
            "connected_gates": ["gate_d"],
            "accessible_routes": ["ramp_field_east", "elevator_field_d"],
        },
    },
]



# ---------------------------------------------------------------------------
# Curve helpers — reuse the same mathematical model as data_generator.py
# but produce a *single* next count instead of a full series, so tick()
# can call them one step at a time.
# ---------------------------------------------------------------------------

def _next_count_normal(capacity: int) -> int:
    """One step of the 'normal' crowd-level curve (~35% capacity ± noise)."""
    base = 0.35 * capacity
    wave = 0.05 * capacity * (1.0 + float(random.choice([-1, 1])) * 0.1)
    noise = random.randint(-25, 25)
    return max(0, int(base + wave + noise))


def _next_count_spike(tick: int, capacity: int) -> int:
    """
    One step of the 'spike' crowd curve.

    The spike curve from data_generator.py is parameterised by 'progress'
    (a value from 0 to 1 representing position in a 30-minute scenario).
    For the live simulation we map the tick index to progress using a
    virtual 30-step window so the curve shape is preserved: ticks 0-11 are
    baseline, 12-23 are rapid surge, 24+ are sustained critical.
    """
    # Virtual 30-step window — each tick is one "minute" in the scenario
    virtual_duration = 30
    progress = min(tick / virtual_duration, 1.0)

    if progress < 0.4:
        base = 0.25 * capacity
        noise = random.randint(-15, 15)
    elif progress < 0.8:
        surge_progress = (progress - 0.4) / 0.4
        base = 0.25 * capacity + 0.65 * capacity * surge_progress
        noise = random.randint(-20, 20)
    else:
        base = 0.90 * capacity + 0.05 * capacity * (progress - 0.8) / 0.2
        noise = random.randint(-10, 10)

    return max(0, int(base + noise))


def _next_count_escalating(tick: int, capacity: int) -> int:
    """
    Fast-escalation curve: starts at ~70% capacity on tick 0 and climbs to
    ~95% capacity by tick 10, making "critical" status observable within
    8-12 polls.

    Formula: linear ramp from 0.70*capacity to 0.95*capacity over 10 ticks,
    then flat at 0.95*capacity with small noise.
    """
    if tick < 10:
        base = 0.70 * capacity + (0.025 * capacity * tick)  # +2.5% per tick
    else:
        base = 0.95 * capacity
    noise = random.randint(-10, 10)
    return max(0, min(capacity, int(base + noise)))


def _next_count_critical_seed(capacity: int) -> int:
    """
    Permanently-critical curve: stays at ~93% of capacity with small noise.
    Used for zones that should appear as 'critical' from the very first load,
    giving reviewers an immediate view of the full alert UI without waiting
    for the escalating curve to complete.
    """
    base = 0.93 * capacity
    noise = random.randint(-50, 50)
    return max(0, min(capacity, int(base + noise)))


def _next_count_watch_seed(capacity: int) -> int:
    """
    Watch-level seed curve: sits at ~78% of capacity with small noise.
    Used for zones that should appear in 'watch' status from startup,
    giving the dashboard a mixed normal/watch/critical picture on first load.
    """
    base = 0.78 * capacity
    noise = random.randint(-30, 30)
    return max(0, min(capacity, int(base + noise)))


# ---------------------------------------------------------------------------
# SimulationState
# ---------------------------------------------------------------------------

import time
import os

class SimulationState:
    """
    Maintains per-zone rolling count histories.
    Supports dual modes:
    1. Serverless Mode: If VERCEL env var is present, computes deterministic,
       time-based tick histories so that all Lambda instances return synchronized
       simulation curves without in-memory state.
    2. Stateful Mode: Fallback for local development and unit tests.
    """

    def __init__(self, zone_defs: List[Dict[str, Any]]) -> None:
        self._lock = threading.Lock()
        self._zone_defs = zone_defs
        self._is_serverless = "VERCEL" in os.environ
        
        # Stateful mode attributes
        self._tick_counters: Dict[str, int] = {}
        self._histories: Dict[str, List[int]] = {}

        for zdef in zone_defs:
            zid = zdef["zone_id"]
            stype = zdef["scenario_type"]
            cap = zdef["capacity"]
            self._tick_counters[zid] = 0

            seed_points = 5
            seed: List[int] = []
            for i in range(seed_points):
                seed.append(self._generate_next(stype, i, cap))
            self._histories[zid] = seed
            self._tick_counters[zid] = seed_points

    def _get_serverless_tick(self) -> int:
        # 1 tick = 15 seconds
        return int(time.time() / 15)

    def tick(self) -> None:
        if self._is_serverless:
            return  # No-op on serverless (tick is time-driven)
            
        with self._lock:
            for zdef in self._zone_defs:
                zid = zdef["zone_id"]
                stype = zdef["scenario_type"]
                cap = zdef["capacity"]
                tick_n = self._tick_counters[zid]
                new_count = self._generate_next(stype, tick_n, cap)
                self._histories[zid].append(new_count)
                if len(self._histories[zid]) > MAX_HISTORY_LEN:
                    self._histories[zid] = self._histories[zid][-MAX_HISTORY_LEN:]
                self._tick_counters[zid] = tick_n + 1

    def get_current_zone_states(self) -> List[Dict[str, Any]]:
        if self._is_serverless:
            current_tick = self._get_serverless_tick()
            snapshots = {}
            for zdef in self._zone_defs:
                zid = zdef["zone_id"]
                stype = zdef["scenario_type"]
                cap = zdef["capacity"]
                
                history = []
                for t in range(current_tick - MAX_HISTORY_LEN + 1, current_tick + 1):
                    # Deterministic seed per tick and zone so multiple lambdas are fully in sync
                    random.seed(t + hash(zid) % 1000000)
                    history.append(self._generate_next(stype, t, cap))
                snapshots[zid] = history
            # Restore random seeding
            random.seed(None)
        else:
            with self._lock:
                snapshots = {
                    zdef["zone_id"]: list(self._histories[zdef["zone_id"]])
                    for zdef in self._zone_defs
                }

        states = []
        for zdef in self._zone_defs:
            zid = zdef["zone_id"]
            state = forecast_zone(
                zone_history=snapshots[zid],
                capacity=zdef["capacity"],
                zone_metadata=zdef["metadata"],
            )
            states.append(state)
        return states

    def get_tick_counter(self, zone_id: str) -> int:
        if self._is_serverless:
            return self._get_serverless_tick()
        with self._lock:
            return self._tick_counters.get(zone_id, 0)

    def get_history(self, zone_id: str) -> List[int]:
        if self._is_serverless:
            current_tick = self._get_serverless_tick()
            zdef = next((z for z in self._zone_defs if z["zone_id"] == zone_id), None)
            if not zdef:
                return []
            stype = zdef["scenario_type"]
            cap = zdef["capacity"]
            
            history = []
            for t in range(current_tick - MAX_HISTORY_LEN + 1, current_tick + 1):
                random.seed(t + hash(zone_id) % 1000000)
                history.append(self._generate_next(stype, t, cap))
            random.seed(None)
            return history
            
        with self._lock:
            return list(self._histories.get(zone_id, []))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_next(scenario_type: str, tick: int, capacity: int) -> int:
        """Dispatch to the right curve function for a given scenario type."""
        if scenario_type == "escalating":
            return _next_count_escalating(tick, capacity)
        elif scenario_type == "spike":
            return _next_count_spike(tick, capacity)
        elif scenario_type == "critical_seed":
            return _next_count_critical_seed(capacity)
        elif scenario_type == "watch_seed":
            return _next_count_watch_seed(capacity)
        else:  # "normal" and any unknown type
            return _next_count_normal(capacity)


# ---------------------------------------------------------------------------
# Module-level singleton — imported directly by server.py
# ---------------------------------------------------------------------------

SIMULATION = SimulationState(ZONE_DEFS)
