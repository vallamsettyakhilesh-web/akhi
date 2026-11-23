import io
import zipfile
import pytest
from starlette.testclient import TestClient
from app import app
from database import get_db_connection
from auth import PRIMARY_ADMIN_EMAIL

PRIMARY_ADMIN_PASS = "akhi@2007"

@pytest.fixture(scope="module", autouse=True)
def clean_audit_users():
    """Ensure clean slate for test users."""
    test_emails = ["audit.student@university.edu", "audit.faculty@university.edu", "audit.recruiter@tech.com"]
    with get_db_connection() as conn:
        for em in test_emails:
            conn.execute("DELETE FROM users WHERE email = ?", (em,))
    yield
    with get_db_connection() as conn:
        for em in test_emails:
            conn.execute("DELETE FROM users WHERE email = ?", (em,))

def get_session_client(email, password, role=None):
    """Helper to authenticate and return a TestClient with valid session cookie."""
    client = TestClient(app, follow_redirects=False)
    data = {"email": email, "password": password}
    if role:
        data["role"] = role
    r = client.post("/login", data=data)
    assert r.status_code == 303, f"Login failed for {email}: {r.text}"
    token = r.cookies.get("srms_session_token")
    assert token is not None, f"No session token cookie set for {email}"
    client.cookies.set("srms_session_token", token)
    return client

# ----------------------------------------------------------------------
# 1. Unauthenticated Route Guardrails (All Protected Pages)
# ----------------------------------------------------------------------
def test_unauthenticated_route_protection():
    client = TestClient(app, follow_redirects=False)
    
    # Root redirects to /login
    r = client.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"

    # Protected dashboards redirect or deny
    for path in ["/student/portal", "/faculty/queue", "/recruiter/console", "/admin/database", "/admin/user-approvals", "/admin/access-requests"]:
        resp = client.get(path)
        assert resp.status_code in (303, 401, 403), f"Unauthenticated access permitted at {path}: {resp.status_code}"

# ----------------------------------------------------------------------
# 2. Registration with Immediate Activation (No Permission Barrier)
# ----------------------------------------------------------------------
def test_student_direct_registration_and_immediate_login():
    client = TestClient(app, follow_redirects=False)
    email = "audit.student@university.edu"
    pwd = "StudentPassword@123"

    # 1. Register new Student
    reg_resp = client.post("/register", data={
        "full_name": "Audit Verification Student",
        "email": email,
        "password": pwd,
        "role": "student",
        "department_company": "Computer Science Dept",
        "roll_no": "22CS_AUDIT_01",
        "branch": "CSE",
        "phone": "+91 98888 12345"
    })
    assert reg_resp.status_code == 303
    assert "/login" in reg_resp.headers["location"]

    # 2. Verify Database record is immediately active
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, is_active, status, role FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        assert row is not None
        assert row["is_active"] == 1
        assert row["status"] == "APPROVED"
        assert row["role"] == "student"

    # 3. Immediate Login without waiting for admin approval
    student_client = get_session_client(email, pwd, "student")
    portal_resp = student_client.get("/student/portal")
    assert portal_resp.status_code == 200
    assert "Audit Verification Student" in portal_resp.text
    assert "22CS_AUDIT_01" in portal_resp.text

