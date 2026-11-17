"""
database.py — SQLite Database for Medical Report Analyzer
Manages: users, patients, prescriptions, analysis history, patient history
"""

import sqlite3
import hashlib
import os
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "medical_analyzer.db")


def get_db():
    """Get a database connection with row_factory."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize all database tables and ensure schema integrity."""
    conn = get_db()
    try:
        c = conn.cursor()

        # Users table
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                last_login TEXT
            )
        """)

        # Patient profiles table
        c.execute("""
            CREATE TABLE IF NOT EXISTS patient_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                user_id INTEGER,
                name TEXT DEFAULT 'Primary Patient',
                age INTEGER,
                gender TEXT,
                known_conditions TEXT,
                allergies TEXT,
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Analysis history (each upload/analyze event)
        c.execute("""
            CREATE TABLE IF NOT EXISTS analysis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                session_id TEXT,
                analysis_type TEXT,  -- 'report', 'prescription', 'symptoms', 'medicine'
                filename TEXT,
                extracted_text TEXT,
                findings_json TEXT,  -- JSON of biomarker findings
                ddi_json TEXT,       -- JSON of DDI findings
                medicines_json TEXT, -- JSON of extracted medicines
                ai_analysis TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Active medicines (confirmed patient medicines)
        c.execute("""
            CREATE TABLE IF NOT EXISTS active_medicines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id INTEGER,
                canonical_name TEXT NOT NULL,
                brand_name TEXT,
                dosage TEXT,
                frequency TEXT,
                duration TEXT,
                start_date TEXT,
                confirmed INTEGER DEFAULT 0,  -- 1=confirmed, 0=pending
                discontinued INTEGER DEFAULT 0,
                notes TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Lab history (previous lab values)
        c.execute("""
            CREATE TABLE IF NOT EXISTS lab_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id INTEGER,
                test_name TEXT NOT NULL,
                value TEXT NOT NULL,
                unit TEXT,
                status TEXT,
                reference_range TEXT,
                test_date TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Migration / Column verification for backward compatibility
        c.execute("PRAGMA table_info(patient_profiles)")
        prof_cols = {row[1] for row in c.fetchall()}
        if "known_conditions" not in prof_cols:
            c.execute("ALTER TABLE patient_profiles ADD COLUMN known_conditions TEXT")
        if "allergies" not in prof_cols:
            c.execute("ALTER TABLE patient_profiles ADD COLUMN allergies TEXT")
        if "name" not in prof_cols:
            c.execute("ALTER TABLE patient_profiles ADD COLUMN name TEXT DEFAULT 'Primary Patient'")
        if "age" not in prof_cols:
            c.execute("ALTER TABLE patient_profiles ADD COLUMN age INTEGER")
        if "gender" not in prof_cols:
            c.execute("ALTER TABLE patient_profiles ADD COLUMN gender TEXT")

        conn.commit()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database init error: {e}")
        conn.rollback()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session-based operations (no login required, uses browser session ID)
# ---------------------------------------------------------------------------

def save_analysis(session_id: str, analysis_type: str, filename: str,
                  extracted_text: str, findings: list, ddi_data: dict,
                  medicines: list, ai_analysis: str, user_id: int = None) -> int:
    """Save an analysis to history. Returns the analysis ID."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO analysis_history
            (user_id, session_id, analysis_type, filename, extracted_text,
             findings_json, ddi_json, medicines_json, ai_analysis)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, session_id, analysis_type, filename,
            extracted_text[:5000] if extracted_text else "",
            json.dumps(findings),
            json.dumps(ddi_data),
            json.dumps(medicines),
            ai_analysis[:10000] if ai_analysis else ""
        ))
        conn.commit()
        return c.lastrowid
    except Exception as e:
        logger.error(f"Error saving analysis: {e}")
        return -1
    finally:
        conn.close()


