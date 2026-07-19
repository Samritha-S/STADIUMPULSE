import sys
import os
import json
import unittest
from unittest.mock import patch

# Ensure backend modules are on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

from fastapi.testclient import TestClient
from server import app
from reasoning.generate_report import classify_report, _validate_report

class TestVolunteerReportTriage(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.known_zones = ["zone_100_gate_a", "zone_200_gate_c", "zone_300_gate_f"]

    @patch("reasoning.generate_report._call_gemini")
    def test_classify_report_happy_path(self, mock_gemini):
        """Mock Gemini returns a valid triage JSON; classify_report parses it correctly."""
        mock_response = {
            "detected_language": "es",
            "zone_id": "zone_300_gate_f",
            "category": "medical",
            "severity": "critical",
            "structured_summary": "Elderly man passed out near Gate F; medical assistance requested.",
            "generated_at": "2026-07-09T14:30:00Z"
        }
        mock_gemini.return_value = json.dumps(mock_response)

        raw_text = "Hay un señor desmayado en la zona del nivel 300 cerca de la puerta F."
        result = classify_report(raw_text, self.known_zones)

        self.assertEqual(result["detected_language"], "es")
        self.assertEqual(result["zone_id"], "zone_300_gate_f")
        self.assertEqual(result["category"], "medical")
        self.assertEqual(result["severity"], "critical")
        self.assertEqual(result["raw_text"], raw_text)
        self.assertIn("report_id", result)

    @patch("reasoning.generate_report._call_gemini")
    def test_classify_report_tier3_fallback(self, mock_gemini):
        """If Gemini returns None, Tier 3 fallback classifies as medium/other, preserving raw_text."""
        mock_gemini.return_value = None

        raw_text = "Suspicious activity near the south escalator."
        result = classify_report(raw_text, self.known_zones)

        self.assertEqual(result["detected_language"], "en")
        self.assertIsNone(result["zone_id"])
        self.assertEqual(result["category"], "other")
        self.assertEqual(result["severity"], "medium")  # safe default (never low)
        self.assertEqual(result["raw_text"], raw_text)
        self.assertIn("Manual triage needed", result["structured_summary"])
        self.assertIn("report_id", result)

    def test_validate_report(self):
        """Test the schema validation helper functions."""
        valid_payload = {
            "detected_language": "en",
            "zone_id": "zone_200_gate_c",
            "category": "facility",
            "severity": "low",
            "structured_summary": "Elevator broken.",
            "generated_at": "2026-07-09T14:30:00Z"
        }
        self.assertTrue(_validate_report(valid_payload, self.known_zones))

        # Missing keys
        invalid_missing = valid_payload.copy()
        del invalid_missing["category"]
        self.assertFalse(_validate_report(invalid_missing, self.known_zones))

        # Invalid category
        invalid_cat = valid_payload.copy()
        invalid_cat["category"] = "unsupported_category"
        self.assertFalse(_validate_report(invalid_cat, self.known_zones))

        # Zone not in known_zones
        invalid_zone = valid_payload.copy()
        invalid_zone["zone_id"] = "zone_nonexistent"
        self.assertFalse(_validate_report(invalid_zone, self.known_zones))

        # Null zone is allowed
        valid_null_zone = valid_payload.copy()
        valid_null_zone["zone_id"] = None
        self.assertTrue(_validate_report(valid_null_zone, self.known_zones))

    @patch("reasoning.generate_report._call_gemini")
    def test_api_submit_report_success(self, mock_gemini):
        """POST /api/report triages and stores report in memory, GET /api/reports retrieves it."""
        mock_response = {
            "detected_language": "en",
            "zone_id": None,
            "category": "security",
            "severity": "high",
            "structured_summary": "Unattended bag near entrance.",
            "generated_at": "2026-07-09T14:30:00Z"
        }
        mock_gemini.return_value = json.dumps(mock_response)

        # Post report
        post_res = self.client.post("/api/report", json={"raw_text": "Unattended bag near entrance."})
        self.assertEqual(post_res.status_code, 200)
        data = post_res.json()
        self.assertEqual(data["category"], "security")
        self.assertEqual(data["severity"], "high")

        # Get reports list
        get_res = self.client.get("/api/reports")
        self.assertEqual(get_res.status_code, 200)
        reports = get_res.json()
        self.assertGreater(len(reports), 0)
        self.assertEqual(reports[0]["report_id"], data["report_id"])

    def test_api_submit_empty_report_rejection(self):
        """API rejects empty or whitespace-only messages with 422 Unprocessable Entity."""
        res_empty = self.client.post("/api/report", json={"raw_text": ""})
        self.assertEqual(res_empty.status_code, 422)

        res_spaces = self.client.post("/api/report", json={"raw_text": "   "})
        self.assertEqual(res_spaces.status_code, 422)

    def test_api_submit_oversized_report_rejection(self):
        """API rejects messages exceeding 1000 characters with 422 Unprocessable Entity."""
        oversized_text = "A" * 1001
        res = self.client.post("/api/report", json={"raw_text": oversized_text})
        self.assertEqual(res.status_code, 422)


if __name__ == "__main__":
    unittest.main()