# ----------------------------------------------------------------------
# 3. Student Profile, Projects, Internships, RRI & ATS Resume Engine
# ----------------------------------------------------------------------
def test_student_complete_dashboard_operations():
    email = "audit.student@university.edu"
    pwd = "StudentPassword@123"
    client = get_session_client(email, pwd, "student")

    # 1. Update Profile (Academics & Skills)
    prof_resp = client.post("/student/profile", data={
        "phone": "+91 98888 12345",
        "cgpa": 9.45,
        "tenth_pct": 92.5,
        "twelfth_pct": 90.0,
        "backlogs": 0,
        "skills": "Python, FastAPI, Docker, SQL, Kubernetes, Redis",
        "marksheet_filename": "semester_transcripts.pdf"
    }, follow_redirects=True)
    assert prof_resp.status_code == 200
    assert "9.45" in prof_resp.text

    # 2. Add Project
    proj_resp = client.post("/student/project", data={
        "title": "Autonomous Agent Pipeline",
        "technologies": "Python, Redis, Docker, FastAPI",
        "github_url": "https://github.com/audit/pipeline",
        "description": "Architected distributed asynchronous agent pipeline handling 10k events/sec with fault tolerance."
    }, follow_redirects=True)
    assert proj_resp.status_code == 200
    assert "Autonomous Agent Pipeline" in proj_resp.text

    # 3. Add Internship
    intern_resp = client.post("/student/internship", data={
        "company": "Amazon AWS",
        "role": "Cloud Infrastructure Intern",
        "duration_months": 3,
        "description": "Engineered real-time telemetry pipelines and optimized serverless compute clusters."
    }, follow_redirects=True)
    assert intern_resp.status_code == 200
    assert "Amazon AWS" in intern_resp.text

    # 4. View ATS Resume Preview
    preview_resp = client.get("/student/resume/preview")
    assert preview_resp.status_code == 200
    assert "Autonomous Agent Pipeline" in preview_resp.text
    assert "Amazon AWS" in preview_resp.text

    # 5. Compile and Download ATS PDF (Verify bytes not corrupted)
    download_resp = client.get("/student/resume/download")
    assert download_resp.status_code == 200
    assert download_resp.headers["content-type"] == "application/pdf"
    pdf_bytes = download_resp.content
    assert pdf_bytes.startswith(b"%PDF-"), "Generated file is not a valid PDF document"
    assert len(pdf_bytes) > 2000, "PDF byte stream is suspiciously empty"

    # 6. Submit DB Access Request
    req_resp = client.post("/access-request", data={
        "target_table": "students",
        "requested_duration_minutes": 45,
        "reason": "Auditing batch academic index for honors award consideration."
    })
    assert req_resp.status_code == 303

    # 7. Student blocked from Admin Database console
    db_resp = client.get("/admin/database")
    assert db_resp.status_code == 403

# ----------------------------------------------------------------------
# 4. Faculty & TPO Verification Workflow
# ----------------------------------------------------------------------
def test_faculty_verification_workflow():
    client = get_session_client("faculty@university.edu", "Faculty@12345", "faculty_tpo")

    # 1. Access Verification Queue
    q_resp = client.get("/faculty/queue")
    assert q_resp.status_code == 200
    assert "Audit &amp; Credential Verification" in q_resp.text or "Audit & Credential Verification" in q_resp.text

    # 2. Get student ID
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM students WHERE roll_no = '22CS_AUDIT_01'")
        student_id = cursor.fetchone()["id"]

    # 3. Verify student credential claim
    verify_resp = client.post("/faculty/verify", data={
        "student_id": student_id,
        "action": "approve",
        "remarks": "Academic transcripts and identity verified by TPO."
    }, follow_redirects=True)
    assert verify_resp.status_code == 200

    # 4. Confirm verification in DB
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT is_verified, verification_remarks FROM students WHERE id = ?", (student_id,))
        verified_row = cursor.fetchone()
        assert verified_row["is_verified"] == 1
        assert "verified by TPO" in verified_row["verification_remarks"]

    # 5. Faculty blocked from Admin Database Console
    assert client.get("/admin/database").status_code == 403

