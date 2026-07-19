"""
Tests for the reasoning layer (generate_brief and generate_nudge).

All tests mock the Gemini API call — no real API calls are made. Tests run
offline, fast, and without burning API credits.
"""

import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

# Ensure backend modules are on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

from reasoning.generate_brief import (
    generate_brief,
    _extract_json,
    _validate_brief,
    _build_fallback_brief,
    BRIEF_REQUIRED_KEYS,
)
from reasoning.generate_nudge import (
    generate_nudge,
    _extract_json as nudge_extract_json,
    _validate_nudge,
    _build_fallback_nudge,
    NUDGE_REQUIRED_KEYS,
    SUPPORTED_LANGUAGES,
    FALLBACK_TRANSIT_TIPS,
)


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

ZONE_STATE_CRITICAL = {
    "zone_id": "zone_south_main",
    "zone_name": "South Main Concourse",
    "current_count": 740,
    "capacity": 800,
    "forecast_count_15min": 830,
    "forecast_count_30min": 900,
    "status": "critical",
    "connected_gates": ["gate_1", "gate_2"],
    "accessible_routes": ["ramp_south_1", "elevator_south"],
}

ZONE_STATE_NORMAL = {
    "zone_id": "zone_east_concourse",
    "zone_name": "East Concourse",
    "current_count": 180,
    "capacity": 800,
    "forecast_count_15min": 195,
    "forecast_count_30min": 210,
    "status": "normal",
    "connected_gates": ["gate_5", "gate_6"],
    "accessible_routes": ["ramp_east_1", "elevator_east"],
}

ZONE_STATE_NO_ACCESSIBLE = {
    "zone_id": "zone_west_standing",
    "zone_name": "West Standing Area",
    "current_count": 500,
    "capacity": 600,
    "forecast_count_15min": 550,
    "forecast_count_30min": 580,
    "status": "watch",
    "connected_gates": ["gate_7"],
    "accessible_routes": [],
}

FAN_PROFILE_EN = {"fan_id": "fan_100", "language": "en", "mobility_needs": False}
FAN_PROFILE_ES_MOBILITY = {"fan_id": "fan_200", "language": "es", "mobility_needs": True}
FAN_PROFILE_UNKNOWN_LANG = {"fan_id": "fan_300", "language": "sw", "mobility_needs": False}
FAN_PROFILE_MOBILITY_NO_ROUTES = {"fan_id": "fan_400", "language": "en", "mobility_needs": True}

# A valid mock LLM response for a brief (JSON string — mirrors what response.text returns)
VALID_BRIEF_RESPONSE = json.dumps({
    "zone_id": "zone_south_main",
    "severity": "critical",
    "summary_text": "South Main Concourse is at 92% capacity.",
    "recommended_action": "Deploy staff to gate 1 and gate 2.",
    "suggested_reroute_zone": "ramp_south_1",
    "languages_needed": ["en", "es"],
    "generated_at": "2026-07-09T14:30:00Z",
})

# A valid mock LLM response for a nudge (JSON string — mirrors what response.text returns)
# Includes transit_tip to reflect the updated schema.
VALID_NUDGE_RESPONSE = json.dumps({
    "fan_id": "fan_100",
    "language": "en",
    "mobility_needs": False,
    "message_text": "Just a heads-up — gate 5 has shorter lines right now.",
    "suggested_route": "gate_5",
    "transit_tip": "Taking the metro tonight? It's quicker than the car park.",
    "generated_at": "2026-07-09T14:30:00Z",
})

# A valid nudge response WITHOUT transit_tip — tests backward-compat with
# LLM responses that may omit the optional field.
VALID_NUDGE_RESPONSE_NO_TIP = json.dumps({
    "fan_id": "fan_100",
    "language": "en",
    "mobility_needs": False,
    "message_text": "Just a heads-up — gate 5 has shorter lines right now.",
    "suggested_route": "gate_5",
    "generated_at": "2026-07-09T14:30:00Z",
})


# ===================================================================
# generate_brief tests
# ===================================================================

