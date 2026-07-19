"""
Tests for the SQLite persistence layer (backend/database.py).

All tests use a temporary file-based database that is created fresh for each
test and deleted on teardown.  No production database is touched.
"""

import os
import sys
import uuid
import unittest
import tempfile
from datetime import datetime, timezone

# Ensure backend modules are on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

import database  # import the module so we can monkey-patch DB_PATH


# ---------------------------------------------------------------------------
# Helper: build a minimal valid report dict for insertion
# ---------------------------------------------------------------------------
def _make_report(
    zone_id="zone_100_gate_a",
    category="medical",
    severity="high",
    raw_text="Person down near section 112.",
    summary="Injured person requiring medical assistance.",
    language="en",
):
    return {
        "report_id": f"rep_{uuid.uuid4().hex[:8]}",
        "raw_text": raw_text,
        "detected_language": language,
        "zone_id": zone_id,
        "category": category,
        "severity": severity,
        "structured_summary": summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


class _TempDbMixin:
    """
    Mixin that redirects database.DB_PATH to a fresh temp file before each
    test and removes it afterwards.  Uses monkey-patching so the module-level
    constant is restored cleanly even if a test raises.
    """

    def setUp(self):
        # Create an empty temp file and point the module at it
        fd, self._tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self._tmp_path)          # remove so SQLite creates it fresh
        self._original_db_path = database.DB_PATH
        database.DB_PATH = self._tmp_path

    def tearDown(self):
        database.DB_PATH = self._original_db_path
        if os.path.exists(self._tmp_path):
            os.unlink(self._tmp_path)


# ===========================================================================
# Schema initialisation
# ===========================================================================
class TestDbInit(_TempDbMixin, unittest.TestCase):
    """db_init() must create the schema and be safely re-callable."""

    def test_creates_reports_table(self):
        """After db_init(), the 'reports' table must exist."""
        database.db_init()
        conn = database.get_db_connection()
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reports'"
        )
        row = cur.fetchone()
        conn.close()
        self.assertIsNotNone(row, "Table 'reports' was not created by db_init()")

    def test_init_is_idempotent(self):
        """Calling db_init() twice must not raise or duplicate the table."""
        database.db_init()
        database.db_init()   # second call must be a no-op
        conn = database.get_db_connection()
        cur = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='reports'"
        )
        count = cur.fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_fresh_init_seeds_data(self):
        """A fresh database must be pre-seeded with at least 1 report by db_init()."""
        database.db_init()
        reports = database.db_get_reports()
        self.assertGreater(len(reports), 0, "db_init() must pre-seed at least one report")

    def test_seeded_reports_have_required_keys(self):
        """Every pre-seeded report must contain all required schema keys."""
        database.db_init()
        required = {
            "report_id", "raw_text", "detected_language",
            "zone_id", "category", "severity",
            "structured_summary", "generated_at",
        }
        for report in database.db_get_reports():
            missing = required - report.keys()
            self.assertFalse(missing, f"Seeded report missing keys: {missing}")


# ===========================================================================
# Save and retrieve
# ===========================================================================
class TestDbSaveReport(_TempDbMixin, unittest.TestCase):
    """db_save_report() must persist a report that is then retrievable."""

    def setUp(self):
        super().setUp()
        database.db_init()

    def test_saved_report_is_retrievable(self):
        """A report saved with db_save_report() must appear in db_get_reports()."""
        report = _make_report()
        database.db_save_report(report)
        results = database.db_get_reports()
        ids = [r["report_id"] for r in results]
        self.assertIn(report["report_id"], ids)

    def test_saved_report_fields_round_trip(self):
        """All fields written must be returned unchanged."""
        report = _make_report(
            zone_id="zone_300_gate_f",
            category="crowd",
            severity="critical",
            raw_text="Critical crush at Gate F.",
            summary="Crush risk at Gate F requiring immediate intervention.",
            language="fr",
        )
        database.db_save_report(report)
        results = database.db_get_reports()
        saved = next(r for r in results if r["report_id"] == report["report_id"])

        self.assertEqual(saved["raw_text"], report["raw_text"])
        self.assertEqual(saved["detected_language"], "fr")
        self.assertEqual(saved["zone_id"], "zone_300_gate_f")
        self.assertEqual(saved["category"], "crowd")
        self.assertEqual(saved["severity"], "critical")
        self.assertEqual(saved["structured_summary"], report["structured_summary"])

    def test_upsert_on_duplicate_report_id(self):
        """Saving a report with an existing report_id must replace it (UPSERT)."""
        report = _make_report(summary="Original summary")
        database.db_save_report(report)

        updated = dict(report, structured_summary="Updated summary")
        database.db_save_report(updated)

        results = database.db_get_reports()
        matches = [r for r in results if r["report_id"] == report["report_id"]]
        self.assertEqual(len(matches), 1, "Duplicate ID should be replaced, not appended")
        self.assertEqual(matches[0]["structured_summary"], "Updated summary")

    def test_null_zone_id_is_stored(self):
        """zone_id is nullable — saving None must not raise and must round-trip as None."""
        report = _make_report(zone_id=None)
        database.db_save_report(report)
        results = database.db_get_reports()
        saved = next(r for r in results if r["report_id"] == report["report_id"])
        self.assertIsNone(saved["zone_id"])

    def test_multiple_distinct_reports_all_stored(self):
        """Saving N distinct reports must result in all N being retrievable."""
        reports = [_make_report(raw_text=f"Incident #{i}") for i in range(5)]
        for r in reports:
            database.db_save_report(r)

        results = database.db_get_reports(limit=50)
        saved_ids = {r["report_id"] for r in results}
        for r in reports:
            self.assertIn(r["report_id"], saved_ids)


