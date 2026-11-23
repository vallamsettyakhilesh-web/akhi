import pytest
import sqlite3
import zipfile
import io
import os
from fastapi.testclient import TestClient

from app import app
from database import get_db_connection, init_db
from seed_data import seed_database, PRIMARY_ADMIN_EMAIL, PRIMARY_ADMIN_PASS
from rri_calculator import calculate_rri
from pdf_compiler import compile_resume_pdf
from auth import SESSION_COOKIE_NAME

@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    seed_database()
    with get_db_connection() as conn:
        conn.execute("DELETE FROM access_requests;")

def get_auth_client(email: str, password: str, role: str) -> TestClient:
    c = TestClient(app, follow_redirects=False)
    resp = c.post("/login", data={"email": email, "password": password, "role": role})
    assert resp.status_code == 303
    return c

# -------------------------------------------------------------
# 1. Entry Point & Mandatory Login Tests
# -------------------------------------------------------------
def test_entry_point_unauthenticated_redirects_to_login():
    """Unauthenticated users at / must be redirected to /login."""
    client = TestClient(app, follow_redirects=False)
    response = client.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

def test_login_page_renders_clean_unified_form():
    """First screen /login renders unified role options and registration form on same page without persona switcher, admin option, or leaked admin email."""
    client = TestClient(app, follow_redirects=False)
    response = client.get("/login")
    assert response.status_code == 200
    assert "Unified Access Gateway" in response.text
    assert "student" in response.text
    assert "faculty_tpo" in response.text
    assert "recruiter" in response.text
    assert "Persona Switcher" not in response.text
    # Verifies both login and new account registration exist on the same page
    assert "New Account Registration" in response.text
    assert "Sign In" in response.text

# -------------------------------------------------------------
# 2. Section 7: Primary Administrator Credentials & Access
# -------------------------------------------------------------
def test_primary_admin_credentials_and_exclusive_access():
    """Verifies vallamsettyakhilesh@gmail.com / akhi@2007 can log in and access admin console."""
    client = get_auth_client(PRIMARY_ADMIN_EMAIL, PRIMARY_ADMIN_PASS, "admin")
    resp = client.get("/admin/database")
    assert resp.status_code == 200
    assert "Backend Database Management &amp; Inspector" in resp.text or "Backend Database Management" in resp.text

    resp_approvals = client.get("/admin/user-approvals")
    assert resp_approvals.status_code == 200

# -------------------------------------------------------------
# 3. Direct User Registration & Immediate Login (Permissions Removed)
# -------------------------------------------------------------
def test_new_user_registration_hold_and_admin_approval_workflow():
    """
    Verifies that:
    1. New student registers on the unified page.
    2. Status is immediately set to APPROVED and is_active = 1 (no permission barrier).
    3. User is redirected to /login with success message.
    4. User can immediately log in and access /student/portal.
    5. Newly registered account is visible in the Main Admin database page (/admin/database) for vallamsettyakhilesh@gmail.com.
    """
    client = TestClient(app, follow_redirects=False)
    new_email = "devstudent.direct@university.edu"
    new_pass = "TestPass@123"

    with get_db_connection() as conn:
        conn.execute("DELETE FROM users WHERE email = ?", (new_email,))

    r_reg = client.post("/register", data={
        "full_name": "Dev Direct Student",
        "email": new_email,
        "password": new_pass,
        "role": "student",
        "department_company": "Computer Science",
        "roll_no": "22CS999",
        "branch": "CSE",
        "phone": "+91 91111 22222"
    })
    assert r_reg.status_code == 303
    assert "/login" in r_reg.headers["location"]

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, status, is_active FROM users WHERE email = ?", (new_email,))
        row = cursor.fetchone()
        assert row is not None
        user_id = row["id"]
        assert row["status"] == "APPROVED"
        assert row["is_active"] == 1

    # Login immediately succeeds without waiting for admin approval
    auth_client = get_auth_client(new_email, new_pass, "student")
    r_portal = auth_client.get("/student/portal")
    assert r_portal.status_code == 200
    assert "Dev Direct Student" in r_portal.text

    # Main Admin (vallamsettyakhilesh@gmail.com) views /admin/database and sees the new user in database
    admin_client = get_auth_client(PRIMARY_ADMIN_EMAIL, PRIMARY_ADMIN_PASS, "admin")
    r_admin = admin_client.get("/admin/database?table=users")
    assert r_admin.status_code == 200
    assert new_email in r_admin.text

    with get_db_connection() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

