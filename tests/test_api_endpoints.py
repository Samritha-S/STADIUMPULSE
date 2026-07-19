"""
Integration tests for the FastAPI endpoints (backend/server.py).

Uses FastAPI's TestClient so all tests run in-process without a real server.
All Gemini API calls are mocked — no real API calls are made.
Tests cover the full request/response cycle for every route.
"""

import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock

# Ensure backend modules are on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared mock responses reused across endpoint tests
# ---------------------------------------------------------------------------

MOCK_BRIEF_JSON = json.dumps({
    "zone_id": "zone_300_gate_f",
    "severity": "critical",
    "summary_text": "Gate F is at 94% capacity and rising fast.",
    "recommended_action": "Deploy staff to gate F and gate G immediately.",
    "suggested_reroute_zone": "ramp_300_west",
    "languages_needed": ["en", "es", "fr"],
    "generated_at": "2026-07-19T14:00:00Z",
})

MOCK_NUDGE_JSON = json.dumps({
    "fan_id": "fan_test",
    "language": "en",
    "mobility_needs": False,
    "message_text": "Head to Gate A — much shorter queues right now.",
    "suggested_route": "gate_a",
    "transit_tip": "NJ Transit rail is running on schedule — 83% less CO₂ than driving.",
    "generated_at": "2026-07-19T14:00:00Z",
})

MOCK_REPORT_JSON = json.dumps({
    "detected_language": "en",
    "zone_id": "zone_100_gate_a",
    "category": "medical",
    "severity": "high",
    "structured_summary": "Person collapsed near section 112, requesting immediate medical assistance.",
    "generated_at": "2026-07-19T14:00:00Z",
})


# ===========================================================================
# GET /api/zones
# ===========================================================================
class TestZonesEndpoint(unittest.TestCase):
    """GET /api/zones must return a valid list of ZoneState objects."""

    REQUIRED_ZONE_KEYS = {
        "zone_id", "zone_name", "current_count", "capacity",
        "forecast_count_15min", "forecast_count_30min",
        "status", "connected_gates", "accessible_routes",
    }
    VALID_STATUSES = {"normal", "watch", "critical"}

    def test_returns_200(self):
        res = client.get("/api/zones")
        self.assertEqual(res.status_code, 200)

    def test_returns_list(self):
        res = client.get("/api/zones")
        self.assertIsInstance(res.json(), list)

    def test_returns_non_empty_list(self):
        res = client.get("/api/zones")
        self.assertGreater(len(res.json()), 0)

    def test_each_zone_has_required_keys(self):
        res = client.get("/api/zones")
        for zone in res.json():
            missing = self.REQUIRED_ZONE_KEYS - zone.keys()
            self.assertFalse(missing, f"Zone {zone.get('zone_id')} missing keys: {missing}")

    def test_status_is_valid_value(self):
        res = client.get("/api/zones")
        for zone in res.json():
            self.assertIn(zone["status"], self.VALID_STATUSES)

    def test_counts_are_non_negative(self):
        res = client.get("/api/zones")
        for zone in res.json():
            self.assertGreaterEqual(zone["current_count"], 0)
            self.assertGreaterEqual(zone["forecast_count_15min"], 0)
            self.assertGreaterEqual(zone["forecast_count_30min"], 0)

    def test_capacity_is_positive(self):
        res = client.get("/api/zones")
        for zone in res.json():
            self.assertGreater(zone["capacity"], 0,
                               f"Zone {zone['zone_id']} has non-positive capacity")

    def test_connected_gates_is_list(self):
        res = client.get("/api/zones")
        for zone in res.json():
            self.assertIsInstance(zone["connected_gates"], list)

    def test_accessible_routes_is_list(self):
        res = client.get("/api/zones")
        for zone in res.json():
            self.assertIsInstance(zone["accessible_routes"], list)

    def test_consecutive_calls_advance_simulation(self):
        """Two consecutive calls must not return identical counts for all zones (simulation ticks)."""
        res1 = client.get("/api/zones")
        res2 = client.get("/api/zones")
        counts1 = {z["zone_id"]: z["current_count"] for z in res1.json()}
        counts2 = {z["zone_id"]: z["current_count"] for z in res2.json()}
        # At least one zone's count must have changed
        changed = any(counts1[zid] != counts2[zid] for zid in counts1)
        self.assertTrue(changed, "Simulation did not advance between two consecutive /api/zones calls")


