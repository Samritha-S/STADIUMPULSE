"""
generate_brief — Control Room Brief generation via Google Gemini LLM.

Takes a ZoneState dict and produces a ControlRoomBrief dict matching the
schema at /backend/shared/ControlRoomBrief.json.

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

Example Output:
    {
        "zone_id": "zone_north_gate3",
        "severity": "medium",
        "summary_text": "North Concourse Gate 3 is at 72% capacity (580/800) ...",
        "recommended_action": "Increase monitoring at gate 3 and gate 4. ...",
        "suggested_reroute_zone": "ramp_north_1",
        "languages_needed": ["en", "es", "fr"],
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
GEMINI_MODEL = "gemini-1.5-flash"

# Required keys per ControlRoomBrief schema
BRIEF_REQUIRED_KEYS = {
    "zone_id", "severity", "summary_text", "recommended_action",
    "suggested_reroute_zone", "languages_needed", "generated_at",
}

# Valid severity values per schema enum
VALID_SEVERITIES = {"low", "medium", "high", "critical"}

# Status-to-severity mapping for deterministic fallback (Tier 3)
STATUS_TO_SEVERITY = {
    "normal": "low",
    "watch": "medium",
    "critical": "critical",
}

# ---------------------------------------------------------------------------
# Response schema for Gemini JSON mode
# Mirrors ControlRoomBrief.json exactly so Gemini enforces the shape at
# generation time, making Tier 1 parse almost always succeed.
# ---------------------------------------------------------------------------
BRIEF_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "zone_id":               {"type": "string"},
        "severity":              {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "summary_text":          {"type": "string"},
        "recommended_action":    {"type": "string"},
        "suggested_reroute_zone":{"type": "string"},
        "languages_needed":      {"type": "array", "items": {"type": "string"}},
        "generated_at":          {"type": "string"},
    },
    "required": [
        "zone_id", "severity", "summary_text", "recommended_action",
        "suggested_reroute_zone", "languages_needed", "generated_at",
    ],
}

# ---------------------------------------------------------------------------
# System prompt — reproduced verbatim from PROMPT_SPEC.md §1
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an operational intelligence system for FIFA World Cup 2026 stadium crowd management.

Your job is to read a ZoneState JSON object describing one stadium zone's current occupancy, \
forecasts, and safety status, and produce a single ControlRoomBrief JSON object for \
control-room operators.

OUTPUT RULES — you MUST follow all of these:
1. Respond with ONLY a single valid JSON object. No markdown fences, no prose, no \
explanation before or after the JSON.
2. The JSON must contain exactly these keys, no more and no fewer:
   "zone_id", "severity", "summary_text", "recommended_action", \
"suggested_reroute_zone", "languages_needed", "generated_at"
3. "severity" must be one of: "low", "medium", "high", "critical".
4. "languages_needed" must be a JSON array of ISO 639-1 language code strings. Always \
include "en". Add other languages proportional to the likely crowd demographics at \
a FIFA World Cup (e.g. "es", "fr", "ar", "pt").
5. "generated_at" must be an ISO 8601 UTC timestamp string (e.g. "2026-07-09T14:30:00Z").

TONE:
- Calm, direct, and actionable. This is a safety operations context, not marketing.
- Use short declarative sentences. Avoid hedging language ("might", "could possibly").
- Never use exclamation marks or alarming language. Operators need clarity, not panic.

SEVERITY-TO-ACTION MAPPING:
- When ZoneState.status is "normal":
  Set severity to "low". summary_text should be a one-sentence confirmation that the \
zone is operating within safe parameters. recommended_action should be "No action \
required. Continue routine monitoring." suggested_reroute_zone should be "none".

- When ZoneState.status is "watch":
  Set severity to "medium". summary_text should note the rising trend and the 15-min / \
30-min forecasted counts relative to capacity. recommended_action should recommend \
increased monitoring and an optional soft PA announcement advising fans of \
alternative routes. suggested_reroute_zone should name the least-loaded route from \
accessible_routes.

- When ZoneState.status is "critical":
  Set severity to "high" or "critical" depending on whether the forecast exceeds \
capacity. summary_text must state the forecasted breach clearly with numbers. \
recommended_action must be a specific, concrete directive: deploy staff to named \
gates, activate hard PA reroute announcements, and optionally request additional \
security. suggested_reroute_zone must name a specific route from accessible_routes.

CONTEXT ABOUT THE INPUT:
- connected_gates lists the physical gates adjacent to the zone.
- accessible_routes lists step-free / wheelchair-accessible paths from the zone.
- Use these lists to make suggested_reroute_zone concrete and grounded, never invented."""