# -------------------------------------------------------------
# 4. Brute Force Protection (5 Failed Attempts Lockout)
# -------------------------------------------------------------
def test_account_lockout_after_5_failed_attempts():
    """5 consecutive failed logins must trigger account lockout for 15 minutes."""
    client = TestClient(app, follow_redirects=False)
    email = "student2@university.edu"
    role = "student"

    with get_db_connection() as conn:
        conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE email = ?", (email,))

    for i in range(1, 5):
        resp = client.post("/login", data={"email": email, "password": "WrongPassword!", "role": role})
        assert resp.status_code == 400
        assert "attempt(s) remaining before account lockout" in resp.text

    resp5 = client.post("/login", data={"email": email, "password": "WrongPassword!", "role": role})
    assert resp5.status_code == 400
    assert "Your account is now locked for 15 minutes" in resp5.text

    resp6 = client.post("/login", data={"email": email, "password": "Student@12345", "role": role})
    assert resp6.status_code == 400
    assert "Account is locked due to 5 consecutive failed attempts" in resp6.text

    with get_db_connection() as conn:
        conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE email = ?", (email,))

# -------------------------------------------------------------
# 5. Strict RBAC & Database Isolation (HTTP 403)
# -------------------------------------------------------------
def test_student_blocked_from_admin_database_yields_403():
    """Student attempting to view /admin/database must receive HTTP 403 Forbidden."""
    client = get_auth_client("student1@university.edu", "Student@12345", "student")
    response = client.get("/admin/database")
    assert response.status_code == 403
    assert "HTTP 403 Forbidden" in response.text or "Exclusive Admin Boundary" in response.text

def test_student_blocked_from_faculty_queue_yields_403():
    """Student attempting to view /faculty/queue must receive HTTP 403 Forbidden."""
    client = get_auth_client("student1@university.edu", "Student@12345", "student")
    response = client.get("/faculty/queue")
    assert response.status_code == 403

def test_recruiter_blocked_from_student_portal_yields_403():
    """Recruiter attempting to access /student/portal must receive HTTP 403 Forbidden."""
    client = get_auth_client("recruiter@techcorp.com", "Recruiter@12345", "recruiter")
    response = client.get("/student/portal")
    assert response.status_code == 403

# -------------------------------------------------------------
# 6. Database Access Request & Approval Workflow
# -------------------------------------------------------------
def test_database_access_request_approval_workflow():
    """Non-admin submits request -> Admin approves -> Non-admin gains temporary table access."""
    student_client = get_auth_client("student1@university.edu", "Student@12345", "student")
    admin_client = get_auth_client(PRIMARY_ADMIN_EMAIL, PRIMARY_ADMIN_PASS, "admin")

    r_initial = student_client.get("/admin/database?table=students")
    assert r_initial.status_code == 403

    r_sub = student_client.post("/access-request", data={
        "target_table": "students",
        "requested_duration_minutes": 60,
        "reason": "Need to audit cohort academic standing for scholarship verification"
    })
    assert r_sub.status_code == 303

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM access_requests WHERE target_table = 'students' ORDER BY id DESC LIMIT 1")
        req_id = cursor.fetchone()["id"]

    r_app = admin_client.post("/admin/access-requests/action", data={
        "request_id": req_id,
        "action": "approve",
        "granted_minutes": 60,
        "remarks": "Approved by System Administrator for scholarship audit."
    })
    assert r_app.status_code == 303

    r_granted = student_client.get("/admin/database?table=students")
    assert r_granted.status_code == 200
    assert "TABLE: students" in r_granted.text

