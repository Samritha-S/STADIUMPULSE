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
load_dotenv(dotenv_path=os.path.join(_here, "../stadiumpulse/.env"))
load_dotenv(dotenv_path=os.path.join(_here, "../.env"))
load_dotenv(dotenv_path=os.path.join(_here, "../../.env"))
load_dotenv(dotenv_path=os.path.join(_here, "stadiumpulse/.env"))

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from reasoning.generate_brief import generate_brief
from reasoning.generate_nudge import generate_nudge
from reasoning.generate_report import classify_report

# ── Stateful simulation — one shared instance for the lifetime of the process
from simulation_state import SIMULATION, ZONE_DEFS
from pydantic import BaseModel, Field

from database import db_init, db_save_report, db_get_reports

app = FastAPI(title="StadiumPulse API", version="0.1.0")

# ── Startup brief cache — populated by seed thread, consumed by /api/briefs ──
# Keyed by zone_id. On the first /api/briefs call the endpoint merges these
# cached briefs with any freshly-generated ones so the dashboard is never empty.
_startup_briefs: Dict[str, Any] = {}
_briefs_cache_lock = threading.Lock()

# Safe startup check for GEMINI_API_KEY presence, and pre-seed demo data
@app.on_event("startup")
def startup_event():
    import logging
    import threading
    
    # Initialize database
    try:
        db_init()
        print("[Database] Schema successfully initialized.", flush=True)
    except Exception as db_err:
        print(f"[Database] Error initializing schema: {db_err}", flush=True)

    srv_logger = logging.getLogger("stadiumpulse.server")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        msg = "WARNING: GEMINI_API_KEY not found in environment — reasoning layer will use fallback responses only"
        srv_logger.warning(msg)
        print(msg, flush=True)
        return  # Skip real seeding — tests import without a key
    else:
        srv_logger.info("GEMINI_API_KEY successfully found in environment.")
        print("GEMINI_API_KEY successfully found in environment.", flush=True)

    # ------------------------------------------------------------------
    # Pre-seed briefs: generate a ControlRoomBrief for any zone that is
    # already in watch or critical status at startup, so /api/briefs returns
    # real content on the very first load rather than an empty list.
    # Done in a background thread so server startup is not blocked.
    # ------------------------------------------------------------------
    def _seed_briefs():
        try:
            print("Seeding startup briefs for hot zones...", flush=True)
            initial_states = SIMULATION.get_current_zone_states()
            hot_zones = [z for z in initial_states if z.get("status") in ("watch", "critical")]
            for zone_state in hot_zones:
                brief = generate_brief(zone_state)
                with _briefs_cache_lock:
                    _startup_briefs[zone_state["zone_id"]] = brief
            print(f"Seeded {len(hot_zones)} startup brief(s).", flush=True)
        except Exception as exc:
            print(f"Brief seeding skipped: {exc}", flush=True)

    threading.Thread(target=_seed_briefs, daemon=True).start()

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
from fastapi.responses import HTMLResponse, FileResponse

# Mount the dashboard under /admin and fan-view under /fan
# We must use directory absolute paths or paths relative to root.
# Since the app runs from workspace root, 'frontend/dashboard' and 'frontend/fan-view' are correct.
app.mount("/admin", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "../frontend/dashboard"), html=True), name="admin")
app.mount("/fan", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "../frontend/fan-view"), html=True), name="fan")
app.mount("/report", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "../frontend/report"), html=True), name="report")

@app.get("/submission", response_class=HTMLResponse)
def get_submission():
    return FileResponse(os.path.join(os.path.dirname(__file__), "../submission.html"))


