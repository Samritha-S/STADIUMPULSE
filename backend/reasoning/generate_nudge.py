"""
generate_nudge — Fan Nudge generation via Google Gemini LLM.

Takes a ZoneState dict and a fan profile dict and produces a FanNudge dict
matching the schema at /backend/shared/FanNudge.json.

Example Input:
    zone_state = {
        "zone_id": "zone_north_gate3",
        "zone_name": "North Concourse Gate 3",
        "current_count": 580,
        "capacity": 800,
        "forecast_count_15min": 640,
        "forecast_count_30min": 710,
        "status": "watch",
        "connected_gates": ["gate_3", "gate_4"],
        "accessible_routes": ["ramp_north_1", "elevator_north"]
    }
    fan_profile = {
        "fan_id": "fan_1137",
        "language": "es",
        "mobility_needs": True
    }

Example Output:
    {
        "fan_id": "fan_1137",
        "language": "es",
        "mobility_needs": true,
        "message_text": "Te recomendamos dirigirte a la rampa norte 1 ...",
        "suggested_route": "ramp_north_1",
        "transit_tip": "El metro l\u00ednea 2 evita los atascos de tr\u00e1fico.",
        "generated_at": "2026-07-09T14:30:00Z"
    }
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stadiumpulse.reasoning")

# ---------------------------------------------------------------------------
# Model configuration
# NOTE: Verify model name and pricing at https://ai.google.dev/pricing before
# any post-hackathon production deployment — Gemini model names evolve quickly.
# ---------------------------------------------------------------------------
GEMINI_MODEL = "gemini-2.5-flash"

# Supported languages for LLM generation. If the requested language is not
# in this list the calling code pre-emptively falls back to English before
# hitting the LLM, and logs a warning per PROMPT_SPEC.md §3.1.
# Chosen based on FIFA World Cup 2026 host countries (US, Mexico, Canada)
# and major attending-nation languages.
SUPPORTED_LANGUAGES = {"en", "es", "fr", "pt", "de", "ar", "it", "ja", "ko", "zh"}

# Required keys per FanNudge schema
NUDGE_REQUIRED_KEYS = {
    "fan_id", "language", "mobility_needs", "message_text",
    "suggested_route", "generated_at",
}

# ---------------------------------------------------------------------------
# Response schema for Gemini JSON mode
# Mirrors FanNudge.json exactly so Gemini enforces the shape at generation time.
# transit_tip is included in properties but NOT in required[] — the model may
# omit it and the caller will fall back to the hardcoded FALLBACK_TRANSIT_TIPS.
# ---------------------------------------------------------------------------
NUDGE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "fan_id":         {"type": "string"},
        "language":       {"type": "string"},
        "mobility_needs": {"type": "boolean"},
        "message_text":   {"type": "string"},
        "suggested_route":{"type": "string"},
        "transit_tip":    {"type": "string"},
        "generated_at":   {"type": "string"},
    },
    "required": [
        "fan_id", "language", "mobility_needs", "message_text",
        "suggested_route", "generated_at",
    ],
}

# ---------------------------------------------------------------------------
# System prompt — reproduced verbatim from PROMPT_SPEC.md §2
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a fan-facing notification system for FIFA World Cup 2026 stadiums.

Your job is to read a zone's current crowd state and a fan's profile, and produce a \
single FanNudge JSON object — a short, personalised message guiding the fan toward a \
less congested route.

OUTPUT RULES — you MUST follow all of these:
1. Respond with ONLY a single valid JSON object. No markdown fences, no prose, no \
explanation before or after the JSON.
2. The JSON must contain exactly these keys:
   "fan_id", "language", "mobility_needs", "message_text", "suggested_route", \
"transit_tip", "generated_at"
3. "language" must echo the fan_profile's language code exactly.
4. "mobility_needs" must echo the fan_profile's mobility_needs boolean exactly.
5. "generated_at" must be an ISO 8601 UTC timestamp string.

LANGUAGE:
- Write "message_text" and "transit_tip" entirely in the language specified by fan_profile.language.
- Use natural, culturally fluent phrasing — do NOT produce a word-for-word literal \
translation from English. Write as a native speaker of that language would.
- If the language code is not one you can write fluently, fall back to English and \
set "language" to "en". (The caller will detect the mismatch and handle it.)

TONE:
- Reassuring, friendly, and helpful — even when status is "critical".
- Never use alarming words like "danger", "emergency", "evacuate", or "overcrowded".
- Frame the message as a helpful suggestion ("you might enjoy a quicker route") \
rather than an order.
- Keep the message short: 1-2 sentences maximum.

MOBILITY-AWARE ROUTING:
- If mobility_needs is true, suggested_route MUST be chosen from the zone's \
accessible_routes list. These routes are step-free (elevators, ramps). Never \
suggest a route that is not in accessible_routes when mobility_needs is true.
- If mobility_needs is false, suggested_route may be any route from \
connected_gates or accessible_routes, whichever is less congested.
- If mobility_needs is true AND accessible_routes is empty, set suggested_route \
to "ask_staff" and include a note in message_text asking the fan to speak to \
the nearest staff member for assistance.

STATUS-BASED MESSAGE INTENSITY:
- "normal": Very brief, low-key. A light suggestion, almost optional. Example \
framing: "Just a heads-up, [route] has shorter lines right now."
- "watch": A clear but calm recommendation. Example framing: "We recommend \
heading to [route] for a smoother experience."
- "critical": Urgent but NOT alarming. Example framing: "For the quickest exit, \
please head to [route] — it's the fastest way out right now.\"

TRANSIT TIP (transit_tip field):
- Always include a transit_tip. Keep it under ~20 words.
- Write transit_tip in the same language as message_text.
- For "normal" status: a light, optional sustainability nudge. Suggest public \
transit or eco-friendly framing — low urgency, positive tone.
  Example (en): "Taking the metro home? It's the greenest option tonight."
- For "watch" or "critical" status: a practical transportation suggestion that \
helps the fan avoid congestion and get home faster. Frame it as being faster \
for the fan (self-interest framing), not solely as a sustainability appeal.
  Example (en, watch): "Subway Line 3 from the south exit avoids the road delays entirely."
  Example (en, critical): "Bus 52 from Gate 2 is running now — beats the car park queues."""""

