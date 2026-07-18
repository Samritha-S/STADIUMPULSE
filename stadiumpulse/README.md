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

StadiumPulse is a proof-of-concept addressing these two gaps simultaneously — automating the situational brief for operators and generating personalised, multilingual route nudges for individual fans, both derived from the same underlying zone forecast.

---

## 2. Approach and Architecture

### Three-layer pipeline

```
Synthetic crowd data  →  Forecast layer  →  Reasoning layer  →  Two action surfaces
(data_generator.py)      (forecast_zone)    (Gemini 2.5 Flash)   (dashboard + fan view)
```

**Layer 1 — Forecast**

`generate_zone_scenario()` synthesises a per-minute crowd count time series for each zone, using either a steady "normal" curve or a sigmoid-style "spike" curve that simulates post-match or halftime egress. This synthetic data stands in for real turnstile, CCTV, or Wi-Fi probe sensor feeds that would exist in a deployed system.

`forecast_zone()` takes that time series and runs a **simple linear regression over the most recent five data points** to estimate the crowd count 15 and 30 minutes ahead. It then classifies the zone as `normal` (forecast below 70% capacity), `watch` (70–90%), or `critical` (above 90%). These thresholds and the forecast window are deliberate choices for hackathon clarity — not production-tuned constants.

**Layer 2 — Reasoning (the GenAI layer)**

For any zone in `watch` or `critical` status, the system calls two Gemini-powered functions:

- `generate_brief(zone_state)` → produces a `ControlRoomBrief` for operators: a plain-language situation summary, a severity classification (`low`/`medium`/`high`/`critical`), a concrete recommended action naming specific gates and routes, and the list of languages the PA announcement will need.
- `generate_nudge(zone_state, fan_profile)` → produces a `FanNudge`: a 1–2 sentence message in the fan's language, directing them toward a specific less-congested route, with step-free routing enforced when `mobility_needs` is true.

Both functions use Gemini's structured JSON output mode (`response_mime_type="application/json"` with a `response_schema`), so the model is constrained to produce schema-valid output at generation time rather than in free text.

**Why generative AI rather than rule-based logic?**

A rules engine could classify severity and pick a reroute zone from a lookup table — and we do exactly that in the Tier 3 fallback. But rules alone cannot:

1. **Generate natural-language situational summaries** that are readable and actionable for an operator who may be simultaneously monitoring a dozen zones. A rule can say "zone is at 87% capacity and trending up"; Gemini can say "North Concourse Gate 3 is at 72% capacity and rising. Forecast projects 640 in 15 min (80%) and 710 in 30 min (89%). Trend is approaching the critical threshold. Consider a soft PA announcement advising fans that ramp_north_1 and elevator_north offer shorter wait times."
2. **Write the same message in 10 different languages** with culturally fluent phrasing, not word-for-word machine translation. A fan nudge in Spanish should read as a Spanish speaker would phrase it, not as translated English.
3. **Adapt tone by severity and audience** with a single call. A `critical` brief and a `critical` nudge describe the same event but in entirely different registers — the brief is terse and directive, the nudge is reassuring and never uses words like "danger" or "evacuate". Encoding both tone profiles and their severity gradients in rules for every language pair is not tractable.

**Layer 3 — Action surfaces**

- `/frontend/dashboard/` — a control-room web view polling `/api/zones` and `/api/briefs`, showing live zone status cards and the brief feed with ARIA live regions so screen readers announce new briefs.
- `/frontend/fan-view/` — a phone-frame mockup showing the `FanNudge` for the most urgent zone, with scenario cycling to demo EN/ES/FR and normal/watch/critical urgency levels.

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
Browser / curl request
        │
        ▼
FastAPI server  (backend/server.py, port 8000)
        │
        ├─ GET /api/zones
        │       │
        │       └─ For each of 4 predefined zones:
        │               generate_zone_scenario()  →  30 minutes of per-minute counts
        │               forecast_zone()           →  15-min + 30-min extrapolation + status
        │               Returns: List[ZoneState]
        │
        ├─ GET /api/briefs
        │       │
        │       └─ Runs the same zone computation
        │          Filters to zones with status "watch" or "critical"
        │          For each: generate_brief(zone_state)  →  Gemini 2.5 Flash (JSON mode)
        │          Sorts: critical first, then watch, then by occupancy ratio
        │          Returns: List[ControlRoomBrief]
        │
        └─ GET /api/nudge?fan_id=&language=&mobility_needs=
                │
                └─ Runs the same zone computation
                   Selects the single most urgent zone (status priority + occupancy ratio)
                   generate_nudge(zone_state, fan_profile)  →  Gemini 2.5 Flash (JSON mode)
                   Returns: FanNudge