@app.get("/", response_class=HTMLResponse)
def get_landing():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>StadiumPulse — Enter Portal</title>
  <meta name="description" content="StadiumPulse crowd-safety intelligence for FIFA World Cup 2026. Live zone tracking and operational portal gate entry.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-void: #080808;
      --surface: #141010;
      --surface-raised: #1E1412;
      --border: rgba(255,255,255,0.07);
      --ink: #F0E8E3;
      --ink-muted: #7A6B66;
      --maroon: #8B2333;
      --maroon-glow: rgba(139,35,51,0.18);
      --green: #4A7856;
      --amber: #C08A2E;
      --red: #B8323F;
      --font-header: "Space Grotesk", system-ui, sans-serif;
      --font-body: "Inter", system-ui, sans-serif;
      --font-data: "JetBrains Mono", monospace;
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg-void);
      color: var(--ink);
      font-family: var(--font-body);
      min-height: 100vh;
      display: flex;
      flex-direction: row;
      overflow-x: hidden;
    }
    
    /* Split Layout */
    .hero-split {
      flex: 1.2;
      background: linear-gradient(135deg, #120B0A 0%, var(--bg-void) 100%);
      border-right: 1px solid var(--border);
      padding: 4rem 3rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      position: relative;
    }
    .form-split {
      flex: 0.8;
      padding: 4rem 3rem;
      display: flex;
      flex-direction: column;
      justify-content: center;
      background: var(--bg-void);
    }
    
    .brand-group {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      margin-bottom: 3rem;
    }
    .brand-dot {
      width: 10px; height: 10px;
      background: var(--maroon);
      border-radius: 50%;
      box-shadow: 0 0 10px var(--maroon);
      animation: pulse-dot 2s infinite ease-in-out;
    }
    @keyframes pulse-dot {
      0%, 100% { transform: scale(1); opacity: 1; }
      50% { transform: scale(1.2); opacity: 0.5; }
    }
    .brand-title {
      font-family: var(--font-header);
      font-size: 1.5rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }
    
    .hero-main h2 {
      font-family: var(--font-header);
      font-size: 3rem;
      font-weight: 700;
      line-height: 1.1;
      letter-spacing: -0.03em;
      margin-bottom: 1.5rem;
    }
    .hero-main p {
      font-size: 1.05rem;
      color: var(--ink-muted);
      max-width: 480px;
      line-height: 1.6;
      margin-bottom: 3rem;
    }
    
    /* Live Data Feed */
    .live-data-wrapper {
      background: rgba(20, 16, 16, 0.5);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.5rem;
      max-width: 500px;
    }
    .live-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1.25rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.75rem;
    }
    .live-indicator {
      font-family: var(--font-data);
      font-size: 0.68rem;
      font-weight: 700;
      color: var(--green);
      letter-spacing: 0.05em;
    }
    .live-title {
      font-family: var(--font-header);
      font-size: 0.85rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--ink-muted);
    }
    
    .live-zones-list {
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }
    .live-zone-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.85rem;
    }
    .live-zone-name {
      color: var(--ink-muted);
    }
    .live-zone-data {
      font-family: var(--font-data);
      font-weight: 500;
      color: var(--ink);
    }
    .live-zone-status {
      font-size: 0.65rem;
      font-weight: 700;
      text-transform: uppercase;
      padding: 0.15rem 0.4rem;
      border-radius: 3px;
      margin-left: 0.5rem;
      letter-spacing: 0.04em;
    }
    .status-normal { background: rgba(74, 120, 86, 0.12); color: var(--green); }
    .status-watch { background: rgba(192, 138, 46, 0.12); color: var(--amber); }
    .status-critical { background: rgba(184, 50, 63, 0.12); color: var(--red); }
    
    .hero-footer {
      font-size: 0.75rem;
      color: var(--ink-muted);
      margin-top: 3rem;
    }
    
    /* Login Form Styles */
    .login-container {
      max-width: 380px;
      margin: 0 auto;
      width: 100%;
    }
    .login-header h3 {
      font-family: var(--font-header);
      font-size: 2rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      margin-bottom: 0.5rem;
    }
    .login-header p {
      font-size: 0.88rem;
      color: var(--ink-muted);
      margin-bottom: 2.5rem;
      line-height: 1.5;
    }
    
    .form { display: flex; flex-direction: column; gap: 1.25rem; }
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
      border-radius: 6px;
      color: var(--ink);
      font-family: var(--font-body);
      font-size: 0.92rem;
      padding: 0.75rem 0.9rem;
      outline: none;
      width: 100%;
      transition: border-color 0.18s, box-shadow 0.18s;
      appearance: none;
      -webkit-appearance: none;
    }
    select {
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%237A6B66' viewBox='0 0 16 16'%3E%3Cpath d='M7.247 11.14L2.451 5.658C1.885 5.013 2.345 4 3.204 4h9.592a1 1 0 0 1 .753 1.659l-4.796 5.48a1 1 0 0 1-1.506 0z'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 0.9rem center;
      padding-right: 2.25rem;
    }
    input:focus, select:focus {
      border-color: var(--maroon);
      box-shadow: 0 0 0 3px var(--maroon-glow);
    }
    .submit {
      background: var(--maroon);
      border: none;
      border-radius: 6px;
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
    .submit:hover { filter: brightness(1.18); box-shadow: 0 4px 16px rgba(139,35,51,0.3); }
    .submit:focus-visible { outline: 2px solid var(--green); outline-offset: 3px; }
    
    .direct-links-footer {
      margin-top: 2rem;
      font-size: 0.73rem;
      color: var(--ink-muted);
      text-align: center;
      line-height: 1.5;
    }
    .direct-links-footer a { color: inherit; text-decoration: underline; opacity: 0.7; }
    .direct-links-footer a:hover { opacity: 1; }
    
    /* Responsive Split */
    @media (max-width: 868px) {
      body { flex-direction: column; }
      .hero-split { padding: 3rem 1.5rem 1.5rem; border-right: none; border-bottom: 1px solid var(--border); }
      .form-split { padding: 2.5rem 1.5rem 3rem; }
      .hero-main h2 { font-size: 2.25rem; }
      .live-data-wrapper { max-width: 100%; }
    }
  </style>
</head>
<body>

  <!-- Hero / Dashboard Preview Section -->
  <section class="hero-split" aria-label="StadiumPulse Platform Overview">
    <div class="brand-group">
      <span class="brand-dot" aria-hidden="true"></span>
      <span class="brand-title">StadiumPulse</span>
    </div>
    
    <div class="hero-main">
      <h2>Crowd safety intelligence for the World Cup Final</h2>
      <p>Stateful forecasting and GenAI decision support at MetLife Stadium. Seamlessly coordinate control rooms, field volunteers, and fans — with built-in eco-routing that steers 78,000 attendees toward zero-emission transit.</p>
      
      <!-- Live mini-feed of zone status to immediately showcase real data -->
      <div class="live-data-wrapper">
        <div class="live-header">
          <span class="live-title">METLIFE SYSTEM STATUS</span>
          <span class="live-indicator" aria-live="polite" id="data-status-label">● POLLING SYSTEM</span>
        </div>
        <div class="live-zones-list" id="mini-zones-list" aria-live="polite">
          <div style="color: var(--ink-muted); font-size: 0.8rem;">Connecting to simulation state...</div>
        </div>
        <div style="margin-top:1rem; padding-top:0.75rem; border-top:1px solid rgba(255,255,255,0.04); display:flex; align-items:center; gap:0.5rem; font-size:0.72rem; color:#2E7D52; font-weight:600;">
          <span>🌿</span>
          <span>Eco routing active — NJ Transit rail &amp; electric shuttles prioritised across all fan nudges</span>
        </div>
      </div>
    </div>
    
    <div class="hero-footer">
      <span>MetLife Stadium · 78,576 capacity · FIFA World Cup 2026 Final</span>
      <span style="margin-left:1rem; color:#2E7D52; font-weight:600;">🌿 Zero-emission transit routes active</span>
    </div>
  </section>

  <!-- Form Sign-In Section -->
  <main class="form-split" role="main">
    <div class="login-container">
      <div class="login-header">
        <h3>Portal Dispatch</h3>
        <p>Access your designated view. Your session information will be maintained browser-locally to route companion data feeds.</p>
      </div>

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
            <option value="report">Report Desk — Dispatch</option>
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

      <p class="direct-links-footer">
        Direct portal entry:<br>
        <a href="/admin">Control Room</a> · <a href="/fan">Fan View</a> · <a href="/report">Report Desk</a>
      </p>
    </div>
  </main>

  <script>
    (function () {
      // Form redirect logic
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
        var dest = role === "ops" ? "/admin" : role === "report" ? "/report" : "/fan";
        window.location.href = dest;
      });

      // Live status mini-panel update logic
      function updateMiniDashboard() {
        fetch("/api/zones")
          .then(function(res) { return res.json(); })
          .then(function(data) {
            var listEl = document.getElementById("mini-zones-list");
            var statusEl = document.getElementById("data-status-label");
            if (!listEl) return;
            
            statusEl.textContent = "● ACTIVE METRICS";
            statusEl.style.color = "var(--green)";
            
            // Map statuses to CSS classes
            var statusClasses = {
              normal: "status-normal",
              watch: "status-watch",
              critical: "status-critical"
            };

            listEl.innerHTML = data.map(function(z) {
              var pct = Math.round(100 * z.current_count / z.capacity);
              var statusClass = statusClasses[z.status] || "status-normal";
              return '<div class="live-zone-row">' +
                '<span class="live-zone-name">' + z.zone_name.replace('Concourse', '').trim() + '</span>' +
                '<span>' +
                  '<span class="live-zone-data">' + z.current_count.toLocaleString() + ' / ' + z.capacity.toLocaleString() + '</span>' +
                  '<span class="live-zone-status ' + statusClass + '">' + z.status + '</span>' +
                '</span>' +
              '</div>';
            }).join('');
          })
          .catch(function(err) {
            console.error("Mini-dashboard updates failed:", err);
            var statusEl = document.getElementById("data-status-label");
            if (statusEl) {
              statusEl.textContent = "● STATE SUSPENDED (OFFLINE)";
              statusEl.style.color = "var(--red)";
            }
          });
      }

      // Run immediately and poll every 3s
      updateMiniDashboard();
      setInterval(updateMiniDashboard, 3000);
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
        zid = zone["zone_id"]
        # Check if a pre-seeded brief exists for this zone (populated at startup).
        # After the first tick cycle this path is rarely hit; the live-generated
        # brief replaces the cached one. But on the very first load it ensures
        # the dashboard is never empty.
        with _briefs_cache_lock:
            cached = _startup_briefs.pop(zid, None)
        brief = cached if cached is not None else generate_brief(zone)
        briefs.append(brief)
    return briefs


# ── Transit Alert In-Memory Store ───────────────────────────────────────────
ACTIVE_TRANSIT_ALERT = {
    "transit_status": "normal",
    "custom_tip": ""
}
transit_alert_lock = threading.Lock()

class TransitAlertRequest(BaseModel):
    transit_status: str = Field(..., description="Status category, e.g. normal, watch, critical")
    custom_tip: str = Field(..., description="Custom message text to broadcast to fans")

@app.post("/api/transit-alert")
def post_transit_alert(payload: TransitAlertRequest):
    with transit_alert_lock:
        ACTIVE_TRANSIT_ALERT["transit_status"] = payload.transit_status.strip()
        ACTIVE_TRANSIT_ALERT["custom_tip"] = payload.custom_tip.strip()
    return ACTIVE_TRANSIT_ALERT

@app.get("/api/transit-alert")
def get_transit_alert():
    with transit_alert_lock:
        return dict(ACTIVE_TRANSIT_ALERT)


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
    with transit_alert_lock:
        if ACTIVE_TRANSIT_ALERT["custom_tip"]:
            nudge["transit_tip"] = ACTIVE_TRANSIT_ALERT["custom_tip"]
        nudge["transit_status"] = ACTIVE_TRANSIT_ALERT["transit_status"]
    return nudge



# ── Report Triage SQL Persistence ─────────────────────────────────────────

class ReportRequest(BaseModel):
    # Reject empty raw_text (min_length=1) and cap raw_text length (max_length=1000) for security.
    raw_text: str = Field(..., min_length=1, max_length=1000, description="Raw volunteer message text.")

@app.post("/api/report", response_model=Dict[str, Any])
def post_report(payload: ReportRequest):
    """
    Submits a raw volunteer incident report, runs classify_report to triage it via
    Gemini, and appends it to the SQLite database.
    """
    text = payload.raw_text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="raw_text cannot be empty or whitespace only")

    known_zones = [z["zone_id"] for z in ZONE_DEFS]
    report = classify_report(text, known_zones)

    db_save_report(report)

    return report

@app.get("/api/reports", response_model=List[Dict[str, Any]])
def get_reports():
    """Returns the current list of volunteer reports, most recent first."""
    return db_get_reports()

