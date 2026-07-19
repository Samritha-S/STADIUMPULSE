"""
generate_report — Volunteer report triage via Google Gemini LLM.

Takes raw_text and a list of known_zones and produces a VolunteerReport dict
matching the schema at /backend/shared/VolunteerReport.json.
"""

import os
import re
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stadiumpulse.reasoning")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GEMINI_MODEL = "gemini-2.5-flash"

REPORT_REQUIRED_KEYS = {
    "detected_language",
    "zone_id",
    "category",
    "severity",
    "structured_summary",
    "generated_at",
}

VALID_CATEGORIES = {"medical", "security", "crowd", "facility", "other"}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}

# ---------------------------------------------------------------------------
# Response schema for Gemini JSON mode
# Mirrors VolunteerReport.json exactly so Gemini enforces the shape.
# ---------------------------------------------------------------------------
REPORT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "detected_language":  {"type": "string"},
        "zone_id":            {"type": "string"},
        "category":           {"type": "string", "enum": list(VALID_CATEGORIES)},
        "severity":           {"type": "string", "enum": list(VALID_SEVERITIES)},
        "structured_summary": {"type": "string"},
        "generated_at":       {"type": "string"},
    },
    "required": [
        "detected_language", "zone_id", "category", "severity",
        "structured_summary", "generated_at"
    ],
}

# ---------------------------------------------------------------------------
# System prompt — reproduced from PROMPT_SPEC.md §5
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an operational incident triage assistant for MetLife Stadium during the FIFA World Cup 2026.
Your job is to read a volunteer's raw free-text report (which may be in any language), detect the language, and classify it into a structured JSON report.

You are provided with a list of known_zones (valid zone_id strings in the venue model).

OUTPUT RULES:
1. Respond with ONLY a single valid JSON object. No markdown fences, no prose, no explanation.
2. The JSON must contain exactly these keys:
   "detected_language", "zone_id", "category", "severity", "structured_summary", "generated_at"
3. "detected_language" must be the ISO 639-1 code of the raw input text.
4. "zone_id" must match one of the provided known_zones if the text refers to it, or be null if no clear reference is found.
5. "category" must be exactly one of: "medical", "security", "crowd", "facility", "other".
6. "severity" must be exactly one of: "low", "medium", "high", "critical".
7. "structured_summary" must be a clean, objective one-sentence summary of the incident written in English.
8. "generated_at" must be an ISO 8601 UTC timestamp string.

CLASSIFICATION RULES:
- Category definitions:
  - "medical": Physical injury, illness, heat exhaustion, or medical emergencies.
  - "security": Altercations, unauthorized access, suspicious items, thefts, active hazards.
  - "crowd": Congestion, gate blockages, pushy crowds, line management issues.
  - "facility": Broken turnstiles, elevator failures, spills, plumbing issues, lights out.
  - "other": General questions, lost items, or issues not fitting above.
- Severity levels:
  - "critical": Active danger, unconscious person, severe crowd crush, active fire, major safety risk.
  - "high": Impending danger, injured person needing help, minor fights, blocked fire exit.
  - "medium": Broken elevator, slow crowd egress, minor property damage, general congestion.
  - "low": General inquiries, lost items, small trash spills, minor questions.
- Zone Matching:
  - Match names/levels to zone IDs: e.g., "100 level gate A" maps to "zone_100_gate_a", "upper deck F" maps to "zone_300_gate_f", etc.
  - Set zone_id to null if the volunteer does not specify a location or if it matches none of the known_zones.
