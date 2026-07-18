"""
StadiumPulse — Minimal FastAPI backend server.

Exposes three endpoints:
  GET /api/zones   -> List[ZoneState]
  GET /api/briefs  -> List[ControlRoomBrief]   (watch/critical zones only)
  GET /api/nudge   -> FanNudge  (query: fan_id, language, mobility_needs)

Run with:
  cd stadiumpulse
  uvicorn backend.server:app --reload --port 8000
"""

import os
import sys
from typing import Any, Dict, List

# ── allow  `uvicorn backend.server:app` from the stadiumpulse/ working dir
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

# Robustly load .env from multiple potential locations (CWD, ancestors, and relative paths)
load_dotenv()
_here = os.path.dirname(__file__)
load_dotenv(dotenv_path=os.path.join(_here, "../.env"))
load_dotenv(dotenv_path=os.path.join(_here, "../../.env"))

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from forecast.data_generator import generate_zone_scenario
from forecast.forecast_service import forecast_zone
from reasoning.generate_brief import generate_brief
from reasoning.generate_nudge import generate_nudge

app = FastAPI(title="StadiumPulse API", version="0.1.0")

# Safe startup check for GEMINI_API_KEY presence
@app.on_event("startup")
def startup_event():
    import logging
    srv_logger = logging.getLogger("stadiumpulse.server")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        msg = "WARNING: GEMINI_API_KEY not found in environment — reasoning layer will use fallback responses only"
        srv_logger.warning(msg)
        print(msg, flush=True)
    else:
        srv_logger.info("GEMINI_API_KEY successfully found in environment.")
        print("GEMINI_API_KEY successfully found in environment.", flush=True)

# ── CORS: allow any localhost origin so the frontend HTML files can call us
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
        "null",  # file:// opened pages send Origin: null
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Zone definitions ─────────────────────────────────────────────────────────
# Four predefined zones: two normal, one ramping toward watch, one spiking to critical.
# Scenario type and capacity are the only tuneable parameters; all other metadata
# lives here so the frontend and reasoning layer always get the right names/gates.

ZONE_DEFS = [
    {
        "zone_id": "zone_east_concourse",
        "zone_name": "East Concourse",
        "capacity": 800,
        "scenario_type": "normal",
        "duration_minutes": 30,
        "metadata": {
            "zone_id": "zone_east_concourse",
            "zone_name": "East Concourse",
            "connected_gates": ["gate_5", "gate_6"],
            "accessible_routes": ["ramp_east_1", "elevator_east"],
        },
    },
    {
        "zone_id": "zone_north_gate3",
        "zone_name": "North Concourse Gate 3",
        "capacity": 800,
        "scenario_type": "spike",          # trending toward watch
        "duration_minutes": 20,            # shorter history → mid-surge
        "metadata": {
            "zone_id": "zone_north_gate3",
            "zone_name": "North Concourse Gate 3",
            "connected_gates": ["gate_3", "gate_4"],
            "accessible_routes": ["ramp_north_1", "elevator_north"],
        },
    },
    {
        "zone_id": "zone_south_main",
        "zone_name": "South Main Concourse",
        "capacity": 800,
        "scenario_type": "spike",          # full 30-min spike → critical
        "duration_minutes": 30,
        "metadata": {
            "zone_id": "zone_south_main",
            "zone_name": "South Main Concourse",
            "connected_gates": ["gate_1", "gate_2"],
            "accessible_routes": ["ramp_south_1", "elevator_south"],
        },
    },
    {
        "zone_id": "zone_west_standing",
        "zone_name": "West Standing Area",
        "capacity": 600,
        "scenario_type": "normal",
        "duration_minutes": 30,
        "metadata": {
            "zone_id": "zone_west_standing",
            "zone_name": "West Standing Area",
            "connected_gates": ["gate_7"],
            "accessible_routes": ["ramp_west_1"],
        },
    },
]


def _compute_zone_states() -> List[Dict[str, Any]]:
    """
    Generate synthetic history for every zone and run it through forecast_zone.
    Returns a list of ZoneState dicts matching the shared schema.

    Called by both /api/zones and /api/briefs so the two endpoints see the
    same snapshot (recomputed on each request — acceptable for a hackathon demo;
    a production system would cache this with a short TTL).
    """
    states = []
    for zdef in ZONE_DEFS:
        series = generate_zone_scenario(
            zone_id=zdef["zone_id"],
            duration_minutes=zdef["duration_minutes"],
            scenario_type=zdef["scenario_type"],
            capacity=zdef["capacity"],
        )
        history = [count for _, count in series]
        state = forecast_zone(
            zone_history=history,
            capacity=zdef["capacity"],
            zone_metadata=zdef["metadata"],
        )
        states.append(state)
    return states


def _most_urgent_zone(states: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Return the zone with the highest urgency.
    Priority: critical > watch > normal.
    Within the same status level, pick the one with the highest occupancy ratio.
    """
    priority = {"critical": 2, "watch": 1, "normal": 0}
    return max(
        states,
        key=lambda z: (
            priority.get(z["status"], 0),
            z["current_count"] / max(z["capacity"], 1),
        ),
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/zones", response_model=List[Dict[str, Any]])
def get_zones():
    """
    Returns the current ZoneState for every predefined zone.
    Synthetic crowd history is regenerated on each call so counts evolve
    naturally across refreshes during the demo.
    """
    return _compute_zone_states()


@app.get("/api/briefs", response_model=List[Dict[str, Any]])
def get_briefs():
    """
    For every zone with status 'watch' or 'critical', calls generate_brief
    and returns the resulting ControlRoomBrief list, most urgent first.

    Returns an empty list if all zones are currently in normal status.
    """
    states = _compute_zone_states()
    alert_zones = [z for z in states if z["status"] in ("watch", "critical")]

    # Sort: critical first, then watch; secondary sort by occupancy ratio
    priority = {"critical": 2, "watch": 1}
    alert_zones.sort(
        key=lambda z: (
            priority.get(z["status"], 0),
            z["current_count"] / max(z["capacity"], 1),
        ),
        reverse=True,
    )

    briefs = []
    for zone in alert_zones:
        brief = generate_brief(zone)
        briefs.append(brief)
    return briefs


@app.get("/api/nudge", response_model=Dict[str, Any])
def get_nudge(
    fan_id: str = Query(default="fan_demo"),
    language: str = Query(default="en"),
    mobility_needs: bool = Query(default=False),
):
    """
    Picks the most urgent zone and generates a personalised FanNudge
    for the fan profile supplied via query parameters.

    Query params:
      fan_id         (str)  – identifier for the fan
      language       (str)  – ISO 639-1 code, e.g. 'en', 'es', 'fr'
      mobility_needs (bool) – true = step-free route required
    """
    states = _compute_zone_states()
    target_zone = _most_urgent_zone(states)

    fan_profile = {
        "fan_id": fan_id,
        "language": language,
        "mobility_needs": mobility_needs,
    }

    nudge = generate_nudge(target_zone, fan_profile)
    return nudge