# ===========================================================================
# Retrieval ordering and limits
# ===========================================================================
class TestDbGetReports(_TempDbMixin, unittest.TestCase):
    """db_get_reports() must return rows ordered most-recent first and honour the limit."""

    def setUp(self):
        super().setUp()
        database.db_init()

    def _clear_seeded(self):
        """Remove the pre-seeded rows so tests control all rows."""
        conn = database.get_db_connection()
        conn.execute("DELETE FROM reports")
        conn.commit()
        conn.close()

    def test_returns_most_recent_first(self):
        """Reports must be ordered by generated_at DESC (newest first)."""
        self._clear_seeded()
        timestamps = [
            "2026-07-19T10:00:00+00:00",
            "2026-07-19T11:00:00+00:00",
            "2026-07-19T12:00:00+00:00",
        ]
        reports = []
        for ts in timestamps:
            r = _make_report()
            r["generated_at"] = ts
            database.db_save_report(r)
            reports.append(r)

        results = database.db_get_reports(limit=10)
        returned_ts = [r["generated_at"] for r in results]
        self.assertEqual(returned_ts[0][:16], "2026-07-19T12:00",
                         f"Expected newest first, got: {returned_ts}")

    def test_limit_is_respected(self):
        """db_get_reports(limit=N) must return at most N rows."""
        self._clear_seeded()
        for _ in range(10):
            database.db_save_report(_make_report())

        results = database.db_get_reports(limit=3)
        self.assertLessEqual(len(results), 3)

    def test_returns_empty_list_when_no_rows(self):
        """An empty database (after clearing seed) must return []."""
        self._clear_seeded()
        results = database.db_get_reports()
        self.assertEqual(results, [])

    def test_default_limit_is_20(self):
        """Default call returns at most 20 rows even if more are stored."""
        self._clear_seeded()
        for _ in range(25):
            database.db_save_report(_make_report())

        results = database.db_get_reports()    # no explicit limit
        self.assertLessEqual(len(results), 20)


# ===========================================================================
# Security: SQL injection safety
# ===========================================================================
class TestDbSqlInjectionSafety(_TempDbMixin, unittest.TestCase):
    """
    Parameterized queries must prevent SQL injection in user-supplied fields.
    These tests verify the database does not crash and the injected text is
    stored and returned as a literal string, not interpreted as SQL.
    """

    def setUp(self):
        super().setUp()
        database.db_init()

    def _inject_and_retrieve(self, raw_text):
        report = _make_report(raw_text=raw_text)
        database.db_save_report(report)
        results = database.db_get_reports(limit=50)
        saved = next((r for r in results if r["report_id"] == report["report_id"]), None)
        return saved

    def test_single_quote_injection(self):
        """Single-quote SQL injection attempt must be stored as literal text."""
        payload = "'; DROP TABLE reports; --"
        saved = self._inject_and_retrieve(payload)
        self.assertIsNotNone(saved, "Report was not found — possible injection attack succeeded")
        self.assertEqual(saved["raw_text"], payload)

    def test_union_injection(self):
        """UNION-based SQL injection attempt must be stored as literal text."""
        payload = "x' UNION SELECT 1,2,3,4,5,6,7,8 --"
        saved = self._inject_and_retrieve(payload)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["raw_text"], payload)

    def test_null_byte_in_text(self):
        """Null byte in raw_text must not crash the database layer."""
        payload = "normal text\x00more text"
        try:
            saved = self._inject_and_retrieve(payload)
            # If it succeeds, text must be stored intact (or stripped of null byte)
            self.assertIsNotNone(saved)
        except Exception as exc:
            self.fail(f"Null byte in text caused unexpected exception: {exc}")


if __name__ == "__main__":
    unittest.main()