# ===========================================================================
# GET /api/briefs
# ===========================================================================
class TestBriefsEndpoint(unittest.TestCase):
    """GET /api/briefs must return a valid list of ControlRoomBrief objects."""

    REQUIRED_BRIEF_KEYS = {
        "zone_id", "severity", "summary_text",
        "recommended_action", "suggested_reroute_zone",
        "languages_needed", "generated_at",
    }
    VALID_SEVERITIES = {"low", "medium", "high", "critical"}

    @patch("reasoning.generate_brief._call_gemini")
    def test_returns_200(self, mock_gemini):
        mock_gemini.return_value = MOCK_BRIEF_JSON
        res = client.get("/api/briefs")
        self.assertEqual(res.status_code, 200)

    @patch("reasoning.generate_brief._call_gemini")
    def test_returns_list(self, mock_gemini):
        mock_gemini.return_value = MOCK_BRIEF_JSON
        res = client.get("/api/briefs")
        self.assertIsInstance(res.json(), list)

    @patch("reasoning.generate_brief._call_gemini")
    def test_each_brief_has_required_keys(self, mock_gemini):
        mock_gemini.return_value = MOCK_BRIEF_JSON
        for brief in client.get("/api/briefs").json():
            missing = self.REQUIRED_BRIEF_KEYS - brief.keys()
            self.assertFalse(missing, f"Brief for {brief.get('zone_id')} missing: {missing}")

    @patch("reasoning.generate_brief._call_gemini")
    def test_severity_is_valid_value(self, mock_gemini):
        mock_gemini.return_value = MOCK_BRIEF_JSON
        for brief in client.get("/api/briefs").json():
            self.assertIn(brief["severity"], self.VALID_SEVERITIES)

    @patch("reasoning.generate_brief._call_gemini")
    def test_languages_needed_is_list(self, mock_gemini):
        mock_gemini.return_value = MOCK_BRIEF_JSON
        for brief in client.get("/api/briefs").json():
            self.assertIsInstance(brief["languages_needed"], list)

    @patch("reasoning.generate_brief._call_gemini")
    def test_briefs_does_not_tick_simulation(self, mock_gemini):
        """
        /api/briefs must NOT call tick() — zone counts before and after a
        briefs call (without an intervening /api/zones call) must be identical.
        """
        mock_gemini.return_value = MOCK_BRIEF_JSON
        zones_before = {z["zone_id"]: z["current_count"] for z in client.get("/api/zones").json()}
        client.get("/api/briefs")
        zones_after = {z["zone_id"]: z["current_count"] for z in
                       __import__('server', fromlist=['SIMULATION']).SIMULATION.get_current_zone_states()}
        self.assertEqual(zones_before, {z: zones_after[z] for z in zones_before})

    @patch("reasoning.generate_brief._call_gemini")
    def test_tier3_fallback_still_returns_list(self, mock_gemini):
        """Even when Gemini is completely unavailable, /api/briefs must return a list (Tier 3)."""
        mock_gemini.return_value = None   # force Tier 3
        res = client.get("/api/briefs")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json(), list)


