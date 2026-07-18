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
pip install fastapi uvicorn python-dotenv google-generativeai
```

> These are the only runtime dependencies. `fastapi` and `uvicorn` drive the server;
> `python-dotenv` loads the API key; `google-generativeai` is the Gemini SDK.

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
account, and click **Create API key**. The free tier is sufficient for hackathon demos.

> ⚠️ Never commit the `.env` file. It is already listed in `.gitignore`.

---

## 4. Run the backend server

```bash
# From the repo root
uvicorn backend.server:app --reload --port 8080
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8080 (Press CTRL+C to quit)
```

The API is now live. You can verify each endpoint:

```bash
curl http://localhost:8080/api/zones
curl http://localhost:8080/api/briefs
curl "http://localhost:8080/api/nudge?fan_id=fan_demo&language=en&mobility_needs=false"
```

---

## 5. Open the frontend pages

Open the two HTML files directly in a browser (no build step needed):

**Control Room Dashboard:**
```
frontend/dashboard/index.html
```

**Fan Companion View:**
```
frontend/fan-view/index.html
```

> Both pages automatically call `http://localhost:8080` if the server is running.
> If the server is **not** running, both pages fall back gracefully to built-in mock
> data — the UI never breaks.

---

## 6. Run the test suite

```bash
# From the repo root
python -m unittest discover -s tests -v
```

Expected: **44 tests, OK** (tests are fully mocked — no API key needed).

---

## Demo scenario cheat-sheet

| Endpoint | What to show |
|----------|-------------|
| `/api/zones` | 4 zone cards: East (normal), North (watch/critical), South (critical), West (normal) |
| `/api/briefs` | Gemini-generated briefs for all watch/critical zones, most urgent first |
| `/api/nudge?language=es&mobility_needs=true` | Spanish nudge, step-free route |
| `/api/nudge?language=fr&mobility_needs=false` | French nudge, most urgent zone |

Fan Companion "Next Scenario" button cycles through: EN normal → ES watch + mobility → FR critical.
