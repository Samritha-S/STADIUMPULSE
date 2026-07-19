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
  <title>StadiumPulse — Enter Portal</title>
  <meta name="description" content="StadiumPulse crowd-safety intelligence for FIFA World Cup 2026. Enter your name and role to access your portal.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-void: #0A0A0B;
      --surface: #16100F;
      --surface-raised: #211614;
      --border: rgba(255,255,255,0.08);
      --ink: #F2E9E4;
      --ink-muted: #8A7A75;
      --maroon-primary: #7A1F2B;
      --maroon-glow: rgba(122,31,43,0.18);
      --pulse-normal: #4A7856;
      --font-header: "Space Grotesk", system-ui, sans-serif;
      --font-body: "Inter", system-ui, sans-serif;
    }
    *, *::before, *::after { box-sizing: border-box; }
    body {
      background: var(--bg-void);
      color: var(--ink);
      font-family: var(--font-body);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem 1.25rem;
      margin: 0;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-top: 4px solid var(--maroon-primary);
      border-radius: 14px;
      padding: 2.75rem 2.25rem;
      width: 100%;
      max-width: 440px;
      box-shadow: 0 24px 48px rgba(0,0,0,0.65);
      position: relative;
    }
    .card::after {
      content: "";
      position: absolute;
      top: -4px; left: 12%; right: 12%; height: 4px;
      background: var(--maroon-primary);
      filter: blur(10px);
      opacity: 0.55;
    }
    .brand {
      font-family: var(--font-header);
      font-size: 2.25rem;
      font-weight: 700;
      letter-spacing: -0.03em;
      margin: 0 0 0.375rem;
      text-align: center;
    }
    .tagline {
      font-size: 0.82rem;
      color: var(--ink-muted);
      text-align: center;
      line-height: 1.5;
      margin: 0 0 2rem;
    }
    .form { display: flex; flex-direction: column; gap: 1.1rem; }
    .group { display: flex; flex-direction: column; gap: 0.4rem; }
    label {
      font-size: 0.68rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--ink-muted);
    }
    input, select {
      background: var(--surface-raised);
      border: 1px solid var(--border);
      border-radius: 7px;
      color: var(--ink);
      font-family: var(--font-body);
      font-size: 0.92rem;
      padding: 0.72rem 0.9rem;
      outline: none;
      width: 100%;
      transition: border-color 0.18s, box-shadow 0.18s;
      appearance: none;
      -webkit-appearance: none;
    }
    select {
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%238A7A75' viewBox='0 0 16 16'%3E%3Cpath d='M7.247 11.14L2.451 5.658C1.885 5.013 2.345 4 3.204 4h9.592a1 1 0 0 1 .753 1.659l-4.796 5.48a1 1 0 0 1-1.506 0z'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 0.9rem center;
      padding-right: 2.25rem;
    }
    input:focus, select:focus {
      border-color: var(--maroon-primary);
      box-shadow: 0 0 0 3px var(--maroon-glow);
    }
    .submit {
      background: var(--maroon-primary);
      border: none;
      border-radius: 7px;
      color: var(--ink);
      font-family: var(--font-header);
      font-size: 1rem;
      font-weight: 600;
      padding: 0.85rem;
      margin-top: 0.5rem;
      cursor: pointer;
      width: 100%;
      transition: filter 0.18s, box-shadow 0.18s;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
    }
    .submit:hover { filter: brightness(1.18); box-shadow: 0 4px 16px rgba(122,31,43,0.4); }
    .submit:focus-visible { outline: 2px solid var(--pulse-normal); outline-offset: 3px; }
    .guest-note {
      margin-top: 1.5rem;
      font-size: 0.73rem;
      color: var(--ink-muted);
      text-align: center;
      line-height: 1.45;
    }
    .guest-note a { color: inherit; text-decoration: underline; opacity: 0.7; }
    .guest-note a:hover { opacity: 1; }
  </style>
</head>
<body>
  <div class="card" role="main">
    <h1 class="brand">StadiumPulse</h1>
    <p class="tagline">MetLife Stadium · FIFA World Cup 2026 Final · July 19<br>Enter your name and role to access your portal.</p>

    <form class="form" id="session-form" novalidate>
      <div class="group">
        <label for="sp-name">Your Name</label>
        <input type="text" id="sp-name" name="name" required
               placeholder="e.g. Alex Smith" autocomplete="name"
               aria-required="true">
      </div>

      <div class="group">
        <label for="sp-role">Operational Role</label>
        <select id="sp-role" name="role" required aria-required="true">
          <option value="fan">Fan — Companion View</option>
          <option value="ops">Ops Staff — Control Room</option>
          <option value="volunteer">Volunteer — Field Responder</option>
        </select>
      </div>

      <button type="submit" class="submit" id="enter-btn">
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" fill="none"
             viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.2" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M13 7l5 5-5 5M6 12h12"/>
        </svg>
        Enter Portal
      </button>
    </form>

    <p class="guest-note">
      Demo only — no backend authentication.<br>
      Direct portal links: <a href="/admin">/admin</a> · <a href="/fan">/fan</a> · <a href="/volunteer">/volunteer</a>
    </p>
  </div>

  <script>
    (function () {
      var form = document.getElementById("session-form");
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        var name = document.getElementById("sp-name").value.trim();
        var role = document.getElementById("sp-role").value;
        if (!name) {
          document.getElementById("sp-name").focus();
          return;
        }
        sessionStorage.setItem("stadiumpulse_name", name);
        sessionStorage.setItem("stadiumpulse_role", role);
        var dest = role === "ops" ? "/admin" : role === "volunteer" ? "/volunteer" : "/fan";
        window.location.href = dest;
      });
    })();
  </script>
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