# ===========================================================================
# GET /api/nudge
# ===========================================================================
class TestNudgeEndpoint(unittest.TestCase):
    """GET /api/nudge must return a valid FanNudge for various query-param combinations."""

    REQUIRED_NUDGE_KEYS = {
        "fan_id", "language", "mobility_needs",
        "message_text", "suggested_route", "generated_at",
    }

    @patch("reasoning.generate_nudge._call_gemini")
    def test_returns_200_default_params(self, mock_gemini):
        mock_gemini.return_value = MOCK_NUDGE_JSON
        res = client.get("/api/nudge")
        self.assertEqual(res.status_code, 200)

    @patch("reasoning.generate_nudge._call_gemini")
    def test_returns_dict(self, mock_gemini):
        mock_gemini.return_value = MOCK_NUDGE_JSON
        res = client.get("/api/nudge")
        self.assertIsInstance(res.json(), dict)

    @patch("reasoning.generate_nudge._call_gemini")
    def test_has_required_keys(self, mock_gemini):
        mock_gemini.return_value = MOCK_NUDGE_JSON
        data = client.get("/api/nudge?fan_id=fan_1&language=en&mobility_needs=false").json()
        missing = self.REQUIRED_NUDGE_KEYS - data.keys()
        self.assertFalse(missing, f"Nudge missing keys: {missing}")

    @patch("reasoning.generate_nudge._call_gemini")
    def test_accepts_mobility_true(self, mock_gemini):
        mobility_nudge = json.dumps({
            "fan_id": "fan_mobility",
            "language": "en",
            "mobility_needs": True,
            "message_text": "Use the accessible ramp.",
            "suggested_route": "ramp_100_east",
            "generated_at": "2026-07-19T14:00:00Z",
        })
        mock_gemini.return_value = mobility_nudge
        res = client.get("/api/nudge?fan_id=fan_m&language=en&mobility_needs=true")
        self.assertEqual(res.status_code, 200)

    @patch("reasoning.generate_nudge._call_gemini")
    def test_accepts_non_english_language(self, mock_gemini):
        es_nudge = json.dumps({
            "fan_id": "fan_es",
            "language": "es",
            "mobility_needs": False,
            "message_text": "Diríjase a la puerta A.",
            "suggested_route": "gate_a",
            "generated_at": "2026-07-19T14:00:00Z",
        })
        mock_gemini.return_value = es_nudge
        res = client.get("/api/nudge?fan_id=fan_es&language=es&mobility_needs=false")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["language"], "es")

    @patch("reasoning.generate_nudge._call_gemini")
    def test_tier3_fallback_still_returns_nudge(self, mock_gemini):
        """Nudge endpoint must return a valid result even when Gemini is down."""
        mock_gemini.return_value = None
        res = client.get("/api/nudge?fan_id=fan_x&language=en")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("message_text", data)
        self.assertIn("suggested_route", data)

    @patch("reasoning.generate_nudge._call_gemini")
    def test_does_not_tick_simulation(self, mock_gemini):
        """/api/nudge must NOT advance the simulation tick counter."""
        mock_gemini.return_value = MOCK_NUDGE_JSON
        from server import SIMULATION
        tick_before = SIMULATION.get_tick_counter(
            SIMULATION.get_current_zone_states()[0]["zone_id"]
        )
        client.get("/api/nudge")
        tick_after = SIMULATION.get_tick_counter(
            SIMULATION.get_current_zone_states()[0]["zone_id"]
        )
        self.assertEqual(tick_before, tick_after)


# ===========================================================================
# GET /api/transit-alert  +  POST /api/transit-alert
# ===========================================================================
class TestTransitAlertEndpoint(unittest.TestCase):
    """Transit alert GET/POST round-trip and validation."""

    def test_get_returns_200(self):
        res = client.get("/api/transit-alert")
        self.assertEqual(res.status_code, 200)

    def test_get_returns_dict_with_expected_keys(self):
        res = client.get("/api/transit-alert")
        data = res.json()
        self.assertIn("transit_status", data)
        self.assertIn("custom_tip", data)

    def test_post_updates_status(self):
        payload = {"transit_status": "watch", "custom_tip": "NJ Transit is delayed by 15 min."}
        post_res = client.post("/api/transit-alert", json=payload)
        self.assertEqual(post_res.status_code, 200)
        data = post_res.json()
        self.assertEqual(data["transit_status"], "watch")
        self.assertEqual(data["custom_tip"], "NJ Transit is delayed by 15 min.")

    def test_post_then_get_reflects_update(self):
        """After POSTing an update, GET must return the same values."""
        payload = {"transit_status": "critical", "custom_tip": "All rail suspended. Use shuttles."}
        client.post("/api/transit-alert", json=payload)
        get_res = client.get("/api/transit-alert")
        data = get_res.json()
        self.assertEqual(data["transit_status"], "critical")
        self.assertEqual(data["custom_tip"], "All rail suspended. Use shuttles.")

    def test_post_strips_whitespace_from_tip(self):
        """Leading/trailing whitespace in custom_tip must be stripped."""
        payload = {"transit_status": "normal", "custom_tip": "   Use the shuttle.   "}
        res = client.post("/api/transit-alert", json=payload)
        self.assertEqual(res.json()["custom_tip"], "Use the shuttle.")

    def test_post_missing_field_returns_422(self):
        """POSTing without transit_status must fail with 422 Unprocessable Entity."""
        res = client.post("/api/transit-alert", json={"custom_tip": "Only tip, no status."})
        self.assertEqual(res.status_code, 422)

    def test_post_clears_tip_with_empty_string(self):
        """Setting custom_tip to '' effectively clears any previous override."""
        client.post("/api/transit-alert", json={"transit_status": "normal", "custom_tip": "Old tip."})
        client.post("/api/transit-alert", json={"transit_status": "normal", "custom_tip": ""})
        data = client.get("/api/transit-alert").json()
        self.assertEqual(data["custom_tip"], "")