def get_analysis_history(session_id: str, limit: int = 10) -> list:
    """Get recent analysis history for a session."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT id, analysis_type, filename, findings_json, ddi_json,
                   medicines_json, created_at
            FROM analysis_history
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (session_id, limit))
        rows = c.fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["findings"] = json.loads(item.get("findings_json") or "[]")
                item["ddi"] = json.loads(item.get("ddi_json") or "{}")
                item["medicines"] = json.loads(item.get("medicines_json") or "[]")
            except Exception:
                item["findings"] = []
                item["ddi"] = {}
                item["medicines"] = []
            result.append(item)
        return result
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return []
    finally:
        conn.close()


def save_active_medicines(session_id: str, medicines: list, user_id: int = None):
    """Add medicines to active medicines list (pending confirmation)."""
    conn = get_db()
    try:
        c = conn.cursor()
        for med in medicines:
            # Avoid duplicates
            c.execute("""
                SELECT id FROM active_medicines
                WHERE session_id=? AND canonical_name=? AND discontinued=0
            """, (session_id, med.get("canonical_name", "")))
            if not c.fetchone():
                c.execute("""
                    INSERT INTO active_medicines
                    (session_id, user_id, canonical_name, brand_name, dosage, frequency, duration)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    session_id, user_id,
                    med.get("canonical_name", ""),
                    med.get("brand_name", ""),
                    med.get("dosage", ""),
                    med.get("frequency", ""),
                    med.get("duration", "")
                ))
        conn.commit()
    except Exception as e:
        logger.error(f"Error saving active medicines: {e}")
    finally:
        conn.close()


def get_active_medicines(session_id: str) -> list:
    """Get active (non-discontinued) medicines for a session."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT canonical_name, brand_name, dosage, frequency, duration, start_date, confirmed
            FROM active_medicines
            WHERE session_id=? AND discontinued=0
            ORDER BY created_at DESC
        """, (session_id,))
        return [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching active medicines: {e}")
        return []
    finally:
        conn.close()


def save_lab_results(session_id: str, findings: list, user_id: int = None):
    """Save lab results to history."""
    conn = get_db()
    try:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        for f in findings:
            c.execute("""
                INSERT INTO lab_history
                (session_id, user_id, test_name, value, unit, status, reference_range, test_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id, user_id,
                f.get("test", ""),
                str(f.get("value", "")),
                f.get("unit", ""),
                f.get("status", ""),
                f.get("reference", ""),
                today
            ))
        conn.commit()
    except Exception as e:
        logger.error(f"Error saving lab results: {e}")
    finally:
        conn.close()


def get_lab_history(session_id: str, limit: int = 50) -> list:
    """Get previous lab results for a session."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT test_name, value, unit, status, reference_range, test_date
            FROM lab_history
            WHERE session_id=?
            ORDER BY test_date DESC, created_at DESC
            LIMIT ?
        """, (session_id, limit))
        return [dict(row) for row in c.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching lab history: {e}")
        return []
    finally:
        conn.close()


def get_patient_profile(session_id: str) -> dict:
    """Retrieve patient profile information."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT name, age, gender, known_conditions, allergies, updated_at
            FROM patient_profiles
            WHERE session_id = ?
        """, (session_id,))
        row = c.fetchone()
        if row:
            return dict(row)
        return {
            "name": "Primary Patient",
            "age": "",
            "gender": "unknown",
            "known_conditions": "",
            "allergies": "",
            "updated_at": ""
        }
    except Exception as e:
        logger.error(f"Error fetching patient profile: {e}")
        return {"name": "Primary Patient", "age": "", "gender": "unknown", "known_conditions": "", "allergies": ""}
    finally:
        conn.close()


def save_patient_profile(session_id: str, name: str = "Primary Patient", age: int = None,
                         gender: str = "unknown", known_conditions: str = "",
                         allergies: str = "", user_id: int = None) -> bool:
    """Create or update patient profile."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO patient_profiles (session_id, user_id, name, age, gender, known_conditions, allergies, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(session_id) DO UPDATE SET
                name=excluded.name,
                age=excluded.age,
                gender=excluded.gender,
                known_conditions=excluded.known_conditions,
                allergies=excluded.allergies,
                updated_at=datetime('now')
        """, (session_id, user_id, name, age, gender, known_conditions, allergies))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error saving patient profile: {e}")
        return False
    finally:
        conn.close()


def set_medicine_status(session_id: str, canonical_name: str, confirmed: int = 1, discontinued: int = 0) -> bool:
    """Update active medicine confirmation or discontinuation status."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            UPDATE active_medicines
            SET confirmed = ?, discontinued = ?
            WHERE session_id = ? AND canonical_name = ?
        """, (confirmed, discontinued, session_id, canonical_name))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating medicine status: {e}")
        return False
    finally:
        conn.close()


def get_session_context(session_id: str) -> dict:
    """Get complete session context for RAG chatbot."""
    return {
        "profile": get_patient_profile(session_id),
        "active_medicines": get_active_medicines(session_id),
        "lab_history": get_lab_history(session_id, limit=20),
        "analysis_history": get_analysis_history(session_id, limit=5)
    }
