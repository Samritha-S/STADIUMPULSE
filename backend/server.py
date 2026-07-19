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
import threading
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

from reasoning.generate_brief import generate_brief
from reasoning.generate_nudge import generate_nudge
from reasoning.generate_report import classify_report

# ── Stateful simulation — one shared instance for the lifetime of the process
from simulation_state import SIMULATION, ZONE_DEFS
from pydantic import BaseModel, Field

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
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

# Mount the dashboard under /admin and fan-view under /fan
# We must use directory absolute paths or paths relative to root.
# Since the app runs from workspace root, 'frontend/dashboard' and 'frontend/fan-view' are correct.
app.mount("/admin", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "../frontend/dashboard"), html=True), name="admin")
app.mount("/fan", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "../frontend/fan-view"), html=True), name="fan")
app.mount("/volunteer", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "../frontend/volunteer"), html=True), name="volunteer")


@app.get("/", response_class=HTMLResponse)
def get_landing():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>StadiumPulse Portal</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-void: #0A0A0B;
      --surface: #16100F;
      --surface-raised: #211614;
      --border: rgba(255, 255, 255, 0.08);
      --border-subtle: rgba(255, 255, 255, 0.04);
      --ink: #F2E9E4;
      --ink-muted: #8A7A75;
      
      --maroon-primary: #7A1F2B;
      --maroon-glow: rgba(122, 31, 43, 0.15);
      --pulse-normal: #4A7856;
      
      --font-header: 'Space Grotesk', system-ui, sans-serif;
      --font-body: 'Inter', system-ui, sans-serif;
    }
    
    body {
      background-color: var(--bg-void);
      color: var(--ink);
      font-family: var(--font-body);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
      padding: 2rem 1.5rem;
      box-sizing: border-box;
    }
    
    .container {
      background-color: var(--surface);
      border: 1px solid var(--border);
      border-top: 4px solid var(--maroon-primary);
      border-radius: 12px;
      padding: 3rem 2.5rem;
      max-width: 680px;
      width: 100%;
      text-align: center;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
      position: relative;
    }

    /* Signature Accent Glow */
    .container::after {
      content: '';
      position: absolute;
      top: -4px;
      left: 10%;
      right: 10%;
      height: 4px;
      background: var(--maroon-primary);
      filter: blur(8px);
      opacity: 0.6;
    }
    
    h1 {
      font-family: var(--font-header);
      font-size: 2.5rem;
      font-weight: 700;
      margin: 0 0 0.5rem 0;
      letter-spacing: -0.03em;
      color: var(--ink);
    }
    
    .positioning-copy {
      color: var(--ink-muted);
      font-size: 1rem;
      max-width: 480px;
      margin: 0 auto 2.5rem;
      line-height: 1.5;
    }
    
    .portal-grid {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 1.25rem;
    }

    @media (max-width: 768px) {
      .portal-grid {
        grid-template-columns: 1fr;
      }
    }

    
    .portal-card {
      background-color: var(--surface-raised);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1.5rem;
      display: flex;
      flex-direction: column;
      text-align: left;
      transition: all 0.22s ease-in-out;
      text-decoration: none;
      color: inherit;
    }
    
    .portal-card:hover {
      border-color: var(--maroon-primary);
      box-shadow: 0 0 15px var(--maroon-glow);
      transform: translateY(-2px);
    }

    .portal-card:focus-visible {
      outline: 2px solid var(--pulse-normal);
      outline-offset: 2px;
    }
    
    .card-title {
      font-family: var(--font-header);
      font-size: 1.2rem;
      font-weight: 700;
      margin: 0 0 0.5rem 0;
      color: var(--ink);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .card-title::after {
      content: '→';
      font-weight: 500;
      opacity: 0.5;
      transition: transform 0.2s;
    }

    .portal-card:hover .card-title::after {
      transform: translateX(3px);
      opacity: 0.9;
      color: var(--maroon-primary);
    }
    
    .card-desc {
      font-size: 0.82rem;
      color: var(--ink-muted);
      line-height: 1.45;
      margin: 0;
    }
    
    .card-badge {
      display: inline-block;
      font-size: 0.65rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--ink-muted);
      margin-bottom: 0.75rem;
      opacity: 0.7;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>StadiumPulse</h1>
    <p class="positioning-copy">Real-time crowd flow forecasting, multi-lingual AI-assisted safety routing (supporting 10 languages), localized eco-transit guidance, and volunteer incident triage for MetLife Stadium — FIFA World Cup 2026 Final, July 19.</p>
    
    <nav class="portal-grid" aria-label="Portal access">
      <a href="/admin" class="portal-card" aria-label="Access Ops Center Dashboard">
        <span class="card-badge">CONTROL ROOM ONLY</span>
        <h2 class="card-title">Ops Center</h2>
        <p class="card-desc">High-density visual monitor wall showing real-time zone congestion, predictive flow analytics, and GenAI brief alerts.</p>
      </a>
      
      <a href="/fan" class="portal-card" aria-label="Access Fan Companion Mobile View">
        <span class="card-badge">SPECTATOR CHANNEL</span>
        <h2 class="card-title">Fan Companion</h2>
        <p class="card-desc">Personalized multilingual companion view providing step-free routing nudges, optimized egress pathways, and live directions.</p>
      </a>

      <a href="/volunteer" class="portal-card" aria-label="Access Volunteer Incident Triage Portal">
        <span class="card-badge">FIELD VOLUNTEERS</span>
        <h2 class="card-title">Volunteer Portal</h2>
        <p class="card-desc">Submit raw free-text incident reports from the field for automated classification, tagging, and control-room dispatch.</p>
      </a>
    </nav>
  </div>
</body>
</html>"""



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
    Advances the simulation by one tick and returns the current ZoneState for
    every predefined zone.  Repeated polls show genuine progression over time.
    """
    SIMULATION.tick()
    return SIMULATION.get_current_zone_states()


@app.get("/api/briefs", response_model=List[Dict[str, Any]])
def get_briefs():
    """
    For every zone with status 'watch' or 'critical', calls generate_brief
    and returns the resulting ControlRoomBrief list, most urgent first.

    Does NOT call tick() — reflects the same moment as the last /api/zones
    call so the dashboard shows coherent data.

    Returns an empty list if all zones are currently in normal status.
    """
    states = SIMULATION.get_current_zone_states()
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

    Does NOT call tick() — reflects the same moment as the last /api/zones
    call so the nudge is consistent with the dashboard state.

    Query params:
      fan_id         (str)  – identifier for the fan
      language       (str)  – ISO 639-1 code, e.g. 'en', 'es', 'fr'
      mobility_needs (bool) – true = step-free route required
    """
    states = SIMULATION.get_current_zone_states()
    target_zone = _most_urgent_zone(states)

    fan_profile = {
        "fan_id": fan_id,
        "language": language,
        "mobility_needs": mobility_needs,
    }

    nudge = generate_nudge(target_zone, fan_profile)
    return nudge


# ── Volunteer Triage In-Memory Store ─────────────────────────────────────────
# Bounded to last 20 reports, thread-safe access isn't strictly requested but
# we use a simple lock to keep it robust and prevent race conditions.
VOLUNTEER_REPORTS: List[Dict[str, Any]] = []
reports_lock = threading.Lock()


class ReportRequest(BaseModel):
    # Reject empty raw_text (min_length=1) and cap raw_text length (max_length=1000) for security.
    raw_text: str = Field(..., min_length=1, max_length=1000, description="Raw volunteer message text.")

@app.post("/api/report", response_model=Dict[str, Any])
def post_report(payload: ReportRequest):
    """
    Submits a raw volunteer incident report, runs classify_report to triage it via
    Gemini, and appends it to the in-memory store (bounded to last 20 reports).
    """
    text = payload.raw_text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="raw_text cannot be empty or whitespace only")

    known_zones = [z["zone_id"] for z in ZONE_DEFS]
    report = classify_report(text, known_zones)

    with reports_lock:
        VOLUNTEER_REPORTS.insert(0, report)
        if len(VOLUNTEER_REPORTS) > 20:
            del VOLUNTEER_REPORTS[20:]

    return report

@app.get("/api/reports", response_model=List[Dict[str, Any]])
def get_reports():
    """Returns the current list of volunteer reports, most recent first."""
    with reports_lock:
        return list(VOLUNTEER_REPORTS)