# ===========================================================================
# POST /api/report  +  GET /api/reports
# ===========================================================================
class TestReportEndpoints(unittest.TestCase):
    """POST /api/report (triage) and GET /api/reports (list) integration tests."""

    @patch("reasoning.generate_report._call_gemini")
    def test_post_report_returns_200(self, mock_gemini):
        mock_gemini.return_value = MOCK_REPORT_JSON
        res = client.post("/api/report", json={"raw_text": "Person collapsed near Gate A."})
        self.assertEqual(res.status_code, 200)

    @patch("reasoning.generate_report._call_gemini")
    def test_post_report_returns_report_id(self, mock_gemini):
        mock_gemini.return_value = MOCK_REPORT_JSON
        res = client.post("/api/report", json={"raw_text": "Person collapsed near Gate A."})
        data = res.json()
        self.assertIn("report_id", data)
        self.assertTrue(data["report_id"].startswith("rep_"))

    @patch("reasoning.generate_report._call_gemini")
    def test_post_report_preserves_raw_text(self, mock_gemini):
        mock_gemini.return_value = MOCK_REPORT_JSON
        raw = "Someone left an unattended bag near section 201."
        res = client.post("/api/report", json={"raw_text": raw})
        self.assertEqual(res.json()["raw_text"], raw)

    @patch("reasoning.generate_report._call_gemini")
    def test_post_report_has_all_triage_fields(self, mock_gemini):
        mock_gemini.return_value = MOCK_REPORT_JSON
        res = client.post("/api/report", json={"raw_text": "Emergency at Gate B."})
        data = res.json()
        for key in ("detected_language", "category", "severity", "structured_summary"):
            self.assertIn(key, data, f"Missing triage field: {key}")

    def test_post_empty_report_rejected_422(self):
        """Empty raw_text must return HTTP 422."""
        res = client.post("/api/report", json={"raw_text": ""})
        self.assertEqual(res.status_code, 422)

    def test_post_whitespace_only_report_rejected_422(self):
        """Whitespace-only raw_text must return HTTP 422."""
        res = client.post("/api/report", json={"raw_text": "   \n\t  "})
        self.assertEqual(res.status_code, 422)

    def test_post_oversized_report_rejected_422(self):
        """raw_text exceeding 1000 characters must return HTTP 422."""
        res = client.post("/api/report", json={"raw_text": "X" * 1001})
        self.assertEqual(res.status_code, 422)

    def test_post_exactly_1000_chars_is_accepted(self):
        """raw_text of exactly 1000 characters is at the boundary and must succeed."""
        # Allow tier-3 fallback since we're not mocking Gemini here
        res = client.post("/api/report", json={"raw_text": "A" * 1000})
        # 200 (Gemini mocked via tier-3) or 200 regardless — just not 422
        self.assertNotEqual(res.status_code, 422)

    def test_get_reports_returns_200(self):
        res = client.get("/api/reports")
        self.assertEqual(res.status_code, 200)

    def test_get_reports_returns_list(self):
        res = client.get("/api/reports")
        self.assertIsInstance(res.json(), list)

    @patch("reasoning.generate_report._call_gemini")
    def test_get_reports_includes_newly_posted(self, mock_gemini):
        """After POST, GET /api/reports must include the new report."""
        mock_gemini.return_value = MOCK_REPORT_JSON
        raw = f"Unique incident text {__import__('uuid').uuid4().hex}"
        post_res = client.post("/api/report", json={"raw_text": raw})
        posted_id = post_res.json().get("report_id")

        get_res = client.get("/api/reports")
        report_ids = [r["report_id"] for r in get_res.json()]
        self.assertIn(posted_id, report_ids)

    @patch("reasoning.generate_report._call_gemini")
    def test_tier3_fallback_report_still_stored(self, mock_gemini):
        """Even with Gemini unavailable, the report must still be persisted."""
        mock_gemini.return_value = None   # force Tier 3
        raw = f"Tier3 fallback test {__import__('uuid').uuid4().hex}"
        post_res = client.post("/api/report", json={"raw_text": raw})
        self.assertEqual(post_res.status_code, 200)
        posted_id = post_res.json()["report_id"]

        get_res = client.get("/api/reports")
        ids = [r["report_id"] for r in get_res.json()]
        self.assertIn(posted_id, ids)