# ----------------------------------------------------------------------
# 5. Recruiter Talent Console, Multi-Tag Filtering & Bulk ZIP Export
# ----------------------------------------------------------------------
def test_recruiter_console_filters_and_bulk_zip():
    client = get_session_client("recruiter@techcorp.com", "Recruiter@12345", "recruiter")

    # 1. Console Home
    console_resp = client.get("/recruiter/console")
    assert console_resp.status_code == 200
    assert "Talent Search &amp; Bulk Export" in console_resp.text or "Talent Search & Bulk Export" in console_resp.text

    # 2. Filter Queries
    assert client.get("/recruiter/console?branch=CSE").status_code == 200
    assert client.get("/recruiter/console?min_cgpa=8.0").status_code == 200
    assert client.get("/recruiter/console?skill=Python").status_code == 200
    assert client.get("/recruiter/console?verified_only=1").status_code == 200
    assert client.get("/recruiter/console?zero_backlogs=1").status_code == 200

    # 3. Single Candidate Resume Download
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM students WHERE roll_no = '22CS_AUDIT_01'")
        s_id = cursor.fetchone()["id"]

    cand_resp = client.get(f"/recruiter/candidate/{s_id}")
    assert cand_resp.status_code == 200
    assert cand_resp.headers["content-type"] == "application/pdf"
    assert cand_resp.content.startswith(b"%PDF-")

    # 4. Bulk ZIP Export (Must contain valid non-empty PDFs)
    zip_resp = client.get("/recruiter/export-zip?branch=CSE")
    assert zip_resp.status_code == 200
    assert zip_resp.headers["content-type"] == "application/zip"
    
    zip_bytes = zip_resp.content
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        namelist = zf.namelist()
        assert len(namelist) > 0, "Bulk ZIP archive is empty"
        for fname in namelist:
            assert fname.endswith(".pdf")
            extracted = zf.read(fname)
            assert extracted.startswith(b"%PDF-"), f"ZIP entry {fname} is not a valid PDF"

    # 5. Recruiter blocked from Admin Database Console
    assert client.get("/admin/database").status_code == 403

# ----------------------------------------------------------------------
# 6. Primary Administrator: Main Admin Page, Database & Live Registry
# ----------------------------------------------------------------------
def test_primary_admin_exclusive_main_database_console():
    admin_client = get_session_client(PRIMARY_ADMIN_EMAIL, PRIMARY_ADMIN_PASS, "admin")

    # 1. Main Admin Database Page
    admin_resp = admin_client.get("/admin/database")
    assert admin_resp.status_code == 200
    assert "TABLE: users" in admin_resp.text
    assert "Total Registered Users" in admin_resp.text
    # Verify the newly registered student appears in the users database view
    assert "audit.student@university.edu" in admin_resp.text

    # 2. Table Switching
    for tbl in ["students", "projects", "internships", "audit_logs", "access_requests"]:
        r_tbl = admin_client.get(f"/admin/database?table={tbl}")
        assert r_tbl.status_code == 200
        assert f"TABLE: {tbl}" in r_tbl.text

    # 3. SQL Query Execution Console
    sql_resp = admin_client.post("/admin/database/query", data={
        "sql_query": "SELECT email, role, status FROM users WHERE email = 'audit.student@university.edu';"
    })
    assert sql_resp.status_code == 200
    assert "audit.student@university.edu" in sql_resp.text

    # 4. Non-SELECT SQL queries are safely blocked
    blocked_sql = admin_client.post("/admin/database/query", data={
        "sql_query": "DROP TABLE users;"
    })
    assert blocked_sql.status_code == 400
    assert "Only SELECT queries are permitted" in blocked_sql.text

    # 5. Access Requests Queue & Approval
    reqs_resp = admin_client.get("/admin/access-requests")
    assert reqs_resp.status_code == 200

    # 6. Admin can inspect verification queue, recruiter console, and student portal
    assert admin_client.get("/faculty/queue").status_code == 200
    assert admin_client.get("/recruiter/console").status_code == 200
    assert admin_client.get("/student/portal").status_code == 200
    assert admin_client.get("/student/resume/preview").status_code == 200

# ----------------------------------------------------------------------
# 7. Single Admin Exclusivity Barrier
# ----------------------------------------------------------------------
def test_non_head_users_strictly_denied_admin_privileges():
    # Test all non-head users cannot access admin console
    for user_cred in [("student1@university.edu", "Student@12345", "student"),
                      ("faculty@university.edu", "Faculty@12345", "faculty_tpo"),
                      ("recruiter@techcorp.com", "Recruiter@12345", "recruiter")]:
        c = get_session_client(user_cred[0], user_cred[1], user_cred[2])
        r = c.get("/admin/database")
        assert r.status_code == 403
        r_query = c.post("/admin/database/query", data={"sql_query": "SELECT * FROM users;"})
        assert r_query.status_code in (401, 403)
