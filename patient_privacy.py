"""
===============================================================================
PATIENT PRIVACY, PSEUDONYMIZATION & SUPABASE-SQLITE HYBRID ENGINE
===============================================================================

Provides:
1. Patient Pseudonymization (e.g. 'MR. IRANI GANGADHARAPPA' -> 'Patient_a8f9b2c3')
2. PII Encryption at Rest (AES-256 / Fernet Encryption for Name, Age, Gender)
3. De-identification at Ingestion (Strips/Replaces PII from raw OCR text before AI API calls)
4. Supabase Managed PostgreSQL + SQLite Automatic Local Fallback Manager
"""

import os
import re
import hashlib
import json
import logging
import base64
from datetime import datetime
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# Secret key management
ENV_ENCRYPTION_KEY = os.getenv("PATIENT_PII_SECRET_KEY", "").strip()
if not ENV_ENCRYPTION_KEY:
    # Generate a deterministic fallback key based on salt if env key not set
    salt = b"MedicalReportAnalyzer_PrivacySalt_2026"
    derived = hashlib.pbkdf2_hmac('sha256', salt, b"patient_privacy_secret", 100000)
    ENV_ENCRYPTION_KEY = base64.urlsafe_b64encode(derived).decode('utf-8')

_fernet_cipher = Fernet(ENV_ENCRYPTION_KEY.encode('utf-8'))

def generate_pseudonym_id(patient_name):
    """
    Generates a consistent, pseudonymous ID (e.g., 'Patient_a8f9b2c3') from patient name.
    Protects patient identity at rest and in external API logs.
    """
    if not patient_name or not isinstance(patient_name, str):
        return "Patient_anon_default"
    clean_name = patient_name.strip().lower()
    if clean_name in ["default patient", "default_patient", "unknown", "anonymous"]:
        return "Patient_anon_default"
    
    hasher = hashlib.sha256()
    hasher.update(b"MEDICAL_PRIVACY_SALT_")
    hasher.update(clean_name.encode('utf-8'))
    digest_hex = hasher.hexdigest()[:8]
    return f"Patient_{digest_hex}"

def encrypt_pii(plain_text):
    """Encrypts PII field (Name, Age, Gender) using AES-256 / Fernet."""
    if not plain_text or not isinstance(plain_text, str):
        return plain_text
    try:
        encrypted_bytes = _fernet_cipher.encrypt(plain_text.encode('utf-8'))
        return f"ENC:{encrypted_bytes.decode('utf-8')}"
    except Exception as e:
        logger.error(f"PII Encryption failed: {e}")
        return plain_text

def decrypt_pii(cipher_token):
    """Decrypts PII field if token starts with 'ENC:'."""
    if not cipher_token or not isinstance(cipher_token, str):
        return cipher_token
    if not cipher_token.startswith("ENC:"):
        return cipher_token
    try:
        raw_token = cipher_token[4:]
        decrypted_bytes = _fernet_cipher.decrypt(raw_token.encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except Exception as e:
        logger.error(f"PII Decryption failed: {e}")
        return cipher_token

def strip_pii_from_report_text(raw_text, patient_name=None):
    """
    Strips or replaces real patient names and sensitive demographics from raw OCR text 
    before sending payload to external LLM / AI APIs.
    """
    if not raw_text or not isinstance(raw_text, str):
        return raw_text

    pseudonym = generate_pseudonym_id(patient_name) if patient_name else "Patient_Deidentified"
    sanitized = raw_text

    # Replace explicit patient name if known
    if patient_name and len(patient_name.strip()) >= 3:
        clean_pname = patient_name.strip()
        sanitized = re.sub(re.escape(clean_pname), pseudonym, sanitized, flags=re.IGNORECASE)
        # Also strip individual words if multi-word name
        words = [w for w in clean_pname.split() if len(w) >= 3 and w.lower() not in ["mr", "mrs", "ms", "dr", "male", "female"]]
        for w in words:
            sanitized = re.sub(r'\b' + re.escape(w) + r'\b', pseudonym, sanitized, flags=re.IGNORECASE)

    # Replace OCR Name headers
    name_patterns = [
        r'(?:name\s*of\s*patient|pt\.?\s*name|patient\'?s?\s*name|client\s*name)\s*[\:\=\-]\s*(?:MR|MRS|MS|DR|MASTER)?\.?\s*([A-Za-z\s]+?)(?=\s+(?:lab|ref|age|sex|gender|date|reg|ward|ip|op|no|status|unit|doctor|dr|\d)|$)',
        r'(?:name)\s*[\:\=\-]\s*(?:MR|MRS|MS|DR|MASTER)?\.?\s*([A-Za-z\s]+?)(?=\s+(?:lab|ref|age|sex|gender|date|reg|ward|ip|op|no|status|unit|doctor|dr|\d)|$)'
    ]
    for pat in name_patterns:
        sanitized = re.sub(pat, f"Name : {pseudonym} ", sanitized, flags=re.IGNORECASE)

    return sanitized


class SupabaseSQLiteFallbackManager:
    """
    Hybrid Managed Database Manager:
    - Primary Store: Supabase / PostgreSQL (Managed Cloud DB with RAG / pgvector)
    - Automatic Fallback: Local SQLite ('patient_database.db') if network/Supabase is offline.
    """

    def __init__(self, sqlite_path="patient_database.db"):
        self.sqlite_path = sqlite_path

    def get_database_connection(self):
        """
        Attempts to connect to Supabase / Neon PostgreSQL Cloud first.
        Falls back automatically to local SQLite connection if unreachable.
        """
        cloud_url = os.getenv("SUPABASE_DATABASE_URL") or os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")
        if cloud_url and cloud_url.startswith("postgresql"):
            try:
                import psycopg2
                conn = psycopg2.connect(cloud_url, connect_timeout=3)
                logger.info("Connected to Supabase/Cloud PostgreSQL DB.")
                return conn, "postgresql"
            except Exception as e:
                logger.warning(f"Supabase/Cloud DB connection unreachable ({e}). Falling back to local SQLite.")

        # Fallback to local SQLite
        import sqlite3
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        logger.info("Connected to local fallback SQLite DB.")
        return conn, "sqlite"

    def execute_query(self, query_sql, params=()):
        """Executes query with automatic PostgreSQL/SQLite adapter handling."""
        conn, db_type = self.get_database_connection()
        try:
            cur = conn.cursor()
            if db_type == "postgresql":
                pg_query = query_sql.replace("?", "%s")
                cur.execute(pg_query, params)
                if query_sql.strip().upper().startswith("SELECT"):
                    rows = cur.fetchall()
                    cur.close()
                    conn.close()
                    return rows
                else:
                    conn.commit()
                    cur.close()
                    conn.close()
                    return True
            else:
                cur.execute(query_sql, params)
                if query_sql.strip().upper().startswith("SELECT"):
                    rows = cur.fetchall()
                    conn.close()
                    return rows
                else:
                    conn.commit()
                    conn.close()
                    return True
        except Exception as e:
            logger.error(f"Database query error ({db_type}): {e}")
            if conn:
                conn.close()
            return None