class TestGenerateBrief(unittest.TestCase):
    """Tests for generate_brief() covering happy path, fallback tiers, and edge cases."""

    @patch("reasoning.generate_brief._call_gemini")
    def test_valid_llm_response_parsed_correctly(self, mock_gemini):
        """A well-formed LLM response is parsed and returned with all required keys."""
        mock_gemini.return_value = VALID_BRIEF_RESPONSE

        result = generate_brief(ZONE_STATE_CRITICAL)

        self.assertIsInstance(result, dict)
        self.assertTrue(BRIEF_REQUIRED_KEYS.issubset(result.keys()))
        self.assertEqual(result["zone_id"], "zone_south_main")
        self.assertEqual(result["severity"], "critical")
        self.assertIn("summary_text", result)
        self.assertIn("recommended_action", result)
        # generated_at must be set by calling code, not the LLM value
        self.assertNotEqual(result["generated_at"], "2026-07-09T14:30:00Z")

    @patch("reasoning.generate_brief._call_gemini")
    def test_generated_at_overwritten_by_caller(self, mock_gemini):
        """The generated_at timestamp must come from the caller, not from the LLM."""
        mock_gemini.return_value = VALID_BRIEF_RESPONSE

        before = datetime.now(timezone.utc)
        result = generate_brief(ZONE_STATE_CRITICAL)
        after = datetime.now(timezone.utc)

        ts = datetime.fromisoformat(result["generated_at"])
        self.assertGreaterEqual(ts, before.replace(microsecond=0))
        self.assertLessEqual(ts, after.replace(microsecond=0) + __import__('datetime').timedelta(seconds=1))

    @patch("reasoning.generate_brief._call_gemini")
    def test_json_wrapped_in_markdown_fences_tier1_strips(self, mock_gemini):
        """Tier 1: JSON wrapped in markdown fences is extracted and parsed."""
        wrapped = "Here is the brief:\n```json\n" + VALID_BRIEF_RESPONSE + "\n```"
        mock_gemini.return_value = wrapped

        result = generate_brief(ZONE_STATE_CRITICAL)

        self.assertEqual(result["zone_id"], "zone_south_main")
        self.assertEqual(result["severity"], "critical")
        # Should succeed on first call (Tier 1), so _call_gemini called once
        mock_gemini.assert_called_once()

    @patch("reasoning.generate_brief._call_gemini")
    def test_malformed_response_triggers_tier2_retry(self, mock_gemini):
        """Tier 2: If Tier 1 fails, one retry is made."""
        # First call returns garbage, second call returns valid JSON
        mock_gemini.side_effect = ["This is not JSON at all!!!", VALID_BRIEF_RESPONSE]

        result = generate_brief(ZONE_STATE_CRITICAL)

        self.assertEqual(result["zone_id"], "zone_south_main")
        self.assertEqual(mock_gemini.call_count, 2)

    @patch("reasoning.generate_brief._call_gemini")
    def test_both_calls_fail_triggers_tier3_fallback(self, mock_gemini):
        """Tier 3: If both LLM calls fail, a deterministic fallback is returned."""
        mock_gemini.return_value = None  # Simulate API failure

        result = generate_brief(ZONE_STATE_CRITICAL)

        self.assertEqual(result["zone_id"], "zone_south_main")
        self.assertEqual(result["severity"], "critical")  # critical -> critical
        self.assertIn("Automated summary unavailable", result["summary_text"])
        self.assertIn("LLM summary generation failed", result["recommended_action"])
        self.assertEqual(result["languages_needed"], ["en"])

    @patch("reasoning.generate_brief._call_gemini")
    def test_fallback_severity_mapping_normal(self, mock_gemini):
        """Tier 3 fallback maps status 'normal' to severity 'low'."""
        mock_gemini.return_value = None

        result = generate_brief(ZONE_STATE_NORMAL)

        self.assertEqual(result["severity"], "low")

    @patch("reasoning.generate_brief._call_gemini")
    def test_fallback_reroute_uses_first_accessible_route(self, mock_gemini):
        """Tier 3 fallback picks the first accessible_route for suggested_reroute_zone."""
        mock_gemini.return_value = None

        result = generate_brief(ZONE_STATE_CRITICAL)

        self.assertEqual(result["suggested_reroute_zone"], "ramp_south_1")

    @patch("reasoning.generate_brief._call_gemini")
    def test_fallback_reroute_none_when_no_routes(self, mock_gemini):
        """Tier 3 fallback returns 'none' when accessible_routes is empty."""
        mock_gemini.return_value = None

        result = generate_brief(ZONE_STATE_NO_ACCESSIBLE)

        self.assertEqual(result["suggested_reroute_zone"], "none")


# ===================================================================
# generate_nudge tests
# ===================================================================

