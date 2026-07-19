# StadiumPulse — Setup & Demo Guide

> Copy-paste every command block exactly as shown. All paths are relative to the repo root.

---

## 1. Prerequisites

| Tool | Minimum version | Install |
|------|----------------|---------|
| Python | 3.11+ | python.org |
| pip | bundled with Python | — |

---

## 2. Install dependencies

```bash
pip install -r requirements.txt
```

> Runtime dependencies: `fastapi`, `uvicorn`, `python-dotenv`, `google-generativeai`, `pydantic`.
> No database driver needed — SQLite is included in Python's standard library.

---

## 3. Set up environment variables

```bash
# From the repo root
cp .env.example .env
```

Open `.env` in any editor and replace the placeholder value:

```
GEMINI_API_KEY=your_real_key_here
```

**Where to get a Gemini API key:**
Go to [Google AI Studio](https://aistudio.google.com/app/apikey), sign in with your Google
account, and click **Create API key**. The free tier is sufficient for demo use.

> ⚠️ Never commit the `.env` file. It is already listed in `.gitignore`.

---

## 4. Run the backend server

```bash
# From the repo root
uvicorn backend.server:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Verify the endpoints are live:

```bash
curl http://localhost:8000/api/zones
curl http://localhost:8000/api/briefs
curl "http://localhost:8000/api/nudge?fan_id=fan_demo&language=en&mobility_needs=false"
curl http://localhost:8000/api/transit-alert
curl http://localhost:8000/api/reports
```

---

## 5. Visit the Web Portals

Open your browser and navigate to:

```
http://localhost:8000/
```

This is the **Portal Dispatch** entry screen. Enter your name and select a role to be routed to the correct portal:

| Role | Portal | URL |
|------|--------|-----|
| Fan | Fan Companion | `/fan` |
| Ops Staff | Ops Control Room | `/admin` |
| Report Desk | Incident Report Desk | `/report` |

All portals automatically detect the server at the same origin. If the server is not running, the dashboard and fan view display built-in mock data as fallback — no hard errors.

---

## 6. Run the test suite

```bash
# From the repo root — all 129 tests, fully mocked (no API key needed)
python -m pytest tests/ -v
```

Expected output:
```
======================== 129 passed in ~18 s =========================
```

To run a specific test file:
```bash
python -m pytest tests/test_api_endpoints.py -v   # API integration tests
python -m pytest tests/test_database.py -v        # SQLite persistence tests
python -m pytest tests/test_reasoning.py -v       # GenAI layer tests (mocked)
python -m pytest tests/test_simulation_state.py -v
python -m pytest tests/test_forecast.py -v
python -m pytest tests/test_report.py -v
```

---

## 7. Live Deployment

The application is fully deployed on Vercel:

> **https://stadiumpulse.vercel.app**

No setup is needed to view the deployed version. The Gemini API key is configured as a Vercel environment secret.

---

## 8. Demo scenario cheat-sheet

| What to show | How to trigger |
|-------------|---------------|
| Live zone escalation | Open `/admin` — watch the 300 Level Gate F and Gate H zones escalate to **CRITICAL** within ~30 seconds |
| Critical Alert Rail | The red strip at the top of the Ops Centre fills with critical-zone mini-cards automatically |
| GenAI Operational Brief | Scroll the right column — each critical/watch zone has a Gemini-generated brief with recommended action |
| Transit broadcast | Fill in the Transit & Sustainability Dispatch form → click **Publish Broadcast** |
| Fan multilingual nudge | Open `/fan` — click the language selector to switch between EN / ES / FR demo profiles |
| Accessibility settings | Open `/fan` → click the settings (⚙) icon → toggle High Contrast / Large Font / Reduce Motion |
| Volunteer report triage | Open `/report` → submit an incident message (in any language) → see the AI triage result |
| Offline resilience | Stop the server — both `/admin` and `/fan` continue showing mock data with no errors |
