import sqlite3
import os
from contextlib import contextmanager
from typing import Generator

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume_system.db")

@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager providing an atomic SQLite connection.
    Enforces ACID compliance, foreign keys, and rollbacks on errors.
    """
    conn = sqlite3.connect(DB_PATH, timeout=20.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        conn.execute("BEGIN IMMEDIATE TRANSACTION;")
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_db():
    """Initializes the database schema with composite indexes and strict constraints."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Users table (Authentication, Lockout & Registration Approval Gate)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            plain_password TEXT DEFAULT '',
            role TEXT NOT NULL CHECK(role IN ('student', 'faculty_tpo', 'recruiter', 'admin')),
            full_name TEXT NOT NULL,
            failed_attempts INTEGER DEFAULT 0,
            locked_until TIMESTAMP NULL,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
            status TEXT NOT NULL DEFAULT 'APPROVED' CHECK(status IN ('PENDING_ADMIN_APPROVAL', 'APPROVED', 'REJECTED')),
            department_company TEXT DEFAULT '',
            approval_token TEXT NULL,
            approved_at TIMESTAMP NULL,
            approved_by INTEGER NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (approved_by) REFERENCES users(id) ON DELETE SET NULL
        );
        """)

        # Migration helper for existing databases: ensure new columns exist
        cursor.execute("PRAGMA table_info(users);")
        existing_cols = [r["name"] for r in cursor.fetchall()]
        
        migrations = [
            ("is_active", "INTEGER NOT NULL DEFAULT 1"),
            ("status", "TEXT NOT NULL DEFAULT 'APPROVED'"),
            ("department_company", "TEXT DEFAULT ''"),
            ("approval_token", "TEXT NULL"),
            ("approved_at", "TIMESTAMP NULL"),
            ("approved_by", "INTEGER NULL"),
            ("plain_password", "TEXT DEFAULT ''")
        ]
        
        for col_name, col_def in migrations:
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def};")

        # 2. Students table (Profile, Academic History, Verification Status)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            roll_no TEXT UNIQUE NOT NULL,
            branch TEXT NOT NULL,
            phone TEXT NOT NULL,
            cgpa REAL NOT NULL CHECK(cgpa >= 0.0 AND cgpa <= 10.0),
            tenth_pct REAL NOT NULL CHECK(tenth_pct >= 0.0 AND tenth_pct <= 100.0),
            twelfth_pct REAL NOT NULL CHECK(twelfth_pct >= 0.0 AND twelfth_pct <= 100.0),
            backlogs INTEGER NOT NULL DEFAULT 0 CHECK(backlogs >= 0),
            skills TEXT DEFAULT '',
            marksheet_filename TEXT DEFAULT '',
            is_verified INTEGER DEFAULT 0 CHECK(is_verified IN (0, 1)),
            verified_by INTEGER NULL,
            verification_remarks TEXT DEFAULT '',
            verified_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (verified_by) REFERENCES users(id) ON DELETE SET NULL
        );
        """)

        # 3. Projects table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            technologies TEXT NOT NULL,
            github_url TEXT DEFAULT '',
            live_url TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        """)

        # 4. Internships table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS internships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            company TEXT NOT NULL,
            role TEXT NOT NULL,
            duration_months INTEGER NOT NULL CHECK(duration_months > 0),
            description TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        """)

        # 5. Database Access Requests (Admin-governed temporary table visibility)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS access_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            target_table TEXT NOT NULL,
            reason TEXT NOT NULL,
            requested_duration_minutes INTEGER NOT NULL DEFAULT 60 CHECK(requested_duration_minutes > 0),
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
            reviewed_by INTEGER NULL,
            reviewer_remarks TEXT DEFAULT '',
            token TEXT UNIQUE NULL,
            expires_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
        );
        """)

        # 6. Audit Logs
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL,
            ip_address TEXT DEFAULT '127.0.0.1',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        );
        """)

        # Composite & Unique Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email_role ON users(email, role);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_status_active ON users(status, is_active);")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_approval_token ON users(approval_token) WHERE approval_token IS NOT NULL;")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_students_branch_cgpa ON students(branch, cgpa);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_students_is_verified ON students(is_verified);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_access_requests_user_status ON access_requests(user_id, status);")

def log_audit(conn: sqlite3.Connection, user_id: int | None, action: str, details: str, ip: str = "127.0.0.1"):
    """Helper to log security and system events inside an existing transaction."""
    conn.execute(
        "INSERT INTO audit_logs (user_id, action, details, ip_address) VALUES (?, ?, ?, ?)",
        (user_id, action, details, ip)
    )