# ---------------------------------------------------------------------------
# Few-shot examples — reproduced verbatim from PROMPT_SPEC.md §1.1
# Formatted as Gemini content turns (role: user / model).
# ---------------------------------------------------------------------------
FEW_SHOT_EXAMPLES: List[Dict[str, Any]] = [
    # Example A — normal
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
            }
        })}],
    },
    {
        "role": "model",
        "parts": [{"text": json.dumps({
            "zone_id": "zone_100_gate_a",
            "severity": "low",
            "summary_text": "100 Level – Gate A Concourse is at 22% capacity (4200/19500). Forecast shows 4900 in 30 minutes, well within safe limits.",
            "recommended_action": "No action required. Continue routine monitoring.",
            "suggested_reroute_zone": "none",
            "languages_needed": ["en", "es"],
            "generated_at": "2026-07-09T14:30:00Z",
        })}],
    },
    # Example B — watch
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
            }
        })}],
    },
    {
        "role": "model",
        "parts": [{"text": json.dumps({
            "zone_id": "zone_200_gate_c",
            "severity": "medium",
            "summary_text": "200 Level – Gate C Concourse is at 72% capacity (13000/18000) and rising. Forecast projects 14400 in 15 min (80%) and 16000 in 30 min (89%). Trend is approaching the critical threshold.",
            "recommended_action": "Increase monitoring at gate C and gate D. Consider a soft PA announcement advising fans that ramp_200_north and elevator_200_c offer shorter wait times.",
            "suggested_reroute_zone": "ramp_200_north",
            "languages_needed": ["en", "es", "fr"],
            "generated_at": "2026-07-09T14:30:00Z",
        })}],
    },
    # Example C — critical
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
            }
        })}],
    },
    {
        "role": "model",
        "parts": [{"text": json.dumps({
            "zone_id": "zone_300_gate_f",
            "severity": "critical",
            "summary_text": "300 Level – Gate F Concourse is at 92% capacity (16600/18000). Forecast projects 18600 in 15 min, exceeding capacity by 600 persons. 30-min forecast of 20200 represents 112% capacity. Immediate intervention required.",
            "recommended_action": "Deploy crowd management staff to gate F and gate G immediately. Activate hard PA reroute announcement directing fans to ramp_300_west. Close inbound flow at gate F if count exceeds 18000 within 5 minutes. Request additional security standby.",
            "suggested_reroute_zone": "ramp_300_west",
            "languages_needed": ["en", "es", "fr", "ar", "pt"],
            "generated_at": "2026-07-09T14:30:00Z",
        })}],
    },
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _call_gemini(
    user_message: str,
    temperature: float = 0.3,
) -> Optional[str]:
    """
    Sends a request to the Gemini API and returns the text response.

    Uses JSON mode (response_mime_type="application/json" + response_schema)
    so Gemini enforces the ControlRoomBrief shape at generation time, making
    Tier 1 parsing succeed in the vast majority of calls.

    Reads GEMINI_API_KEY from environment variables — never hardcoded.
    Returns None if the API call fails for any reason.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
        _here = os.path.dirname(__file__)
        load_dotenv(os.path.join(_here, "../../.env"))
        load_dotenv(os.path.join(_here, "../../../.env"))
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
                response_schema=BRIEF_RESPONSE_SCHEMA,
            ),
        )
        chat = model.start_chat(history=FEW_SHOT_EXAMPLES)
        response = chat.send_message(user_message)
        return response.text
    except Exception as exc:
        logger.error("Gemini API call failed. Exception Type: %s, Message: %s", type(exc).__name__, str(exc))
        print(f"DEBUG GEMINI BRIEF ERROR: {type(exc).__name__} - {str(exc)}", flush=True)
        return None


def _extract_json(raw_text: str) -> Optional[dict]:
    """
    Tier 1: Attempt to extract valid JSON from raw LLM output.

    With Gemini JSON mode, the response should always be valid JSON.
    The regex fallback handles the rare edge case where it is not.
    """
    if not raw_text:
        return None

    # Fast path: the full response is valid JSON (expected with JSON mode)
    try:
        return json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        pass

    # Slow path: strip surrounding prose / markdown fences, find first {...}
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def _validate_brief(parsed: dict) -> bool:
    """Check that parsed dict has all required keys and valid severity value."""
    if not isinstance(parsed, dict):
        return False
    if not BRIEF_REQUIRED_KEYS.issubset(parsed.keys()):
        return False
    if parsed.get("severity") not in VALID_SEVERITIES:
        return False
    return True


def _build_fallback_brief(zone_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tier 3 deterministic fallback — per PROMPT_SPEC.md §3.3.

    Constructs a safe, minimal ControlRoomBrief directly from the input
    ZoneState without any LLM call.
    """
    status = zone_state.get("status", "normal")
    severity = STATUS_TO_SEVERITY.get(status, "low")
    zone_name = zone_state.get("zone_name", "Unknown Zone")
    current = zone_state.get("current_count", 0)
    capacity = zone_state.get("capacity", 0)
    routes = zone_state.get("accessible_routes", [])

    return {
        "zone_id": zone_state.get("zone_id", "unknown_zone"),
        "severity": severity,
        "summary_text": (
            f"{zone_name} is at {current}/{capacity} capacity. "
            "Automated summary unavailable."
        ),
        "recommended_action": "Manual assessment recommended. LLM summary generation failed.",
        "suggested_reroute_zone": routes[0] if routes else "none",
        "languages_needed": ["en"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_brief(zone_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a ControlRoomBrief for the given ZoneState.

    Uses Gemini (JSON mode) to produce a situational brief for control-room
    operators. Implements the 3-tier fallback strategy defined in
    PROMPT_SPEC.md §3.3:
        Tier 1 — parse Gemini's guaranteed-JSON response
        Tier 2 — one retry if the API call itself fails or returns unparseable output
        Tier 3 — deterministic hardcoded fallback (no LLM)

    The ``generated_at`` timestamp is always set by this function, never
    trusted from the model response (per spec §4 implementation notes).

    Args:
        zone_state: A dict matching the ZoneState JSON schema.

    Returns:
        A dict matching the ControlRoomBrief JSON schema.
    """
    user_message = json.dumps(zone_state)

    # --- Tier 1: initial call ---
    raw = _call_gemini(user_message)
    if raw is not None:
        parsed = _extract_json(raw)
        if parsed is not None and _validate_brief(parsed):
            parsed["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return parsed

    # --- Tier 2: one retry ---
    logger.warning("Tier 1 failed for generate_brief (zone %s). Retrying.", zone_state.get("zone_id"))
    raw_retry = _call_gemini(user_message)
    if raw_retry is not None:
        parsed_retry = _extract_json(raw_retry)
        if parsed_retry is not None and _validate_brief(parsed_retry):
            parsed_retry["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return parsed_retry

    # --- Tier 3: deterministic fallback ---
    logger.warning("Tier 2 failed for generate_brief (zone %s). Using deterministic fallback.", zone_state.get("zone_id"))
    return _build_fallback_brief(zone_state)