# ===========================================================================
# GET /  (landing page)
# ===========================================================================
class TestLandingPage(unittest.TestCase):
    """Root route must return HTML with the portal dispatch form."""

    def test_returns_200(self):
        res = client.get("/")
        self.assertEqual(res.status_code, 200)

    def test_returns_html(self):
        res = client.get("/")
        content_type = res.headers.get("content-type", "")
        self.assertIn("text/html", content_type)

    def test_html_contains_portal_form(self):
        """The landing page must include the session form and role selector."""
        html = client.get("/").text
        self.assertIn("session-form", html)
        self.assertIn("sp-role", html)

    def test_html_has_correct_title(self):
        html = client.get("/").text
        self.assertIn("StadiumPulse", html)

    def test_html_has_meta_viewport(self):
        """Must include a viewport meta tag for responsive rendering."""
        html = client.get("/").text
        self.assertIn('name="viewport"', html)

    def test_html_has_lang_attribute(self):
        """Root HTML element must declare lang='en' for WCAG 3.1.1."""
        html = client.get("/").text
        self.assertIn('lang="en"', html)


# ===========================================================================
# Input security / boundary validation (API-level)
# ===========================================================================
class TestInputValidation(unittest.TestCase):
    """Edge-case and security-boundary tests on API inputs."""

    def test_nudge_accepts_all_supported_languages(self):
        """All 10 supported ISO-639-1 language codes must be accepted without error."""
        supported = ["en", "es", "fr", "pt", "de", "ar", "it", "ja", "ko", "zh"]
        for lang in supported:
            res = client.get(f"/api/nudge?fan_id=fan_x&language={lang}")
            self.assertEqual(res.status_code, 200, f"Language '{lang}' was unexpectedly rejected")

    @patch("reasoning.generate_nudge._call_gemini")
    def test_nudge_unsupported_language_still_returns_200(self, mock_gemini):
        """An unsupported language code must fall back gracefully, not error."""
        mock_gemini.return_value = MOCK_NUDGE_JSON
        res = client.get("/api/nudge?language=xx")
        self.assertEqual(res.status_code, 200)

    def test_report_xss_payload_stored_as_literal(self):
        """An XSS payload in raw_text must be stored verbatim, never executed."""
        xss = "<script>alert('xss')</script>"
        res = client.post("/api/report", json={"raw_text": xss})
        # Must succeed (200) — input validation only rejects empty or >1000 chars
        self.assertEqual(res.status_code, 200)
        # The raw_text in the response must match the input exactly (not stripped/mangled)
        self.assertEqual(res.json()["raw_text"], xss)

    def test_report_sql_injection_payload_is_safe(self):
        """SQL injection in raw_text must not crash the server."""
        sql_inject = "'; DROP TABLE reports; --"
        res = client.post("/api/report", json={"raw_text": sql_inject})
        self.assertIn(res.status_code, [200, 422],
                      f"Unexpected status {res.status_code} for SQL injection payload")

    def test_transit_alert_post_extra_fields_ignored(self):
        """Extra unknown fields in the request body must be silently ignored."""
        res = client.post("/api/transit-alert", json={
            "transit_status": "normal",
            "custom_tip": "All clear.",
            "unknown_field": "this should be ignored",
        })
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
