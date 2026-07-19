"""
StadiumPulse — SQLite Database connection and persistence layer.
"""

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

DB_PATH = os.path.join(os.path.dirname(__file__), "stadiumpulse.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    """Initialises the SQLite database schema for reports if they do not exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            report_id TEXT PRIMARY KEY,
            raw_text TEXT NOT NULL,
            detected_language TEXT NOT NULL,
            zone_id TEXT,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            structured_summary TEXT NOT NULL,
            generated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    
    # Check if empty, and pre-seed standard records if so
    cursor.execute("SELECT COUNT(*) FROM reports")
    count = cursor.fetchone()[0]
    
    if count == 0:
        print("[Database] Pre-seeding database with initial reports...", flush=True)
        # Pre-seed reports matching server.py startup seed reports
        seed_data = [
            {
                "report_id": f"rep_{uuid.uuid4().hex[:8]}",
                "raw_text": "There's a man down near section 112, looks like heat exhaustion — he's conscious but very pale and sitting on the floor. We need a medic here now.",
                "detected_language": "en",
                "zone_id": "zone_100_gate_a",
                "category": "medical",
                "severity": "critical",
                "structured_summary": "An older man has collapsed near section 112 suffering from heat exhaustion, requiring immediate medical assistance.",
                "generated_at": datetime.now(timezone.utc).isoformat()
            },
            {
                "report_id": f"rep_{uuid.uuid4().hex[:8]}",
                "raw_text": "La cola en la puerta H está completamente bloqueada, no se puede pasar, hay empuje y la gente está gritando. Necesitamos control aquí urgente.",
                "detected_language": "es",
                "zone_id": "zone_300_gate_h",
                "category": "crowd",
                "severity": "high",
                "structured_summary": "Gate H queue is completely blocked with pushing and shouting crowd, requiring urgent crowd control.",
                "generated_at": datetime.now(timezone.utc).isoformat()
            },
            {
                "report_id": f"rep_{uuid.uuid4().hex[:8]}",
                "raw_text": "Les escaliers mécaniques du niveau 300 côté nord sont arrêtés depuis 20 minutes. Les gens doivent prendre les rampes mais c'est très encombré.",
                "detected_language": "fr",
                "zone_id": "zone_300_gate_f",
                "category": "facility",
                "severity": "medium",
                "structured_summary": "Escalators on level 300 north side are broken down, causing crowd congestion on ramps.",
                "generated_at": datetime.now(timezone.utc).isoformat()
            },
            {
                "report_id": f"rep_{uuid.uuid4().hex[:8]}",
                "raw_text": "Someone left a large unattended backpack under the seat in block 204, row 18. Nobody around it for at least 10 minutes. Should we report it?",
                "detected_language": "en",
                "zone_id": "zone_200_gate_e",
                "category": "security",
                "severity": "high",
                "structured_summary": "A large unattended backpack has been left under a seat in block 204, posing a potential security concern.",
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
        ]
        
        for r in seed_data:
            cursor.execute("""
                INSERT INTO reports (report_id, raw_text, detected_language, zone_id, category, severity, structured_summary, generated_at)
                VALUES (:report_id, :raw_text, :detected_language, :zone_id, :category, :severity, :structured_summary, :generated_at)
            """, r)
        conn.commit()
        
    conn.close()

def db_save_report(report: Dict[str, Any]):
    """Saves an incident report to the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO reports (report_id, raw_text, detected_language, zone_id, category, severity, structured_summary, generated_at)
        VALUES (:report_id, :raw_text, :detected_language, :zone_id, :category, :severity, :structured_summary, :generated_at)
    """, report)
    conn.commit()
    conn.close()

def db_get_reports(limit: int = 20) -> List[Dict[str, Any]]:
    """Retrieves list of recent reports, most recent first."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT report_id, raw_text, detected_language, zone_id, category, severity, structured_summary, generated_at
        FROM reports
        ORDER BY generated_at DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]