class TestGenerateNudge(unittest.TestCase):
    """Tests for generate_nudge() covering happy path, language fallback,
    mobility edge cases, and the 3-tier fallback chain."""

    @patch("reasoning.generate_nudge._call_gemini")
    def test_valid_llm_response_parsed_correctly(self, mock_gemini):
        """A well-formed LLM response is parsed and returned with all required keys."""
        mock_gemini.return_value = VALID_NUDGE_RESPONSE

        result = generate_nudge(ZONE_STATE_NORMAL, FAN_PROFILE_EN)

        self.assertIsInstance(result, dict)
        self.assertTrue(NUDGE_REQUIRED_KEYS.issubset(result.keys()))
        self.assertEqual(result["fan_id"], "fan_100")
        self.assertEqual(result["language"], "en")
        self.assertFalse(result["mobility_needs"])
        self.assertIn("message_text", result)

    @patch("reasoning.generate_nudge._call_gemini")
    def test_generated_at_overwritten_by_caller(self, mock_gemini):
        """The generated_at timestamp must come from the caller, not from the LLM."""
        mock_gemini.return_value = VALID_NUDGE_RESPONSE

        result = generate_nudge(ZONE_STATE_NORMAL, FAN_PROFILE_EN)

        self.assertNotEqual(result["generated_at"], "2026-07-09T14:30:00Z")

    @patch("reasoning.generate_nudge._call_gemini")
    def test_unknown_language_falls_back_to_english(self, mock_gemini):
        """
        When fan_profile.language is not in SUPPORTED_LANGUAGES, the code
        patches the profile to 'en' before calling the LLM, and a warning is logged.
        """
        # The LLM receives "en" and responds in English
        en_response = json.dumps({
            "fan_id": "fan_300",
            "language": "en",
            "mobility_needs": False,
            "message_text": "Gate 5 has shorter lines right now.",
            "suggested_route": "gate_5",
            "generated_at": "2026-07-09T14:30:00Z",
        })
        mock_gemini.return_value = en_response

        with self.assertLogs("stadiumpulse.reasoning", level="WARNING") as log_ctx:
            result = generate_nudge(ZONE_STATE_NORMAL, FAN_PROFILE_UNKNOWN_LANG)

        # Check that a language fallback warning was logged
        self.assertTrue(
            any("Language fallback" in msg and "'sw'" in msg for msg in log_ctx.output),
            f"Expected language fallback warning in logs, got: {log_ctx.output}"
        )
        # Result should still be delivered
        self.assertEqual(result["fan_id"], "fan_300")

    @patch("reasoning.generate_nudge._call_gemini")
    def test_empty_accessible_routes_with_mobility_needs(self, mock_gemini):
        """
        When mobility_needs is True and accessible_routes is empty, the
        Tier 3 fallback must set suggested_route to 'ask_staff'.
        This test forces Tier 3 by making the API return None.
        """
        mock_gemini.return_value = None  # Force all tiers to fail -> Tier 3

        with self.assertLogs("stadiumpulse.reasoning", level="WARNING") as log_ctx:
            result = generate_nudge(ZONE_STATE_NO_ACCESSIBLE, FAN_PROFILE_MOBILITY_NO_ROUTES)

        self.assertEqual(result["suggested_route"], "ask_staff")
        # Check that the operational gap was logged
        self.assertTrue(
            any("Operational gap" in msg or "no accessible routes" in msg for msg in log_ctx.output),
            f"Expected operational gap warning in logs, got: {log_ctx.output}"
        )

    @patch("reasoning.generate_nudge._call_gemini")
    def test_mobility_needs_uses_accessible_route_in_fallback(self, mock_gemini):
        """
        Tier 3 fallback: when mobility_needs is True, suggested_route must
        come from accessible_routes (not connected_gates).
        """
        mock_gemini.return_value = None

        result = generate_nudge(ZONE_STATE_CRITICAL, FAN_PROFILE_ES_MOBILITY)

        self.assertEqual(result["suggested_route"], "ramp_south_1")
        self.assertIn(result["suggested_route"], ZONE_STATE_CRITICAL["accessible_routes"])

    @patch("reasoning.generate_nudge._call_gemini")
    def test_malformed_response_triggers_tier2_retry(self, mock_gemini):
        """Tier 2: If Tier 1 fails, one retry is made."""
        mock_gemini.side_effect = ["NOT JSON {{{broken", VALID_NUDGE_RESPONSE]

        result = generate_nudge(ZONE_STATE_NORMAL, FAN_PROFILE_EN)

        self.assertEqual(result["fan_id"], "fan_100")
        self.assertEqual(mock_gemini.call_count, 2)

    @patch("reasoning.generate_nudge._call_gemini")
    def test_both_calls_fail_triggers_tier3_fallback(self, mock_gemini):
        """Tier 3: If both LLM calls fail, a deterministic fallback is returned."""
        mock_gemini.return_value = None

        result = generate_nudge(ZONE_STATE_NORMAL, FAN_PROFILE_EN)

        self.assertEqual(result["fan_id"], "fan_100")
        self.assertEqual(result["language"], "en")
        self.assertIn("suggested_route", result)
        self.assertIn("message_text", result)
        # Fallback should pick from connected_gates since mobility_needs is False
        self.assertEqual(result["suggested_route"], "gate_5")

    @patch("reasoning.generate_nudge._call_gemini")
    def test_json_with_surrounding_prose_tier1_strips(self, mock_gemini):
        """Tier 1: JSON embedded in surrounding prose is extracted correctly."""
        wrapped = "Sure, here is the nudge:\n" + VALID_NUDGE_RESPONSE + "\nHope that helps!"
        mock_gemini.return_value = wrapped

        result = generate_nudge(ZONE_STATE_NORMAL, FAN_PROFILE_EN)

        self.assertEqual(result["fan_id"], "fan_100")
        mock_gemini.assert_called_once()

    @patch("reasoning.generate_nudge._call_gemini")
    def test_tier3_fallback_preserves_supported_languages(self, mock_gemini):
        """Tier 3 fallback preserves a supported non-English language and returns translated templates."""
        mock_gemini.return_value = None  # Force Tier 3 fallback

        profile_es = {"fan_id": "fan_123", "language": "es", "mobility_needs": False}
        result = generate_nudge(ZONE_STATE_NORMAL, profile_es)

        self.assertEqual(result["fan_id"], "fan_123")
        self.assertEqual(result["language"], "es")
        self.assertIn("Para una salida más cómoda", result["message_text"])
        self.assertEqual(result["suggested_route"], "gate_5")


