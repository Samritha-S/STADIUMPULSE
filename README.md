# StadiumPulse

**AI-assisted crowd safety intelligence for FIFA World Cup 2026 stadium operations**

---

## 1. The Problem

FIFA World Cup 2026 is the largest World Cup in history — 48 teams, 104 matches, 16 host stadiums across the United States, Canada, and Mexico. Each match-day can bring 60,000–80,000 fans through a single venue, speaking dozens of languages, dispersed across concourses, gates, and access routes that have different safe capacities.

Crowd crush events — like Hillsborough (1989), Ellis Park (2001), or the Astroworld crush (2021) — share a common failure mode: the time between a zone becoming dangerous and staff taking effective action is too long, and the information that reaches individual fans is too generic or too slow to change behaviour before a crush develops.

The operational gap is specific:

- **Control-room staff** receive raw sensor data or radio calls, then must manually interpret the situation, decide on an action, and write or approve announcements — all under time pressure.
- **Fans** receive only static signage or PA announcements in one or two languages that may not be theirs, with no route-specific guidance personalised to their position or accessibility needs.
- **Communication delay** compounds the problem: by the time a brief is written and approved and a PA announcement broadcast, the zone state may have already changed.

StadiumPulse is a real-time crowd management solution that integrates four core features into a unified pipeline:
1. **Automated situational briefs** to support stadium operators in the control room.
2. **Personalized, multilingual fan nudges** that translate route guidance dynamically into 10 languages (EN, ES, FR, PT, DE, AR, IT, JA, KO, ZH).
3. **Transportation & sustainability guidance** via the `transit_tip` framework, providing eco-nudge sustainability messaging during normal states and time-saving route recommendations to bypass congestion during surges.
4. **Volunteer incident triage** allowing volunteers to submit raw field updates in any language, automatically classifying location, category, and severity for control-room mapping.

---

## 2. Approach and Architecture

### Three-layer pipeline

```
SimulationState (ticking)  →  Forecast layer  →  Reasoning layer  →  Two action surfaces
(simulation_state.py)         (forecast_zone)    (Gemini 1.5 Flash)   (dashboard + fan view)
```

**Layer 1 — Stateful Simulation**

`SimulationState` (`backend/simulation_state.py`) is a module-level singleton that holds a rolling per-minute crowd count history for each of the four predefined zones. Each call to its `tick()` method appends one new synthetic data point per zone, advancing the simulation forward in time. Histories are bounded to the last 20 points to prevent memory growth over long demo sessions. A `threading.Lock` ensures tick writes and history reads are safe under concurrent FastAPI request handling.

Three zone curve types drive the simulation, reusing the same mathematical formulas as `data_generator.py`:

- **`normal`** — steady fluctuation around 35% of capacity ± noise (East Concourse, West Standing Area)
- **`spike`** — sigmoid-style surge toward 90–95% capacity over ~30 ticks (North Concourse Gate 3)
- **`escalating`** — fast linear ramp from 70% to 95% capacity over 10 ticks, scripted to reach `critical` status within 8–12 polls (South Main Concourse)

This is the key difference from a stateless model: rather than regenerating a fresh random scenario on every request, the server maintains a single shared history that progresses monotonically forward. Repeated polls show genuine crowd escalation rather than independent random draws.

`forecast_zone()` takes the current rolling history for a zone and runs a **simple linear regression over the most recent five data points** to estimate the crowd count 15 and 30 minutes ahead. It then classifies the zone as `normal` (forecast below 70% of capacity), `watch` (70–90%), or `critical` (above 90%). These thresholds and the forecast window are deliberate choices for hackathon clarity — not production-tuned constants.

**Layer 2 — Reasoning (the GenAI layer)**

For any zone in `watch` or `critical` status, the system calls two Gemini-powered functions:

- `generate_brief(zone_state)` → produces a `ControlRoomBrief` for operators: a plain-language situation summary, a severity classification (`low`/`medium`/`high`/`critical`), a concrete recommended action naming specific gates and routes, and the list of languages the PA announcement will need.
- `generate_nudge(zone_state, fan_profile)` → produces a `FanNudge`: a 1–2 sentence message in the fan's language, directing them toward a specific less-congested route, with step-free routing enforced when `mobility_needs` is true. Also includes a `transit_tip` field: a short (≤20 word) secondary suggestion covering transportation or sustainability — a light eco-transit nudge for normal-status zones, and a practical congestion-avoidance transit tip (framed in the fan's self-interest as being faster) for watch/critical zones.