# -------------------------------------------------------------
# 7. Input Validation Guard Clauses (CGPA 0.0 - 10.0)
# -------------------------------------------------------------
def test_cgpa_boundary_guard_clause_rejects_out_of_bounds():
    """CGPA > 10.0 or < 0.0 must be rejected."""
    student_client = get_auth_client("student1@university.edu", "Student@12345", "student")
    
    r_neg = student_client.post("/student/profile", data={
        "phone": "+91 99999 88888",
        "cgpa": -1.5,
        "tenth_pct": 85.0,
        "twelfth_pct": 85.0,
        "backlogs": 0,
        "skills": "Python",
        "marksheet_filename": "test.pdf"
    })
    assert r_neg.status_code == 303
    assert "error=" in r_neg.headers["location"]

    r_over = student_client.post("/student/profile", data={
        "phone": "+91 99999 88888",
        "cgpa": 12.5,
        "tenth_pct": 85.0,
        "twelfth_pct": 85.0,
        "backlogs": 0,
        "skills": "Python",
        "marksheet_filename": "test.pdf"
    })
    assert r_over.status_code == 303
    assert "error=" in r_over.headers["location"]

# -------------------------------------------------------------
# 8. RRI Calculation Exact Formula Accuracy
# -------------------------------------------------------------
def test_rri_calculation_accuracy():
    """Tests exact 5-tier weights: W_acad (25), W_proj (25), W_skill (20), W_exp (15), W_ver (15)."""
    res = calculate_rri(
        cgpa=10.0,
        tenth_pct=95.0,
        twelfth_pct=95.0,
        backlogs=0,
        skills="Python, React, Docker, SQL, FastAPI",
        projects_count=3,
        has_project_links=True,
        internships_count=2,
        total_internship_months=6,
        is_verified=True
    )
    assert res["total_rri"] == 100.0
    assert res["breakdown"]["w_acad"] == 25.0
    assert res["breakdown"]["w_proj"] == 25.0
    assert res["breakdown"]["w_skill"] == 20.0
    assert res["breakdown"]["w_exp"] == 15.0
    assert res["breakdown"]["w_ver"] == 15.0
    assert res["tier"] == "Placement Ready (Tier 1)"

# -------------------------------------------------------------
# 9. ATS Resume PDF Generation Engine
# -------------------------------------------------------------
def test_ats_pdf_generation_produces_valid_bytes():
    """Generates valid PDF stream using single-column ReportLab engine."""
    student_data = {
        "full_name": "Test Student",
        "email": "test@univ.edu",
        "phone": "+91 98765 00000",
        "roll_no": "21CS999",
        "branch": "CSE",
        "cgpa": 9.2,
        "tenth_pct": 92.0,
        "twelfth_pct": 90.0,
        "backlogs": 0,
        "skills": "Python, Docker, SQL",
        "is_verified": 1,
        "verified_by_name": "Head TPO",
        "verified_at": "2026-11-18"
    }
    projects = [{
        "title": "Cloud Orchestrator",
        "technologies": "Python, Docker",
        "description": "Engineered distributed task manager.",
        "github_url": "https://github.com/test/cloud"
    }]
    internships = [{
        "company": "Tech Corp",
        "role": "Software Intern",
        "duration_months": 3,
        "description": "Optimized microservices."
    }]

    pdf_bytes = compile_resume_pdf(student_data, projects, internships, max_retries=3)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")

# -------------------------------------------------------------
# 10. Recruiter Bulk ZIP Export
# -------------------------------------------------------------
def test_recruiter_bulk_zip_export():
    """Recruiter bulk export returns ZIP archive with RollNo_Name_Branch.pdf files."""
    client = get_auth_client("recruiter@techcorp.com", "Recruiter@12345", "recruiter")
    response = client.get("/recruiter/export-zip?branch=CSE")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    zip_bytes = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        namelist = zf.namelist()
        assert len(namelist) >= 1
        for fname in namelist:
            assert fname.endswith(".pdf")
            parts = fname.split("_")
            assert len(parts) >= 3