# ===================================================================
# Internal helper unit tests
# ===================================================================

class TestExtractJson(unittest.TestCase):
    """Tests for the _extract_json helper used by both modules."""

    def test_valid_json_string(self):
        self.assertEqual(_extract_json('{"a": 1}'), {"a": 1})

    def test_json_inside_markdown_fences(self):
        text = '```json\n{"a": 1}\n```'
        self.assertEqual(_extract_json(text), {"a": 1})

    def test_json_with_prose(self):
        text = 'Here is: {"a": 1} done'
        self.assertEqual(_extract_json(text), {"a": 1})

    def test_completely_invalid(self):
        self.assertIsNone(_extract_json("no json here"))

    def test_none_input(self):
        self.assertIsNone(_extract_json(None))

    def test_empty_string(self):
        self.assertIsNone(_extract_json(""))


class TestValidateBrief(unittest.TestCase):
    def test_valid(self):
        brief = {k: "x" for k in BRIEF_REQUIRED_KEYS}
        brief["severity"] = "low"
        self.assertTrue(_validate_brief(brief))

    def test_missing_key(self):
        brief = {k: "x" for k in BRIEF_REQUIRED_KEYS}
        brief["severity"] = "low"
        del brief["zone_id"]
        self.assertFalse(_validate_brief(brief))

    def test_invalid_severity(self):
        brief = {k: "x" for k in BRIEF_REQUIRED_KEYS}
        brief["severity"] = "extreme"
        self.assertFalse(_validate_brief(brief))