Both functions use Gemini's structured JSON output mode (`response_mime_type="application/json"` with a `response_schema`), so the model is constrained to produce schema-valid output at generation time rather than in free text.

**Why generative AI rather than rule-based logic?**

A rules engine could classify severity and pick a reroute zone from a lookup table — and we do exactly that in the Tier 3 fallback. But rules alone cannot:

1. **Generate natural-language situational summaries** that are readable and actionable for an operator monitoring a dozen zones simultaneously. A rule can say "zone is at 87% capacity and trending up"; Gemini can say "North Concourse Gate 3 is at 72% capacity and rising. Forecast projects 640 in 15 min (80%) and 710 in 30 min (89%). Consider a soft PA announcement advising fans that ramp_north_1 and elevator_north offer shorter wait times."
2. **Write the same message in 10 different languages** with culturally fluent phrasing, not word-for-word machine translation.
3. **Adapt tone by severity and audience** with a single call. A `critical` brief and a `critical` nudge describe the same event in entirely different registers — the brief is terse and directive, the nudge is reassuring and never uses words like "danger" or "evacuate".

**Layer 3 — Action surfaces**

- `/frontend/dashboard/` — a control-room web view that polls `/api/zones` and `/api/briefs` every **3 seconds** via `setInterval`. Zone cards are updated in-place on each poll (no full DOM rebuild) to avoid flickering. New briefs that appear for the first time receive a `NEW` badge and a 2-second red flash animation so an operator notices escalation immediately. A `● LIVE` badge in the header confirms active polling; after 3 consecutive network failures it switches to `● PAUSED (OFFLINE)` and polling stops. Clicking **Refresh Data** resets the failure count and restores live polling. All brief updates are announced via an `aria-live="polite"` region for screen readers.
- `/frontend/fan-view/` — a phone-frame mockup that polls `/api/nudge` every **3 seconds**, passing the currently selected demo profile (language + mobility needs). When the returned nudge message or severity changes from the previous poll, the card briefly scales and glows to signal the update. A demo controller lets you switch between three fan profiles (EN/normal, ES+mobility/watch, FR/critical); changing profiles takes effect on the next poll. Both views fall back silently to built-in mock data if the server is unreachable — the UI never hard-errors.

### Three-tier fallback: a safety-critical design decision

In a crowd-safety context, a system that silently returns nothing when the LLM is unavailable is more dangerous than one that returns a degraded-but-correct response. StadiumPulse implements a deliberate three-tier fallback in both `generate_brief` and `generate_nudge`:

| Tier | Trigger | Response |
|------|---------|----------|
| **1** | Normal path — Gemini returns valid JSON | Use it directly |
| **2** | API call fails or returns unparseable output | Retry once with the same request |
| **3** | Both calls fail | Deterministic Python fallback: fill all fields from input data, log the failure, return a safe minimal response |

The Tier 3 fallback is not boilerplate error handling — it is a hard guarantee that operators always receive a brief and fans always receive a nudge, even if the Gemini API is unreachable, rate-limited, or returning garbage. The fallback messages are also localised: the nudge fallback ships hardcoded templates in all 10 supported languages so the output doesn't silently revert to English when the LLM goes down during a Spanish-language scenario.

---

## 3. How It Works (End-to-End Data Flow)

```
Both frontends poll every 3 s
        │
        ▼
FastAPI server  (backend/server.py, port 8088)
        │
        ├─ GET /api/zones          ← TICKS the simulation forward by one step
        │       │
        │       └─ SIMULATION.tick()
        │            └─ for each zone: append one new count via its curve (normal/spike/escalating)
        │               trim history to last 20 points
        │          SIMULATION.get_current_zone_states()
        │            └─ for each zone: forecast_zone(history[-20:], capacity)
        │                              → 15-min + 30-min linear extrapolation + status
        │          Returns: List[ZoneState]  (state has genuinely advanced this poll)
        │
        ├─ GET /api/briefs          ← reads current state WITHOUT ticking again
        │       │
        │       └─ SIMULATION.get_current_zone_states()  (same tick as /api/zones)
        │          filter: status in ("watch", "critical")
        │          for each: generate_brief(zone_state) → Gemini JSON mode / Tier 3 fallback
        │          sort: critical first, then watch, secondary by occupancy ratio
        │          Returns: List[ControlRoomBrief]
        │
        └─ GET /api/nudge?fan_id=&language=&mobility_needs=
                │
                └─ SIMULATION.get_current_zone_states()  (same tick as /api/zones)
                   pick most urgent zone (status priority, then occupancy ratio)
                   generate_nudge(zone_state, fan_profile) → Gemini JSON mode / Tier 3 fallback
                   Returns: FanNudge
```