"""

# ---------------------------------------------------------------------------
# Few-shot examples — reproduced from PROMPT_SPEC.md §5.2
# ---------------------------------------------------------------------------
FEW_SHOT_EXAMPLES: List[Dict[str, Any]] = [
    # Example A
    {
        "role": "user",
        "parts": [{"text": json.dumps({
            "raw_text": "Hay un señor mayor desmayado en la zona del nivel 300 cerca de la puerta F. Por favor traigan asistencia médica rápido.",
            "known_zones": ["zone_100_gate_a", "zone_200_gate_c", "zone_300_gate_f", "zone_field_gate_b"]
        })}],
    },
    {
        "role": "model",
        "parts": [{"text": json.dumps({
            "detected_language": "es",
            "zone_id": "zone_300_gate_f",
            "category": "medical",
            "severity": "critical",
            "structured_summary": "Elderly man passed out near 300 Level Gate F Concourse; medical assistance requested.",
            "generated_at": "2026-07-09T14:30:00Z"
        })}],
    },
    # Example B
    {
        "role": "user",
        "parts": [{"text": json.dumps({
            "raw_text": "Someone is leaving bags near the entrance but I'm not sure which entrance. They look suspicious.",
            "known_zones": ["zone_100_gate_a", "zone_200_gate_c", "zone_300_gate_f", "zone_field_gate_b"]
        })}],
    },
    {
        "role": "model",
        "parts": [{"text": json.dumps({
            "detected_language": "en",
            "zone_id": None,
            "category": "security",
            "severity": "medium",
            "structured_summary": "Suspicious bags reported left unattended near an unspecified stadium entrance.",
            "generated_at": "2026-07-09T14:30:00Z"
        })}],
    },
    # Example C
    {
        "role": "user",
        "parts": [{"text": json.dumps({
            "raw_text": "Le distributeur de savon est vide dans les toilettes du niveau 200, près de la porte C.",
            "known_zones": ["zone_100_gate_a", "zone_200_gate_c", "zone_300_gate_f", "zone_field_gate_b"]
        })}],
    },
    {
        "role": "model",
        "parts": [{"text": json.dumps({
            "detected_language": "fr",
            "zone_id": "zone_200_gate_c",
            "category": "facility",
            "severity": "low",
            "structured_summary": "Soap dispenser reported empty in the 200 Level Gate C Concourse restroom.",
            "generated_at": "2026-07-09T14:30:00Z"
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
    """Sends triage request to Gemini API. Returns text response or None on failure."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        _here = os.path.dirname(__file__)
        load_dotenv(os.path.join(_here, "../../stadiumpulse/.env"))
        load_dotenv(os.path.join(_here, "../../.env"))
        load_dotenv("stadiumpulse/.env")
    except Exception:
        pass

    try:
        import google.generativeai as genai
    except ImportError:
        logger.error("google-generativeai SDK not installed.")
        return None

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not set in environment.")
        return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                response_mime_type="application/json",
                response_schema=REPORT_RESPONSE_SCHEMA,
            ),
        )
        chat = model.start_chat(history=FEW_SHOT_EXAMPLES)
        response = chat.send_message(user_message)
        return response.text
    except Exception as exc:
        logger.error("Gemini API call failed for classify_report: %s", str(exc))
        return None


def _extract_json(raw_text: str) -> Optional[dict]:
    """Tier 1 parse helper."""
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


def _validate_report(parsed: dict, known_zones: List[str]) -> bool:
    """Check required keys and enum constraints."""
    if not isinstance(parsed, dict):
        return False
    if not REPORT_REQUIRED_KEYS.issubset(parsed.keys()):
        return False
    if parsed.get("category") not in VALID_CATEGORIES:
        return False
    if parsed.get("severity") not in VALID_SEVERITIES:
        return False
    # Validate zone_id is either null or in known_zones
    zid = parsed.get("zone_id")
    if zid is not None and zid not in known_zones:
        return False
    return True


def _build_fallback_report(raw_text: str) -> Dict[str, Any]:
    """
    Tier 3 fallback per task:
    severity "medium" (safe default), category "other", and a summary stating manual triage is needed.
    Preserves raw_text.
    """
    return {
        "detected_language": "en",
        "zone_id": None,
        "category": "other",
        "severity": "medium",
        "structured_summary": "Manual triage needed: Automated volunteer report classification failed.",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_report(raw_text: str, known_zones: List[str]) -> Dict[str, Any]:
    """
    Classifies a raw volunteer text report using the 3-tier fallback strategy.
    Always overwrites/populates generated_at with the current UTC timestamp.
    """
    import uuid
    report_id = f"rep_{uuid.uuid4().hex[:8]}"
    user_payload = json.dumps({"raw_text": raw_text, "known_zones": known_zones})

    # Tier 1
    raw = _call_gemini(user_payload)
    if raw is not None:
        parsed = _extract_json(raw)
        if parsed is not None and _validate_report(parsed, known_zones):
            parsed["report_id"] = report_id
            parsed["raw_text"] = raw_text
            parsed["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return parsed

    # Tier 2 (one retry)
    logger.warning("Tier 1 failed for classify_report. Retrying.")
    raw_retry = _call_gemini(user_payload)
    if raw_retry is not None:
        parsed_retry = _extract_json(raw_retry)
        if parsed_retry is not None and _validate_report(parsed_retry, known_zones):
            parsed_retry["report_id"] = report_id
            parsed_retry["raw_text"] = raw_text
            parsed_retry["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return parsed_retry

    # Tier 3 fallback
    logger.warning("Tier 2 failed for classify_report. Using deterministic fallback.")
    fallback = _build_fallback_report(raw_text)
    fallback["report_id"] = report_id
    fallback["raw_text"] = raw_text
    return fallback