# ---------------------------------------------------------------------------
# Few-shot examples — reproduced verbatim from PROMPT_SPEC.md §2.1
# Formatted as Gemini content turns (role: user / model).
# All model turns now include transit_tip so the model learns to produce it.
# ---------------------------------------------------------------------------
FEW_SHOT_EXAMPLES: List[Dict[str, Any]] = [
    # Example A — normal, English, no mobility needs
    {
        "role": "user",
        "parts": [{"text": json.dumps({
            "zone_state": {
                "zone_id": "zone_100_gate_a",
                "zone_name": "100 Level – Gate A Concourse",
                "current_count": 4200,
                "capacity": 19500,
                "forecast_count_15min": 4500,
                "forecast_count_30min": 4900,
                "status": "normal",
                "connected_gates": ["gate_a", "gate_b"],
                "accessible_routes": ["ramp_100_east", "elevator_100_a"],
            },
            "fan_profile": {
                "fan_id": "fan_4821",
                "language": "en",
                "mobility_needs": False,
            },
        })}],
    },
    {
        "role": "model",
        "parts": [{"text": json.dumps({
            "fan_id": "fan_4821",
            "language": "en",
            "mobility_needs": False,
            "message_text": "Just a heads-up \u2014 gate a has shorter lines right now if you\u2019re heading out.",
            "suggested_route": "gate_a",
            "transit_tip": "Taking the metro tonight? It\u2019s quicker than the car park and better for the planet.",
            "generated_at": "2026-07-09T14:30:00Z",
        })}],
    },
    # Example B — watch, Spanish, mobility needs
    {
        "role": "user",
        "parts": [{"text": json.dumps({
            "zone_state": {
                "zone_id": "zone_200_gate_c",
                "zone_name": "200 Level – Gate C Concourse",
                "current_count": 13000,
                "capacity": 18000,
                "forecast_count_15min": 14400,
                "forecast_count_30min": 16000,
                "status": "watch",
                "connected_gates": ["gate_c", "gate_d"],
                "accessible_routes": ["ramp_200_north", "elevator_200_c"],
            },
            "fan_profile": {
                "fan_id": "fan_1137",
                "language": "es",
                "mobility_needs": True,
            },
        })}],
    },
    {
        "role": "model",
        "parts": [{"text": json.dumps({
            "fan_id": "fan_1137",
            "language": "es",
            "mobility_needs": True,
            "message_text": "Te recomendamos dirigirte a la rampa norte 200 para una salida m\u00e1s c\u00f3moda y r\u00e1pida. \u00a1Buen partido!",
            "suggested_route": "ramp_200_north",
            "transit_tip": "El metro l\u00ednea 2 desde la salida norte evita los atascos de tr\u00e1fico.",
            "generated_at": "2026-07-09T14:30:00Z",
        })}],
    },
    # Example C — critical, French, no mobility needs
    {
        "role": "user",
        "parts": [{"text": json.dumps({
            "zone_state": {
                "zone_id": "zone_300_gate_f",
                "zone_name": "300 Level – Gate F Concourse",
                "current_count": 16600,
                "capacity": 18000,
                "forecast_count_15min": 18600,
                "forecast_count_30min": 20200,
                "status": "critical",
                "connected_gates": ["gate_f", "gate_g"],
                "accessible_routes": ["ramp_300_west", "elevator_300_f"],
            },
            "fan_profile": {
                "fan_id": "fan_3302",
                "language": "fr",
                "mobility_needs": False,
            },
        })}],
    },
    {
        "role": "model",
        "parts": [{"text": json.dumps({
            "fan_id": "fan_3302",
            "language": "fr",
            "mobility_needs": False,
            "message_text": "Pour sortir plus rapidement, nous vous conseillons de vous diriger vers la porte f \u2014 c\u2019est l\u2019itin\u00e9raire le plus fluide en ce moment.",
            "suggested_route": "gate_f",
            "transit_tip": "Le bus navette depuis la porte f est plus rapide que la file de taxis ce soir.",
            "generated_at": "2026-07-09T14:30:00Z",
        })}],
    },
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _call_gemini(
    user_message: str,
    temperature: float = 0.5,
) -> Optional[str]:
    """
    Sends a request to the Gemini API and returns the text response.

    Uses JSON mode (response_mime_type="application/json" + response_schema)
    so Gemini enforces the FanNudge shape at generation time, making Tier 1
    parsing succeed in the vast majority of calls.

    Reads GEMINI_API_KEY from environment variables — never hardcoded.
    Returns None if the API call fails for any reason.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
        _here = os.path.dirname(__file__)
        load_dotenv(os.path.join(_here, "../../stadiumpulse/.env"))
        load_dotenv(os.path.join(_here, "../../.env"))
        load_dotenv(os.path.join(_here, "../../../.env"))
        load_dotenv("stadiumpulse/.env")
    except Exception:
        pass

    try:
        import google.generativeai as genai  # noqa: local import
    except ImportError:
        logger.error("google-generativeai SDK not installed. Cannot call Gemini API.")
        return None

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not set in environment variables.")
        return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                response_mime_type="application/json",
                response_schema=NUDGE_RESPONSE_SCHEMA,
            ),
        )
        chat = model.start_chat(history=FEW_SHOT_EXAMPLES)
        response = chat.send_message(user_message)
        return response.text
    except Exception as exc:
        logger.error("Gemini API call failed. Exception Type: %s, Message: %s", type(exc).__name__, str(exc))
        print(f"DEBUG GEMINI NUDGE ERROR: {type(exc).__name__} - {str(exc)}", flush=True)
        return None


def _extract_json(raw_text: str) -> Optional[dict]:
    """
    Tier 1: Attempt to extract valid JSON from raw LLM output.

    With Gemini JSON mode, the response should always be valid JSON.
    The regex fallback handles the rare edge case where it is not.
    """
    if not raw_text:
        return None

    try:
        return json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        pass

    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def _validate_nudge(parsed: dict) -> bool:
    """Check that parsed dict has all required keys for FanNudge.

    transit_tip is optional but, if present, must be a string under 200 chars.
    All other required keys are checked by NUDGE_REQUIRED_KEYS.
    """
    if not isinstance(parsed, dict):
        return False
    if not NUDGE_REQUIRED_KEYS.issubset(parsed.keys()):
        return False
    # Optional field type/length guard
    tip = parsed.get("transit_tip")
    if tip is not None and (not isinstance(tip, str) or len(tip) > 200):
        return False
    return True


# ---------------------------------------------------------------------------
# Fallback transit tips (Tier 3) — generic, per-language, status-agnostic.
# These are intentionally short and practical so they add value even without
# contextual zone data. Indexed by ISO 639-1 language code.
# ---------------------------------------------------------------------------
FALLBACK_TRANSIT_TIPS = {
    "en": "🌿 Take NJ Transit rail from the stadium — 83% lower carbon than driving solo. Electric shuttles depart Gates A & C every 8 minutes.",
    "es": "🌿 Tome el tren NJ Transit desde el estadio — 83% menos carbono que manejar solo. Lanzaderas eléctricas salen de las Puertas A y C cada 8 minutos.",
    "fr": "🌿 Prenez le train NJ Transit depuis le stade — 83 % moins d'émissions que la voiture solo. Navettes électriques au départ des Portes A et C toutes les 8 minutes.",
    "pt": "🌿 Tome o trem NJ Transit a partir do estádio — 83% menos carbono do que dirigir sozinho. Ônibus elétricos partem das Portões A e C a cada 8 minutos.",
    "de": "🌿 Nehmen Sie die NJ Transit Bahn ab dem Stadion — 83 % weniger CO₂ als Autofahren allein. Elektro-Shuttles fahren alle 8 Minuten von den Toren A und C.",
    "ar": "🌿 خذ قطار NJ Transit من الملعب — أقل بنسبة 83٪ من الكربون مقارنةً بالقيادة منفرداً. تتوفر حافلات كهربائية من البوابتين A و C كل 8 دقائق.",
    "it": "🌿 Prendi il treno NJ Transit dallo stadio — l'83% in meno di emissioni rispetto all'auto privata. Navette elettriche dai Cancelli A e C ogni 8 minuti.",
    "ja": "🌿 NJ Transitの電車でスタジアムから移動 — 車での一人移動より炭素排出量が83%少ない。電動シャトルはゲートAとCから8分ごとに出発します。",
    "ko": "🌿 경기장에서 NJ Transit 열차를 이용하세요 — 혼자 운전할 때보다 탄소 배출량이 83% 적습니다. 전기 셔틀은 A, C 게이트에서 8분마다 출발합니다.",
    "zh": "🌿 乘坐NJ Transit火车离开体育场——比独自驾车减少83%碳排放。电动接驳车每8分钟从A门和C门发车。"
}

FALLBACK_TEMPLATES = {
    "en": "For a smoother experience, please head to {route}.",
    "es": "Para una salida más cómoda, diríjase a {route}.",
    "fr": "Pour un trajet plus fluide, veuillez vous diriger vers {route}.",
    "pt": "Para uma saída mais rápida, dirija-se a {route}.",
    "de": "Für einen schnelleren Weg nutzen Sie bitte {route}.",
    "ar": "لتجربة أكثر سلاسة، يرجى التوجه إلى {route}.",
    "it": "Per un percorso più scorrevole, dirigiti verso {route}.",
    "ja": "よりスムーズな移動のため、{route}へお進みください。",
    "ko": "더 원활한 이동을 위해 {route}(으)로 이동해 주세요.",
    "zh": "为了更顺畅的体验，请前往 {route}。"
}

def _build_fallback_nudge(
    zone_state: Dict[str, Any],
    fan_profile: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Tier 3 deterministic fallback — per PROMPT_SPEC.md §3.3.

    Constructs a safe, minimal FanNudge directly from the input data
    without any LLM call, localised to the requested language.
    Includes a hardcoded transit_tip in the same language.
    """
    mobility = fan_profile.get("mobility_needs", False)
    accessible = zone_state.get("accessible_routes", [])
    gates = zone_state.get("connected_gates", [])

    if mobility:
        route = accessible[0] if accessible else "ask_staff"
    else:
        route = gates[0] if gates else (accessible[0] if accessible else "ask_staff")

    lang = fan_profile.get("language", "en")
    # Echo back requested language post-substitution logic
    if lang not in SUPPORTED_LANGUAGES:
        lang = "en"

    # Use localised template if available
    template = FALLBACK_TEMPLATES.get(lang, FALLBACK_TEMPLATES["en"])
    friendly_route = route.replace('_', ' ')
    message_text = template.format(route=friendly_route)

    transit_tip = FALLBACK_TRANSIT_TIPS.get(lang, FALLBACK_TRANSIT_TIPS["en"])

    return {
        "fan_id": fan_profile.get("fan_id", "unknown_fan"),
        "language": lang,
        "mobility_needs": mobility,
        "message_text": message_text,
        "suggested_route": route,
        "transit_tip": transit_tip,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_nudge(
    zone_state: Dict[str, Any],
    fan_profile: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Generate a personalised FanNudge for the given ZoneState + fan profile.

    Uses Gemini (JSON mode) to produce a short, multilingual nudge message.
    Implements the 3-tier fallback strategy defined in PROMPT_SPEC.md §3.3:
        Tier 1 — parse Gemini's guaranteed-JSON response
        Tier 2 — one retry if the API call itself fails or times out
        Tier 3 — deterministic hardcoded fallback (no LLM)

    Language handling (per §3.1):
        If the requested language is not in SUPPORTED_LANGUAGES the fan_profile
        is patched to "en" before calling the LLM, and a warning is logged.
        After receiving the LLM response, the output language is compared to
        the original request; any mismatch is logged.

    Mobility handling (per §3.2):
        If mobility_needs is true and accessible_routes is empty, the fallback
        sets suggested_route to "ask_staff" and logs an operational gap warning.

    The ``generated_at`` timestamp is always set by this function, never
    trusted from the model response (per spec §4 implementation notes).

    Args:
        zone_state: A dict matching the ZoneState JSON schema.
        fan_profile: A dict with keys: fan_id (str), language (str),
                     mobility_needs (bool).

    Returns:
        A dict matching the FanNudge JSON schema.
    """
    original_language = fan_profile.get("language", "en")

    # --- Pre-check: unsupported language fallback (§3.1) ---
    effective_profile = dict(fan_profile)
    if original_language not in SUPPORTED_LANGUAGES:
        logger.warning(
            "Language fallback: requested '%s', got '%s' for fan %s",
            original_language, "en", fan_profile.get("fan_id"),
        )
        effective_profile["language"] = "en"

    # --- Pre-check: empty accessible_routes + mobility_needs (§3.2) ---
    accessible = zone_state.get("accessible_routes", [])
    if fan_profile.get("mobility_needs", False) and not accessible:
        logger.warning(
            "Operational gap: zone %s has no accessible routes but fan %s has mobility needs.",
            zone_state.get("zone_id"), fan_profile.get("fan_id"),
        )

    # Build the user message: two keys, zone_state + fan_profile
    user_payload = json.dumps({
        "zone_state": zone_state,
        "fan_profile": effective_profile,
    })

    # --- Tier 1: initial call ---
    raw = _call_gemini(user_payload)
    if raw is not None:
        parsed = _extract_json(raw)
        if parsed is not None and _validate_nudge(parsed):
            # Post-call language mismatch detection (§3.1)
            output_language = parsed.get("language", "en")
            if output_language != original_language:
                logger.warning(
                    "Language fallback: requested '%s', got '%s' for fan %s",
                    original_language, output_language, fan_profile.get("fan_id"),
                )
            parsed["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return parsed

    # --- Tier 2: one retry ---
    logger.warning("Tier 1 failed for generate_nudge (fan %s). Retrying.", fan_profile.get("fan_id"))
    raw_retry = _call_gemini(user_payload)
    if raw_retry is not None:
        parsed_retry = _extract_json(raw_retry)
        if parsed_retry is not None and _validate_nudge(parsed_retry):
            output_language = parsed_retry.get("language", "en")
            if output_language != original_language:
                logger.warning(
                    "Language fallback: requested '%s', got '%s' for fan %s",
                    original_language, output_language, fan_profile.get("fan_id"),
                )
            parsed_retry["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return parsed_retry

    # --- Tier 3: deterministic fallback ---
    logger.warning("Tier 2 failed for generate_nudge (fan %s). Using deterministic fallback.", fan_profile.get("fan_id"))
    return _build_fallback_nudge(zone_state, fan_profile)