**Tick contract:** Only `GET /api/zones` advances the simulation. `GET /api/briefs` and `GET /api/nudge` read the current state without advancing it further, so a dashboard that calls all three endpoints in one poll cycle sees perfectly coherent data — briefs and nudges always correspond to the same moment as the zone cards.

**`GET /api/zones`** — Calls `SIMULATION.tick()` once, then `SIMULATION.get_current_zone_states()`. Returns a list of four `ZoneState` objects. Each contains: current crowd count, zone capacity, 15-minute and 30-minute forecasted counts, safety status (`normal`/`watch`/`critical`), connected gate IDs, and accessible route IDs. Because state is persistent in memory, consecutive calls return genuinely progressive data — counts change each poll and zones escalate over time. South Main Concourse is scripted to reach `critical` within 8–12 polls from a cold start (~24–36 seconds of polling).

**`GET /api/briefs`** — Returns a list of `ControlRoomBrief` objects for all zones currently in `watch` or `critical` status, derived from the same tick's state (no extra tick). Each brief contains: zone ID, severity level, a plain-language summary, a recommended action, a suggested reroute zone, the languages needed for fan announcements, and a UTC timestamp. Returns an empty list if all zones are in `normal` status.

**`GET /api/nudge`** — Accepts query parameters `fan_id` (string), `language` (ISO 639-1 code), and `mobility_needs` (boolean). Reads the current tick's state, picks the single most urgent zone, and returns one `FanNudge`: a 1–2 sentence message in the requested language, a specific suggested route, and whether accessible routing was applied.

---

## 4. Assumptions and Honest Limitations

**Synthetic data in place of real sensors**
`SimulationState` generates crowd counts using mathematical curves (normal fluctuation, sigmoid spike, linear escalation) plus random noise. In a real deployment this layer would be replaced by a feed from turnstile sensors, CCTV people-counting systems, or Wi-Fi probe analytics. The forecast logic in `forecast_zone()` is sensor-agnostic — it accepts any list of integer counts — so swapping in real data is a matter of replacing the data source, not the forecasting logic.

**Simple linear regression, not a production time-series model**
The forecast uses linear regression over the most recent five data points to estimate the 15- and 30-minute trajectory. This is appropriate for a hackathon demo with clean synthetic inputs. Real crowd dynamics are non-linear (surge effects, entry-wave patterns, weather sensitivity) and would benefit from an ARIMA, LSTM, or venue-specific learned model.

**In-memory state only — no persistence across server restarts**
`SimulationState` lives entirely in process memory. Restarting the server resets the simulation to tick 0. For a hackathon demo this is fine; a production system would persist zone histories to a time-series database and resume from the last known state on restart.

**Four zones, one venue (MetLife Stadium)**
The simulation and data models are grounded in a real venue: **MetLife Stadium (East Rutherford, NJ)**, using its real tournament capacity configuration of **78,576** for the FIFA World Cup 2026 Final on July 19, 2026. The zone capacities (~18,000–20,000 each) and the naming conventions represent the stadium concourse levels (100, 200, 300, Field) and gate letters (A–G). While this provides highly realistic sizing for demo simulations, exact gate and concourse boundary assignments are a reasonable approximation for demo purposes and are not sourced from official FIFA or venue-owner documents.


**10 supported languages, no human review of safety-critical translations**
The supported language set (`en`, `es`, `fr`, `pt`, `de`, `ar`, `it`, `ja`, `ko`, `zh`) covers the major attending-nation languages for FIFA 2026 but not all of them. More critically, in a real crowd-safety context, AI-generated safety messages should be reviewed by native-speaker safety communication professionals before deployment — Gemini's phrasing is fluent but not certified. The tone rules (no alarming words, reassuring framing) are enforced in the system prompt but cannot be guaranteed by the model in all edge cases.