```

**`GET /api/zones`** — Returns a list of four `ZoneState` objects, one per predefined zone. Each contains: current crowd count, zone capacity, 15-minute and 30-minute forecasted counts, safety status (`normal`/`watch`/`critical`), connected gate IDs, and accessible route IDs. Crowd history is regenerated on each request, so counts evolve naturally during a live demo without stored state.

**`GET /api/briefs`** — Returns a list of `ControlRoomBrief` objects for all zones currently in `watch` or `critical` status. Each brief contains: zone ID, severity level, a plain-language summary, a recommended action, a suggested reroute zone, the languages needed for fan announcements, and a UTC timestamp. Empty list if all zones are in `normal` status.

**`GET /api/nudge`** — Accepts query parameters `fan_id` (string), `language` (ISO 639-1 code), and `mobility_needs` (boolean). Picks the single most urgent zone and returns one `FanNudge`: a 1–2 sentence message in the requested language, a specific suggested route, and whether accessible routing was applied.

Both frontends call these endpoints on load (and on manual refresh for the dashboard) and fall back silently to built-in mock data if the server is not running — the UI never hard-errors.

---

## 4. Assumptions and Honest Limitations

**Synthetic data in place of real sensors**  
`generate_zone_scenario()` uses mathematical curves plus random noise to simulate crowd counts. In a real deployment, this layer would be replaced by a feed from turnstile sensors, CCTV people-counting systems, or Wi-Fi probe analytics. The forecast logic in `forecast_zone()` is sensor-agnostic — it accepts any list of integer counts — so swapping in real data is a matter of replacing the data source, not the forecasting logic.

**Simple linear regression, not a production time-series model**  
The forecast uses linear regression over the most recent five data points to estimate the 15- and 30-minute trajectory. This is appropriate for a hackathon demo with clean synthetic inputs. Real crowd dynamics are non-linear (surge effects, entry-wave patterns, weather sensitivity) and would benefit from an ARIMA, LSTM, or venue-specific learned model. The regression approach was chosen deliberately for its simplicity, zero dependencies, and pure-Python implementation.

**Four zones, one venue**  
The demo hardcodes four zones in a single notional stadium. FIFA World Cup 2026 has 16 venues across three countries, each with dozens of zones and complex interconnection graphs. A production system would need a graph model of zone adjacency, dynamic routing across the full venue, and zone-level capacity data from each stadium's BIM model.

**10 supported languages, no human review of safety-critical translations**  
The supported language set (`en`, `es`, `fr`, `pt`, `de`, `ar`, `it`, `ja`, `ko`, `zh`) covers the major attending-nation languages for FIFA 2026 but not all of them. More critically, in a real crowd-safety context, AI-generated safety messages should be reviewed by native-speaker safety communication professionals before deployment — Gemini's phrasing is fluent but not certified. The tone rules (no alarming words, reassuring framing) are enforced in the system prompt but cannot be guaranteed by the model in all edge cases.

**API key via `.env` file**  
`GEMINI_API_KEY` is read from a `.env` file loaded at startup. This is appropriate for local development; a production deployment would use a secrets manager (Google Secret Manager, AWS Secrets Manager, or equivalent) and would not expose the key on the filesystem.

**No authentication on the API**  
All three endpoints are unauthenticated GET requests. For a hackathon demo this is fine; a production control-room system would require authentication and role-based access — particularly for the briefs feed, which contains operational security-sensitive zone status information.

**Crowd counts are not deduplicated or smoothed**  
The synthetic data already includes noise, and the linear regression operates on raw counts. Real sensor feeds have duplicate detections, dropout periods, and sensor failures that require smoothing, gap-filling, and outlier rejection before a count series is suitable for forecasting.

---

## 5. Setup

See **[SETUP.md](SETUP.md)** for copy-pasteable installation, environment variable configuration, server startup, and test run instructions.

Quick reference:

```bash
pip install fastapi uvicorn python-dotenv google-generativeai
cp stadiumpulse/.env.example stadiumpulse/.env   # then add GEMINI_API_KEY
cd stadiumpulse && uvicorn backend.server:app --reload --port 8000
python -m unittest discover -s stadiumpulse/tests -v   # 32 tests, all mocked
```

---

## Repository Layout

```
stadiumpulse/
├── backend/
│   ├── forecast/
│   │   ├── data_generator.py      # Synthetic crowd time-series generation
│   │   └── forecast_service.py    # Linear regression forecast + status classification
│   ├── reasoning/
│   │   ├── generate_brief.py      # Gemini → ControlRoomBrief (JSON mode)
│   │   ├── generate_nudge.py      # Gemini → FanNudge (JSON mode, multilingual)
│   │   └── PROMPT_SPEC.md         # System prompts, few-shot examples, edge case spec
│   ├── shared/
│   │   ├── ZoneState.json         # Shared data schema
│   │   ├── ControlRoomBrief.json  # Shared data schema
│   │   └── FanNudge.json          # Shared data schema
│   └── server.py                  # FastAPI server: /api/zones, /api/briefs, /api/nudge
├── frontend/
│   ├── dashboard/                 # Control-room web UI (HTML/CSS/JS)
│   └── fan-view/                  # Fan mobile mockup (HTML/CSS/JS)
├── tests/
│   └── test_reasoning.py          # 32 unit tests (fully mocked, no API key needed)
│   └── test_forecast.py
├── .env.example                   # Environment variable template
├── SETUP.md                       # Step-by-step setup guide
└── README.md                      # This file
```