class TestValidateNudge(unittest.TestCase):
    def test_valid(self):
        nudge = {k: "x" for k in NUDGE_REQUIRED_KEYS}
        self.assertTrue(_validate_nudge(nudge))

    def test_missing_key(self):
        nudge = {k: "x" for k in NUDGE_REQUIRED_KEYS}
        del nudge["fan_id"]
        self.assertFalse(_validate_nudge(nudge))

    def test_transit_tip_absent_is_valid(self):
        """transit_tip is optional — its absence must not fail validation."""
        nudge = {k: "x" for k in NUDGE_REQUIRED_KEYS}
        nudge.pop("transit_tip", None)  # ensure it's absent
        self.assertTrue(_validate_nudge(nudge))

    def test_transit_tip_present_and_valid(self):
        """transit_tip present as a short string must pass validation."""
        nudge = {k: "x" for k in NUDGE_REQUIRED_KEYS}
        nudge["transit_tip"] = "Take the metro — it's faster than driving."
        self.assertTrue(_validate_nudge(nudge))

    def test_transit_tip_wrong_type_fails(self):
        """transit_tip must be a string if present; a non-string must fail."""
        nudge = {k: "x" for k in NUDGE_REQUIRED_KEYS}
        nudge["transit_tip"] = 42  # wrong type
        self.assertFalse(_validate_nudge(nudge))

    def test_transit_tip_too_long_fails(self):
        """transit_tip longer than 200 chars must fail the optional length guard."""
        nudge = {k: "x" for k in NUDGE_REQUIRED_KEYS}
        nudge["transit_tip"] = "x" * 201
        self.assertFalse(_validate_nudge(nudge))


# ===================================================================
# transit_tip integration tests
# ===================================================================

class TestTransitTip(unittest.TestCase):
    """Tests that transit_tip flows correctly through the generation pipeline."""

    @patch("reasoning.generate_nudge._call_gemini")
    def test_transit_tip_in_valid_llm_response(self, mock_gemini):
        """When the LLM includes transit_tip, it is preserved in the output."""
        mock_gemini.return_value = VALID_NUDGE_RESPONSE  # fixture includes transit_tip

        result = generate_nudge(ZONE_STATE_NORMAL, FAN_PROFILE_EN)

        self.assertIn("transit_tip", result)
        self.assertIsInstance(result["transit_tip"], str)
        self.assertGreater(len(result["transit_tip"]), 0)

    @patch("reasoning.generate_nudge._call_gemini")
    def test_no_transit_tip_in_llm_response_is_accepted(self, mock_gemini):
        """When the LLM omits transit_tip, the nudge is still valid (optional field)."""
        mock_gemini.return_value = VALID_NUDGE_RESPONSE_NO_TIP  # no transit_tip

        result = generate_nudge(ZONE_STATE_NORMAL, FAN_PROFILE_EN)

        # Core required fields must still be present
        self.assertIn("message_text", result)
        self.assertIn("suggested_route", result)
        self.assertEqual(result["fan_id"], "fan_100")

    @patch("reasoning.generate_nudge._call_gemini")
    def test_tier3_fallback_includes_transit_tip(self, mock_gemini):
        """Tier 3 fallback must always include transit_tip from FALLBACK_TRANSIT_TIPS."""
        mock_gemini.return_value = None  # force Tier 3

        result = generate_nudge(ZONE_STATE_NORMAL, FAN_PROFILE_EN)

        self.assertIn("transit_tip", result)
        self.assertEqual(result["transit_tip"], FALLBACK_TRANSIT_TIPS["en"])

    @patch("reasoning.generate_nudge._call_gemini")
    def test_tier3_fallback_transit_tip_localised(self, mock_gemini):
        """Tier 3 fallback transit_tip must be in the fan's requested language."""
        mock_gemini.return_value = None  # force Tier 3

        profile_fr = {"fan_id": "fan_fr1", "language": "fr", "mobility_needs": False}
        result = generate_nudge(ZONE_STATE_NORMAL, profile_fr)

        self.assertEqual(result["language"], "fr")
        self.assertEqual(result["transit_tip"], FALLBACK_TRANSIT_TIPS["fr"])

    @patch("reasoning.generate_nudge._call_gemini")
    def test_existing_fields_not_broken_by_transit_tip(self, mock_gemini):
        """Adding transit_tip must not break message_text, suggested_route, or mobility_needs."""
        mock_gemini.return_value = VALID_NUDGE_RESPONSE

        result = generate_nudge(ZONE_STATE_NORMAL, FAN_PROFILE_EN)

        self.assertEqual(result["fan_id"], "fan_100")
        self.assertEqual(result["language"], "en")
        self.assertFalse(result["mobility_needs"])
        self.assertIn("message_text", result)
        self.assertIn("suggested_route", result)
        # transit_tip must not have overwritten any required field
        self.assertTrue(NUDGE_REQUIRED_KEYS.issubset(result.keys()))


if __name__ == '__main__':
    unittest.main()