**API key via `.env` file**
`GEMINI_API_KEY` is read from a `.env` file loaded at startup. This is appropriate for local development; a production deployment would use a secrets manager (Google Secret Manager, AWS Secrets Manager, or equivalent) and would not expose the key on the filesystem.

**No authentication on the API**
All three endpoints are unauthenticated GET requests. For a hackathon demo this is fine; a production control-room system would require authentication and role-based access — particularly for the briefs feed, which contains operational security-sensitive zone status information.

**Session identity is client-side only (deliberate scope decision)**
The `/` entry screen collects a name and role and stores them in `sessionStorage` to provide a "signed-in" experience across portals (name + role badge, log-out action, portal switching nav). This is a demo identity layer, not real authentication — `sessionStorage` is browser-local, never sent to the server, and is cleared on tab close. A production deployment would require real server-side authentication: OAuth 2.0, session tokens with CSRF protection, or an identity platform (Google Identity, Auth0, etc.). This scope boundary is intentional for a hackathon build and is not a gap.

**Crowd counts are not deduplicated or smoothed**
The synthetic data already includes noise, and the linear regression operates on raw counts. Real sensor feeds have duplicate detections, dropout periods, and sensor failures that require smoothing, gap-filling, and outlier rejection before a count series is suitable for forecasting.

---

## 5. Setup

See **[SETUP.md](SETUP.md)** for copy-pasteable installation, environment variable configuration, server startup, and test run instructions.

Quick reference:

```bash
pip install fastapi uvicorn python-dotenv google-generativeai
cp .env.example .env   # then add GEMINI_API_KEY
uvicorn backend.server:app --reload --port 8088
python -m unittest discover -s tests -v   # 59 tests, all mocked
```

Once running, navigate to `http://localhost:8088/` to reach the **entry screen** — enter your name and select a role (Fan / Ops Staff / Volunteer) to be routed to the matching portal. Each portal shows a persistent top nav bar with your session identity, links to switch between portals, and a log-out action. Navigating directly to `/admin`, `/fan`, or `/volunteer` without going through the entry screen works fine — the nav bar shows a "Guest" state and prompts you to enter details.

---

## Repository Layout

```
STADIUMPULSE/
├── backend/
│   ├── forecast/
│   │   ├── data_generator.py      # Synthetic crowd time-series generation (used by tests)
│   │   └── forecast_service.py    # Linear regression forecast + status classification
│   ├── reasoning/
│   │   ├── generate_brief.py      # Gemini → ControlRoomBrief (JSON mode, 3-tier fallback)
│   │   ├── generate_nudge.py      # Gemini → FanNudge (JSON mode, multilingual fallback)
│   │   ├── generate_report.py     # Gemini → VolunteerReport (JSON mode, 3-tier fallback)
│   │   └── PROMPT_SPEC.md         # System prompts, few-shot examples, edge case spec
│   ├── shared/
│   │   ├── ZoneState.json         # Shared data schema
│   │   ├── ControlRoomBrief.json  # Shared data schema
│   │   ├── FanNudge.json          # Shared data schema
│   │   └── VolunteerReport.json   # Shared data schema
│   ├── server.py                  # FastAPI server: /api/zones, /api/briefs, /api/nudge, /api/report
│   └── simulation_state.py        # Stateful ticking simulation engine (singleton)
├── frontend/
│   ├── dashboard/                 # Control-room web UI — live polling, NEW badges, offline detection
│   ├── fan-view/                  # Fan mobile mockup — live polling, nudge highlight animation
│   └── volunteer/                 # Volunteer incident triage portal — form submit, real-time feedback
├── tests/
│   ├── test_reasoning.py          # Unit tests for generate_brief / generate_nudge (mocked)
│   ├── test_report.py             # Unit tests for classify_report (mocked)
│   ├── test_forecast.py           # Unit tests for forecast_zone and data_generator
│   └── test_simulation_state.py   # Unit tests for state ticking and forecasts
├── .env.example                   # Environment variable template
├── SETUP.md                       # Step-by-step setup guide
└── README.md                      # This file
```
