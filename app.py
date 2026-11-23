import os
import io
import zipfile
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import get_db_connection, log_audit, init_db
from auth import (
    authenticate_user,
    create_session_token,
    get_current_user,
    login_required,
    role_required,
    has_active_table_access,
    hash_password,
    SESSION_COOKIE_NAME,
    ADMIN_EMAIL,
    HEAD_ADMIN_EMAIL
)
from models import (
    ProfileUpdateRequest,
    ProjectCreateRequest,
    InternshipCreateRequest,
    VerificationActionRequest,
    DatabaseAccessRequestCreate,
    DatabaseAccessActionRequest,
    RegisterRequest,
    UserApprovalActionRequest
)
from rri_calculator import calculate_rri
from pdf_compiler import compile_resume_pdf
from seed_data import seed_database
from email_service import (
    send_admin_registration_notification,
    send_user_approval_confirmation,
    PRIMARY_ADMIN_EMAIL
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_database()
    yield

# Application Initialization
app = FastAPI(
    title="Student Resume Management System (SRMS)",
    version="1.0.0",
    lifespan=lifespan
)

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ---------------------------------------------------------
# Custom Exception Handlers (Security & HTTP 403 Isolation)
# ---------------------------------------------------------
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    user = get_current_user(request)
    if exc.status_code == status.HTTP_403_FORBIDDEN:
        return templates.TemplateResponse(
            request=request,
            name="403.html",
            context={
                "user": user,
                "detail": exc.detail,
                "path": request.url.path,
            },
            status_code=403,
        )
    elif exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return RedirectResponse(url="/login?error=" + exc.detail, status_code=303)
    
    return HTMLResponse(content=f"<h3>Error {exc.status_code}</h3><p>{exc.detail}</p>", status_code=exc.status_code)

# ---------------------------------------------------------
# 1. Mandatory Unified Entry Point: Login & Registration
# ---------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def entry_point(request: Request):
    """
    Mandatory Entry Point:
    Opens directly to clean, secure unified gateway as the absolute first screen.
    """
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    role = user.get("role")
    if role == "student":
        return RedirectResponse(url="/student/portal", status_code=303)
    elif role == "faculty_tpo":
        return RedirectResponse(url="/faculty/queue", status_code=303)
    elif role == "recruiter":
        return RedirectResponse(url="/recruiter/console", status_code=303)
    elif role == "admin":
        return RedirectResponse(url="/admin/database", status_code=303)
    return RedirectResponse(url="/login", status_code=303)

@app.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    tab: Optional[str] = "login",
    error: Optional[str] = None,
    success: Optional[str] = None
):
    """
    Unified Single Page housing both Primary Admin Login and New Account Registration.
    """
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "user": None,
            "active_tab": tab,
            "error": error,
            "success": success
        }
    )

@app.get("/register", response_class=HTMLResponse)
async def register_page_redirect(request: Request, error: Optional[str] = None):
    """Redirects /register directly into the registration tab of the unified login page."""
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=303)
    err_param = f"&error={error}" if error else ""
    return RedirectResponse(url=f"/login?tab=register{err_param}", status_code=303)

@app.post("/login")
async def process_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    role: Optional[str] = Form(None),
):
    ip = request.client.host if request.client else "127.0.0.1"
    success, user_data, err_msg = authenticate_user(email, password, role, ip)
    
    if not success or not user_data:
        if "PENDING_ADMIN_APPROVAL" in err_msg or "Please wait until your access request is approved" in err_msg:
            return RedirectResponse(url=f"/registration-pending?email={email.strip().lower()}", status_code=303)

        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "user": None,
                "active_tab": "login",
                "error": err_msg,
                "success": None
            },
            status_code=400
        )

    # Issue encrypted/signed session token
    session_data = {
        "user_id": user_data["id"],
        "email": user_data["email"],
        "role": user_data["role"],
        "full_name": user_data["full_name"],
    }
    token = create_session_token(session_data, expires_delta=timedelta(hours=8))
    
    redirect_target = "/"
    if user_data["role"] == "student":
        redirect_target = "/student/portal"
    elif user_data["role"] == "faculty_tpo":
        redirect_target = "/faculty/queue"
    elif user_data["role"] == "recruiter":
        redirect_target = "/recruiter/console"
    elif user_data["role"] == "admin":
        redirect_target = "/admin/database"

    response = RedirectResponse(url=redirect_target, status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=28800,
    )
    return response

@app.post("/register")
async def process_registration(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    department_company: str = Form(default=""),
    roll_no: str = Form(default=""),
    branch: str = Form(default=""),
    phone: str = Form(default=""),
):
    try:
        validated = RegisterRequest(
            full_name=full_name,
            email=email.strip().lower(),
            password=password,
            role=role,
            department_company=department_company,
            roll_no=roll_no,
            branch=branch,
            phone=phone
        )
    except Exception as val_err:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"user": None, "active_tab": "register", "error": str(val_err)},
            status_code=400
        )

    clean_email = validated.email
    approval_token = secrets.token_urlsafe(32)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = ?", (clean_email,))
        if cursor.fetchone():
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={"user": None, "active_tab": "register", "error": f"An account with email {clean_email} already exists. Please log in."},
                status_code=400
            )

        cursor.execute("""
            INSERT INTO users (
                email, password_hash, plain_password, role, full_name, is_active, status, 
                department_company, approval_token
            ) VALUES (?, ?, ?, ?, ?, 1, 'APPROVED', ?, ?)
        """, (
            clean_email,
            hash_password(validated.password),
            validated.password,
            validated.role,
            validated.full_name,
            validated.department_company,
            approval_token
        ))
        new_user_id = cursor.lastrowid

        if validated.role == "student":
            cursor.execute("""
                INSERT INTO students (
                    user_id, roll_no, branch, phone, cgpa, tenth_pct, twelfth_pct,
                    backlogs, skills, marksheet_filename, is_verified
                ) VALUES (?, ?, ?, ?, 0.0, 0.0, 0.0, 0, '', '', 0)
            """, (
                new_user_id,
                validated.roll_no or f"PENDING-{new_user_id}",
                validated.branch or "CSE",
                validated.phone or "Unspecified"
            ))

        log_audit(
            conn,
            new_user_id,
            "REGISTRATION_ACTIVE",
            f"New {validated.role} registration active immediately ({clean_email})"
        )

    applicant_data = {
        "id": new_user_id,
        "full_name": validated.full_name,
        "email": clean_email,
        "role": validated.role,
        "department_company": validated.department_company
    }
    host_base = f"{request.url.scheme}://{request.url.netloc}"
    try:
        send_admin_registration_notification(applicant_data, approval_token, host_base)
    except Exception:
        pass

    return RedirectResponse(url=f"/login?success=Account+registered+successfully!+You+can+now+sign+in+directly.&reg_email={clean_email}", status_code=303)

@app.get("/registration-pending", response_class=HTMLResponse)
async def registration_pending_page(request: Request, email: Optional[str] = None):
    applicant = None
    if email:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, full_name, email, role, department_company, status, is_active
                FROM users WHERE email = ?
            """, (email.strip().lower(),))
            row = cursor.fetchone()
            if row:
                applicant = dict(row)

    return templates.TemplateResponse(
        request=request,
        name="registration_pending.html",
        context={"user": None, "applicant": applicant}
    )

@app.get("/logout")
async def logout(request: Request):
    user = get_current_user(request)
    if user:
        with get_db_connection() as conn:
            log_audit(conn, user.get("user_id"), "LOGOUT", "User signed out")
    response = RedirectResponse(url="/login?success=You+have+been+securely+signed+out.", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response

# ---------------------------------------------------------
# 1c. Admin User Approvals Queue & Direct Email Actions
# ---------------------------------------------------------
@app.get("/admin/user-approvals", response_class=HTMLResponse)
async def admin_user_approvals_queue(
    request: Request,
    current_user: dict = Depends(role_required(["admin"])),
    success: Optional[str] = None,
    error: Optional[str] = None
):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, email, role, full_name, is_active, status, department_company, created_at, approved_at
            FROM users
            ORDER BY (status = 'PENDING_ADMIN_APPROVAL') DESC, id DESC
        """)
        users = [dict(r) for r in cursor.fetchall()]

    return templates.TemplateResponse(
        request=request,
        name="admin_user_approvals.html",
        context={
            "user": current_user,
            "users": users,
            "active_page": "user_approvals",
            "success": success,
            "error": error
        }
    )

@app.post("/admin/user-approvals/action")
async def process_user_approval_action(
    request: Request,
    user_id: int = Form(...),
    action: str = Form(...),
    remarks: str = Form(default=""),
    current_user: dict = Depends(role_required(["admin"])),
):
    try:
        validated = UserApprovalActionRequest(
            user_id=user_id,
            action=action,
            remarks=remarks
        )
    except Exception as val_err:
        return RedirectResponse(url=f"/admin/user-approvals?error={val_err}", status_code=303)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, full_name, role, status FROM users WHERE id = ?", (validated.user_id,))
        target_user = cursor.fetchone()
        if not target_user:
            raise HTTPException(status_code=404, detail="Target applicant account not found.")

        target_dict = dict(target_user)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        if validated.action == "approve":
            cursor.execute("""
                UPDATE users 
                SET status = 'APPROVED', is_active = 1, approved_by = ?, approved_at = ?, approval_token = NULL
                WHERE id = ?
            """, (current_user["user_id"], now_str, validated.user_id))
            
            log_audit(
                conn,
                current_user["user_id"],
                "USER_REGISTRATION_APPROVED",
                f"Admin approved user ID {validated.user_id} ({target_dict['email']})"
            )
            
            host_base = f"{request.url.scheme}://{request.url.netloc}"
            send_user_approval_confirmation(target_dict["email"], target_dict["full_name"], target_dict["role"], host_base)
            msg = f"User+{target_dict['email']}+has+been+officially+APPROVED+and+notified."
        else:
            cursor.execute("""
                UPDATE users 
                SET status = 'REJECTED', is_active = 0, approved_by = ?, approved_at = ?, approval_token = NULL
                WHERE id = ?
            """, (current_user["user_id"], now_str, validated.user_id))
            
            log_audit(
                conn,
                current_user["user_id"],
                "USER_REGISTRATION_REJECTED",
                f"Admin rejected user ID {validated.user_id} ({target_dict['email']})"
            )
            msg = f"User+{target_dict['email']}+registration+has+been+REJECTED."

    return RedirectResponse(url=f"/admin/user-approvals?success={msg}", status_code=303)

@app.get("/admin/users/email-action", response_class=HTMLResponse)
async def process_email_action_link(
    request: Request,
    token: str,
    action: str
):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, email, full_name, role, status 
            FROM users WHERE approval_token = ?
        """, (token,))
        user_row = cursor.fetchone()

        if not user_row:
            return HTMLResponse(
                content="""
                <div style="font-family:sans-serif; max-width:600px; margin:40px auto; padding:24px; border:1px solid #e2e8f0; border-radius:12px;">
                    <h3 style="color:#e11d48;">Invalid or Expired Approval Token</h3>
                    <p>This registration request has already been processed or the token is invalid.</p>
                    <a href="/login">Return to SRMS Portal</a>
                </div>
                """,
                status_code=400
            )

        target_dict = dict(user_row)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        if action.lower() == "approve":
            cursor.execute("""
                UPDATE users 
                SET status = 'APPROVED', is_active = 1, approved_at = ?, approval_token = NULL
                WHERE id = ?
            """, (now_str, target_dict["id"]))
            
            log_audit(conn, target_dict["id"], "EMAIL_DIRECT_APPROVAL", f"Approved via secure email token for {target_dict['email']}")
            
            host_base = f"{request.url.scheme}://{request.url.netloc}"
            send_user_approval_confirmation(target_dict["email"], target_dict["full_name"], target_dict["role"], host_base)
            
            return HTMLResponse(
                content=f"""
                <div style="font-family:sans-serif; max-width:600px; margin:40px auto; padding:32px; border:1px solid #10b981; border-radius:12px; background:#f0fdf4;">
                    <h2 style="color:#065f46; margin-top:0;">Registration Approved Successfully</h2>
                    <p style="color:#166534;">The applicant account for <strong>{target_dict['full_name']}</strong> ({target_dict['email']}) has been activated as <strong>{target_dict['role'].upper()}</strong>.</p>
                    <p style="color:#166534;">A confirmation email has been dispatched to the user unlocking their institutional dashboard.</p>
                    <div style="margin-top:20px;">
                        <a href="/login" style="background:#0f172a; color:#fff; padding:10px 18px; border-radius:6px; text-decoration:none; font-size:13px; font-weight:bold;">Go to SRMS Dashboard</a>
                    </div>
                </div>
                """
            )
        else:
            cursor.execute("""
                UPDATE users 
                SET status = 'REJECTED', is_active = 0, approved_at = ?, approval_token = NULL
                WHERE id = ?
            """, (now_str, target_dict["id"]))
            
            log_audit(conn, target_dict["id"], "EMAIL_DIRECT_REJECTION", f"Rejected via secure email token for {target_dict['email']}")
            
            return HTMLResponse(
                content=f"""
                <div style="font-family:sans-serif; max-width:600px; margin:40px auto; padding:32px; border:1px solid #f43f5e; border-radius:12px; background:#fff1f2;">
                    <h2 style="color:#9f1239; margin-top:0;">Registration Rejected</h2>
                    <p style="color:#be123c;">The applicant account for <strong>{target_dict['full_name']}</strong> ({target_dict['email']}) has been marked as REJECTED.</p>
                    <div style="margin-top:20px;">
                        <a href="/login" style="background:#0f172a; color:#fff; padding:10px 18px; border-radius:6px; text-decoration:none; font-size:13px; font-weight:bold;">Return to Login</a>
                    </div>
                </div>
                """
            )

# ---------------------------------------------------------
# 2. Student Portal & Profile Builder (MOD-02)
# ---------------------------------------------------------
@app.get("/student/portal", response_class=HTMLResponse)
async def student_portal(
    request: Request,
    current_user: dict = Depends(role_required(["student", "admin"])),
    success: Optional[str] = None,
    error: Optional[str] = None
):
    user_id = current_user["user_id"]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        if current_user["role"] == "admin":
            cursor.execute("""
                SELECT s.*, u.full_name, u.email, v.full_name as verified_by_name
                FROM students s
                JOIN users u ON s.user_id = u.id
                LEFT JOIN users v ON s.verified_by = v.id
                LIMIT 1
            """)
        else:
            cursor.execute("""
                SELECT s.*, u.full_name, u.email, v.full_name as verified_by_name
                FROM students s
                JOIN users u ON s.user_id = u.id
                LEFT JOIN users v ON s.verified_by = v.id
                WHERE s.user_id = ?
            """, (user_id,))
            
        student_row = cursor.fetchone()
        if not student_row:
            raise HTTPException(status_code=404, detail="Student record not found.")
        
        student = dict(student_row)
        student_id = student["id"]

        cursor.execute("SELECT * FROM projects WHERE student_id = ? ORDER BY id DESC", (student_id,))
        projects = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM internships WHERE student_id = ? ORDER BY id DESC", (student_id,))
        internships = [dict(r) for r in cursor.fetchall()]

    total_months = sum(i["duration_months"] for i in internships)
    has_links = any(bool(p["github_url"] or p["live_url"]) for p in projects)
    
    rri = calculate_rri(
        cgpa=student["cgpa"],
        tenth_pct=student["tenth_pct"],
        twelfth_pct=student["twelfth_pct"],
        backlogs=student["backlogs"],
        skills=student["skills"],
        projects_count=len(projects),
        has_project_links=has_links,
        internships_count=len(internships),
        total_internship_months=total_months,
        is_verified=bool(student["is_verified"])
    )

    return templates.TemplateResponse(
        request=request,
        name="student_portal.html",
        context={
            "user": current_user,
            "student": student,
            "projects": projects,
            "internships": internships,
            "rri": rri,
            "active_page": "student_portal",
            "success": success,
            "error": error
        }
    )

@app.post("/student/profile")
async def update_student_profile(
    request: Request,
    phone: str = Form(...),
    cgpa: float = Form(...),
    tenth_pct: float = Form(...),
    twelfth_pct: float = Form(...),
    backlogs: int = Form(...),
    skills: str = Form(default=""),
    marksheet_filename: str = Form(default=""),
    current_user: dict = Depends(role_required(["student", "admin"])),
):
    try:
        validated = ProfileUpdateRequest(
            phone=phone,
            cgpa=cgpa,
            tenth_pct=tenth_pct,
            twelfth_pct=twelfth_pct,
            backlogs=backlogs,
            skills=skills,
            marksheet_filename=marksheet_filename
        )
    except Exception as val_err:
        return RedirectResponse(url=f"/student/portal?error={val_err}", status_code=303)

    user_id = current_user["user_id"]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM students WHERE user_id = ?", (user_id,))
        s_row = cursor.fetchone()
        if not s_row:
            if current_user["role"] == "admin":
                cursor.execute("SELECT id FROM students LIMIT 1")
                s_row = cursor.fetchone()
            else:
                raise HTTPException(status_code=404, detail="Student profile not found.")
        
        target_student_id = s_row["id"]
        cursor.execute("""
            UPDATE students 
            SET phone = ?, cgpa = ?, tenth_pct = ?, twelfth_pct = ?, backlogs = ?, 
                skills = ?, marksheet_filename = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            validated.phone, validated.cgpa, validated.tenth_pct, validated.twelfth_pct,
            validated.backlogs, validated.skills, validated.marksheet_filename, target_student_id
        ))
        log_audit(conn, user_id, "PROFILE_UPDATED", f"Updated student profile ID {target_student_id}")

    return RedirectResponse(url="/student/portal?success=Profile+updated+successfully.+RRI+recalculated.", status_code=303)

@app.post("/student/project")
async def add_student_project(
    request: Request,
    title: str = Form(...),
    technologies: str = Form(...),
    description: str = Form(...),
    github_url: str = Form(default=""),
    live_url: str = Form(default=""),
    current_user: dict = Depends(role_required(["student", "admin"])),
):
    try:
        validated = ProjectCreateRequest(
            title=title,
            technologies=technologies,
            description=description,
            github_url=github_url,
            live_url=live_url
        )
    except Exception as val_err:
        return RedirectResponse(url=f"/student/portal?error={val_err}", status_code=303)

    user_id = current_user["user_id"]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM students WHERE user_id = ?", (user_id,))
        s_row = cursor.fetchone()
        if not s_row:
            if current_user["role"] == "admin":
                cursor.execute("SELECT id FROM students LIMIT 1")
                s_row = cursor.fetchone()
            else:
                raise HTTPException(status_code=404, detail="Student record not found.")

        target_student_id = s_row["id"]
        cursor.execute("""
            INSERT INTO projects (student_id, title, technologies, description, github_url, live_url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (target_student_id, validated.title, validated.technologies, validated.description, validated.github_url, validated.live_url))
        log_audit(conn, user_id, "PROJECT_ADDED", f"Added project '{validated.title}' to student ID {target_student_id}")

    return RedirectResponse(url="/student/portal?success=Project+added+successfully.", status_code=303)

@app.post("/student/internship")
async def add_student_internship(
    request: Request,
    company: str = Form(...),
    role: str = Form(...),
    duration_months: int = Form(...),
    description: str = Form(...),
    current_user: dict = Depends(role_required(["student", "admin"])),
):
    try:
        validated = InternshipCreateRequest(
            company=company,
            role=role,
            duration_months=duration_months,
            description=description
        )
    except Exception as val_err:
        return RedirectResponse(url=f"/student/portal?error={val_err}", status_code=303)

    user_id = current_user["user_id"]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM students WHERE user_id = ?", (user_id,))
        s_row = cursor.fetchone()
        if not s_row:
            if current_user["role"] == "admin":
                cursor.execute("SELECT id FROM students LIMIT 1")
                s_row = cursor.fetchone()
            else:
                raise HTTPException(status_code=404, detail="Student record not found.")

        target_student_id = s_row["id"]
        cursor.execute("""
            INSERT INTO internships (student_id, company, role, duration_months, description)
            VALUES (?, ?, ?, ?, ?)
        """, (target_student_id, validated.company, validated.role, validated.duration_months, validated.description))
        log_audit(conn, user_id, "INTERNSHIP_ADDED", f"Added internship at {validated.company} for student ID {target_student_id}")

    return RedirectResponse(url="/student/portal?success=Internship+record+saved.", status_code=303)

# ---------------------------------------------------------
# 3. ATS Resume Compiler Engine (MOD-04)
# ---------------------------------------------------------
@app.get("/student/resume/preview", response_class=HTMLResponse)
async def resume_preview(
    request: Request,
    current_user: dict = Depends(role_required(["student", "admin"]))
):
    user_id = current_user["user_id"]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if current_user["role"] == "admin":
            cursor.execute("""
                SELECT s.*, u.full_name, u.email, v.full_name as verified_by_name
                FROM students s
                JOIN users u ON s.user_id = u.id
                LEFT JOIN users v ON s.verified_by = v.id
                LIMIT 1
            """)
        else:
            cursor.execute("""
                SELECT s.*, u.full_name, u.email, v.full_name as verified_by_name
                FROM students s
                JOIN users u ON s.user_id = u.id
                LEFT JOIN users v ON s.verified_by = v.id
                WHERE s.user_id = ?
            """, (user_id,))
            
        student_row = cursor.fetchone()
        if not student_row:
            raise HTTPException(status_code=404, detail="Student record not found.")
        
        student = dict(student_row)
        student_id = student["id"]

        cursor.execute("SELECT * FROM projects WHERE student_id = ? ORDER BY id DESC", (student_id,))
        projects = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM internships WHERE student_id = ? ORDER BY id DESC", (student_id,))
        internships = [dict(r) for r in cursor.fetchall()]

    return templates.TemplateResponse(
        request=request,
        name="ats_compiler.html",
        context={
            "user": current_user,
            "student": student,
            "projects": projects,
            "internships": internships,
            "active_page": "resume_preview"
        }
    )

@app.get("/student/resume/download")
async def download_resume_pdf(
    request: Request,
    current_user: dict = Depends(role_required(["student", "admin"]))
):
    user_id = current_user["user_id"]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if current_user["role"] == "admin":
            cursor.execute("""
                SELECT s.*, u.full_name, u.email, v.full_name as verified_by_name
                FROM students s
                JOIN users u ON s.user_id = u.id
                LEFT JOIN users v ON s.verified_by = v.id
                LIMIT 1
            """)
        else:
            cursor.execute("""
                SELECT s.*, u.full_name, u.email, v.full_name as verified_by_name
                FROM students s
                JOIN users u ON s.user_id = u.id
                LEFT JOIN users v ON s.verified_by = v.id
                WHERE s.user_id = ?
            """, (user_id,))
            
        student_row = cursor.fetchone()
        if not student_row:
            raise HTTPException(status_code=404, detail="Student record not found.")
        
        student = dict(student_row)
        student_id = student["id"]

        cursor.execute("SELECT * FROM projects WHERE student_id = ? ORDER BY id DESC", (student_id,))
        projects = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM internships WHERE student_id = ? ORDER BY id DESC", (student_id,))
        internships = [dict(r) for r in cursor.fetchall()]

    pdf_bytes = compile_resume_pdf(student, projects, internships, max_retries=3)
    
    filename = f"{student['roll_no']}_{student['full_name'].replace(' ', '_')}_{student['branch']}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ---------------------------------------------------------
# 4. Faculty & TPO Verification Queue (MOD-03)
# ---------------------------------------------------------
@app.get("/faculty/queue", response_class=HTMLResponse)
async def faculty_verification_queue(
    request: Request,
    current_user: dict = Depends(role_required(["faculty_tpo", "admin"])),
    success: Optional[str] = None,
    error: Optional[str] = None
):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.*, u.full_name, u.email, v.full_name as verified_by_name
            FROM students s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN users v ON s.verified_by = v.id
            ORDER BY s.is_verified ASC, s.cgpa DESC
        """)
        students = [dict(r) for r in cursor.fetchall()]

    return templates.TemplateResponse(
        request=request,
        name="faculty_queue.html",
        context={
            "user": current_user,
            "students": students,
            "active_page": "faculty_queue",
            "success": success,
            "error": error
        }
    )

@app.post("/faculty/verify")
async def process_student_verification(
    request: Request,
    student_id: int = Form(...),
    action: str = Form(...),
    remarks: str = Form(...),
    current_user: dict = Depends(role_required(["faculty_tpo", "admin"])),
):
    try:
        validated = VerificationActionRequest(
            student_id=student_id,
            action=action,
            remarks=remarks
        )
    except Exception as val_err:
        return RedirectResponse(url=f"/faculty/queue?error={val_err}", status_code=303)

    is_verified_val = 1 if validated.action == "approve" else 0
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE students 
            SET is_verified = ?, verified_by = ?, verification_remarks = ?, verified_at = ?
            WHERE id = ?
        """, (is_verified_val, current_user["user_id"], validated.remarks, now_str, validated.student_id))
        
        status_word = "APPROVED" if is_verified_val == 1 else "REJECTED"
        log_audit(
            conn,
            current_user["user_id"],
            f"VERIFICATION_{status_word}",
            f"Faculty verified student ID {validated.student_id}: {validated.remarks}"
        )

    return RedirectResponse(
        url=f"/faculty/queue?success=Verification+decision+recorded+({status_word})+for+student+ID+{student_id}.",
        status_code=303
    )

# ---------------------------------------------------------
# 5. Recruiter Talent Console (MOD-06)
# ---------------------------------------------------------
@app.get("/recruiter/console", response_class=HTMLResponse)
async def recruiter_console(
    request: Request,
    branch: Optional[str] = None,
    min_cgpa: Optional[float] = None,
    skill: Optional[str] = None,
    verified_only: Optional[int] = None,
    zero_backlogs: Optional[int] = None,
    current_user: dict = Depends(role_required(["recruiter", "admin"])),
):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT s.*, u.full_name, u.email, v.full_name as verified_by_name
            FROM students s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN users v ON s.verified_by = v.id
            WHERE 1=1
        """
        params = []
        if branch:
            query += " AND s.branch = ?"
            params.append(branch)
        if min_cgpa is not None and min_cgpa > 0.0:
            query += " AND s.cgpa >= ?"
            params.append(min_cgpa)
        if skill:
            query += " AND s.skills LIKE ?"
            params.append(f"%{skill.strip()}%")
        if verified_only == 1:
            query += " AND s.is_verified = 1"
        if zero_backlogs == 1:
            query += " AND s.backlogs = 0"
            
        query += " ORDER BY s.cgpa DESC"
        cursor.execute(query, params)
        raw_candidates = [dict(r) for r in cursor.fetchall()]

        candidates = []
        for c in raw_candidates:
            cursor.execute("SELECT COUNT(*) as p_count FROM projects WHERE student_id = ?", (c["id"],))
            p_count = cursor.fetchone()["p_count"]
            cursor.execute("SELECT COUNT(*) as i_count, SUM(duration_months) as total_m FROM internships WHERE student_id = ?", (c["id"],))
            i_row = cursor.fetchone()
            i_count = i_row["i_count"] or 0
            total_m = i_row["total_m"] or 0

            c["rri"] = calculate_rri(
                cgpa=c["cgpa"],
                tenth_pct=c["tenth_pct"],
                twelfth_pct=c["twelfth_pct"],
                backlogs=c["backlogs"],
                skills=c["skills"],
                projects_count=p_count,
                has_project_links=True,
                internships_count=i_count,
                total_internship_months=total_m,
                is_verified=bool(c["is_verified"])
            )
            candidates.append(c)

    return templates.TemplateResponse(
        request=request,
        name="recruiter_console.html",
        context={
            "user": current_user,
            "candidates": candidates,
            "filters": {
                "branch": branch or "",
                "min_cgpa": min_cgpa or 0.0,
                "skill": skill or "",
                "verified_only": bool(verified_only),
                "zero_backlogs": bool(zero_backlogs),
            },
            "active_page": "recruiter_console"
        }
    )

@app.get("/recruiter/resume/{student_id}/download")
@app.get("/recruiter/candidate/{student_id}")
async def recruiter_download_single_resume(
    student_id: int,
    request: Request,
    current_user: dict = Depends(role_required(["recruiter", "admin"]))
):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.*, u.full_name, u.email, v.full_name as verified_by_name
            FROM students s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN users v ON s.verified_by = v.id
            WHERE s.id = ?
        """, (student_id,))
        student_row = cursor.fetchone()
        if not student_row:
            raise HTTPException(status_code=404, detail="Candidate not found.")
        
        student = dict(student_row)
        cursor.execute("SELECT * FROM projects WHERE student_id = ?", (student_id,))
        projects = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT * FROM internships WHERE student_id = ?", (student_id,))
        internships = [dict(r) for r in cursor.fetchall()]

    pdf_bytes = compile_resume_pdf(student, projects, internships)
    filename = f"{student['roll_no']}_{student['full_name'].replace(' ', '_')}_{student['branch']}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/recruiter/export-zip")
async def export_bulk_resumes_zip(
    request: Request,
    branch: Optional[str] = None,
    min_cgpa: Optional[float] = None,
    skill: Optional[str] = None,
    verified_only: Optional[int] = None,
    zero_backlogs: Optional[int] = None,
    current_user: dict = Depends(role_required(["recruiter", "admin"]))
):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT s.*, u.full_name, u.email, v.full_name as verified_by_name
            FROM students s
            JOIN users u ON s.user_id = u.id
            LEFT JOIN users v ON s.verified_by = v.id
            WHERE 1=1
        """
        params = []
        if branch:
            query += " AND s.branch = ?"
            params.append(branch)
        if min_cgpa is not None and min_cgpa > 0.0:
            query += " AND s.cgpa >= ?"
            params.append(min_cgpa)
        if skill:
            query += " AND s.skills LIKE ?"
            params.append(f"%{skill.strip()}%")
        if verified_only == 1:
            query += " AND s.is_verified = 1"
        if zero_backlogs == 1:
            query += " AND s.backlogs = 0"

        cursor.execute(query, params)
        students = [dict(r) for r in cursor.fetchall()]

        if not students:
            raise HTTPException(status_code=400, detail="No candidates match the specified filter criteria to export.")

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for s in students:
                cursor.execute("SELECT * FROM projects WHERE student_id = ?", (s["id"],))
                projs = [dict(r) for r in cursor.fetchall()]
                cursor.execute("SELECT * FROM internships WHERE student_id = ?", (s["id"],))
                ints = [dict(r) for r in cursor.fetchall()]
                
                pdf_bytes = compile_resume_pdf(s, projs, ints)
                clean_name = s['full_name'].replace(' ', '_')
                file_name = f"{s['roll_no']}_{clean_name}_{s['branch']}.pdf"
                zf.writestr(file_name, pdf_bytes)

        log_audit(conn, current_user["user_id"], "BULK_EXPORT_ZIP", f"Exported {len(students)} resumes to ZIP")

    zip_buffer.seek(0)
    zip_filename = f"candidates_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
    )

# ---------------------------------------------------------
# 6. Isolated Database Console (Section 2 - Admin Only)
# ---------------------------------------------------------
@app.get("/admin/database", response_class=HTMLResponse)
async def admin_database_console(
    request: Request,
    table: Optional[str] = "users",
    current_user: dict = Depends(login_required)
):
    allowed_tables = ["users", "students", "projects", "internships", "access_requests", "audit_logs"]
    target_table = table if table in allowed_tables else "users"

    # Strict exclusive main admin access check: only vallamsettyakhilesh@gmail.com (or approved temporary access token)
    clean_user_email = current_user.get("email", "").strip().lower().replace(" ", "")
    is_main_admin = (clean_user_email == HEAD_ADMIN_EMAIL.lower().replace(" ", ""))
    has_temp_access = has_active_table_access(current_user.get("user_id"), target_table)

    if not (is_main_admin or has_temp_access):
        with get_db_connection() as conn:
            log_audit(
                conn,
                current_user.get("user_id"),
                "MAIN_ADMIN_PAGE_ACCESS_DENIED",
                f"Unauthorized attempt to access main admin page by {clean_user_email}"
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: The main admin database page is strictly restricted to vallamsettyakhilesh@gmail.com."
        )

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Compute summary metrics for live overview
        cursor.execute("SELECT COUNT(*) as cnt FROM users")
        total_users = cursor.fetchone()["cnt"]
        cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'student'")
        total_students = cursor.fetchone()["cnt"]
        cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'faculty_tpo'")
        total_faculty = cursor.fetchone()["cnt"]
        cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'recruiter'")
        total_recruiters = cursor.fetchone()["cnt"]

        cursor.execute(f"PRAGMA table_info({target_table});")
        columns = [r["name"] for r in cursor.fetchall()]

        cursor.execute(f"SELECT * FROM {target_table} ORDER BY 1 DESC LIMIT 100;")
        rows = [dict(r) for r in cursor.fetchall()]

    return templates.TemplateResponse(
        request=request,
        name="admin_database.html",
        context={
            "user": current_user,
            "tables": allowed_tables,
            "active_table": target_table,
            "columns": columns,
            "rows": rows,
            "custom_result": None,
            "active_page": "admin_database",
            "stats": {
                "total_users": total_users,
                "total_students": total_students,
                "total_faculty": total_faculty,
                "total_recruiters": total_recruiters
            }
        }
    )

@app.post("/admin/user/{user_id}/delete")
async def admin_delete_user(
    user_id: int,
    request: Request,
    current_user: dict = Depends(login_required)
):
    clean_user_email = current_user.get("email", "").strip().lower().replace(" ", "")
    if clean_user_email != HEAD_ADMIN_EMAIL.lower().replace(" ", ""):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Only the primary head administrator can delete users."
        )

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, full_name, role FROM users WHERE id = ?", (user_id,))
        target = cursor.fetchone()
        if not target:
            return RedirectResponse(url="/admin/database?table=users&error=User+not+found.", status_code=303)

        target_email = target["email"].strip().lower().replace(" ", "")
        if target_email == HEAD_ADMIN_EMAIL.lower().replace(" ", ""):
            return RedirectResponse(url="/admin/database?table=users&error=The+primary+administrator+account+cannot+be+deleted.", status_code=303)

        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        log_audit(
            conn,
            current_user.get("user_id"),
            "USER_DELETED",
            f"Admin deleted user {target['email']} ({target['full_name']}, role={target['role']})"
        )

    return RedirectResponse(url="/admin/database?table=users&success=User+deleted+successfully.", status_code=303)

@app.post("/admin/database/query", response_class=HTMLResponse)
async def admin_database_query(
    request: Request,
    sql_query: str = Form(...),
    current_user: dict = Depends(role_required(["admin"]))
):
    clean_user_email = current_user.get("email", "").strip().lower().replace(" ", "")
    if clean_user_email != HEAD_ADMIN_EMAIL.lower().replace(" ", ""):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied: Main admin queries are strictly restricted to vallamsettyakhilesh@gmail.com."
        )

    allowed_tables = ["users", "students", "projects", "internships", "access_requests", "audit_logs"]
    clean_q = sql_query.strip().upper()

    if not clean_q.startswith("SELECT"):
        return templates.TemplateResponse(
            request=request,
            name="admin_database.html",
            context={
                "user": current_user,
                "tables": allowed_tables,
                "active_table": "students",
                "columns": [],
                "rows": [],
                "custom_result": None,
                "error": "Security restriction: Only SELECT queries are permitted in this console."
            },
            status_code=400
        )

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql_query)
            fetched = cursor.fetchall()
            if fetched:
                res_cols = [k for k in fetched[0].keys()]
                res_rows = [dict(r) for r in fetched]
            else:
                res_cols = []
                res_rows = []
            
            log_audit(conn, current_user["user_id"], "SQL_EXECUTED", f"Query: {sql_query[:100]}")

            return templates.TemplateResponse(
                request=request,
                name="admin_database.html",
                context={
                    "user": current_user,
                    "tables": allowed_tables,
                    "active_table": "students",
                    "columns": [],
                    "rows": [],
                    "custom_result": {"columns": res_cols, "rows": res_rows},
                    "success": f"Query returned {len(res_rows)} row(s)."
                }
            )
    except Exception as e:
        return templates.TemplateResponse(
            request=request,
            name="admin_database.html",
            context={
                "user": current_user,
                "tables": allowed_tables,
                "active_table": "students",
                "columns": [],
                "rows": [],
                "custom_result": None,
                "error": f"SQL Execution Error: {str(e)}"
            },
            status_code=400
        )

# ---------------------------------------------------------
# 7. Database Access Request Workflow (Section 2)
# ---------------------------------------------------------
@app.get("/access-request", response_class=HTMLResponse)
async def access_request_page(
    request: Request,
    current_user: dict = Depends(login_required),
    success: Optional[str] = None,
    error: Optional[str] = None
):
    user_id = current_user["user_id"]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM access_requests WHERE user_id = ? ORDER BY id DESC", (user_id,))
        requests = [dict(r) for r in cursor.fetchall()]

        cursor.execute("""
            SELECT * FROM access_requests 
            WHERE user_id = ? AND status = 'approved' AND datetime(expires_at) > datetime('now')
        """, (user_id,))
        active_grants = [dict(r) for r in cursor.fetchall()]

    return templates.TemplateResponse(
        request=request,
        name="access_request.html",
        context={
            "user": current_user,
            "requests": requests,
            "active_grants": active_grants,
            "active_page": "access_request",
            "success": success,
            "error": error
        }
    )

@app.post("/access-request")
async def submit_access_request(
    request: Request,
    target_table: str = Form(...),
    requested_duration_minutes: int = Form(...),
    reason: str = Form(...),
    current_user: dict = Depends(login_required),
):
    try:
        validated = DatabaseAccessRequestCreate(
            target_table=target_table,
            requested_duration_minutes=requested_duration_minutes,
            reason=reason
        )
    except Exception as val_err:
        return RedirectResponse(url=f"/access-request?error={val_err}", status_code=303)

    user_id = current_user["user_id"]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO access_requests (user_id, target_table, requested_duration_minutes, reason, status)
            VALUES (?, ?, ?, ?, 'pending')
        """, (user_id, validated.target_table, validated.requested_duration_minutes, validated.reason))
        log_audit(conn, user_id, "ACCESS_REQUEST_SUBMITTED", f"Requested {validated.target_table} for {validated.requested_duration_minutes}m")

    return RedirectResponse(
        url="/access-request?success=Database+access+request+submitted+to+System+Administrator+queue.",
        status_code=303
    )

@app.get("/admin/access-requests", response_class=HTMLResponse)
async def admin_access_requests_queue(
    request: Request,
    current_user: dict = Depends(role_required(["admin"])),
    success: Optional[str] = None,
    error: Optional[str] = None
):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, u.email, u.full_name, u.role
            FROM access_requests r
            JOIN users u ON r.user_id = u.id
            ORDER BY r.status = 'pending' DESC, r.id DESC
        """)
        requests = [dict(r) for r in cursor.fetchall()]

    return templates.TemplateResponse(
        request=request,
        name="admin_requests.html",
        context={
            "user": current_user,
            "requests": requests,
            "active_page": "admin_requests",
            "success": success,
            "error": error
        }
    )

@app.post("/admin/access-requests/action")
async def process_access_request_action(
    request: Request,
    request_id: int = Form(...),
    action: str = Form(...),
    granted_minutes: int = Form(default=60),
    remarks: str = Form(default=""),
    current_user: dict = Depends(role_required(["admin"])),
):
    try:
        validated = DatabaseAccessActionRequest(
            request_id=request_id,
            action=action,
            granted_minutes=granted_minutes,
            remarks=remarks
        )
    except Exception as val_err:
        return RedirectResponse(url=f"/admin/access-requests?error={val_err}", status_code=303)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM access_requests WHERE id = ?", (validated.request_id,))
        req = cursor.fetchone()
        if not req:
            raise HTTPException(status_code=404, detail="Request not found.")

        if validated.action == "approve":
            token = secrets.token_urlsafe(24)
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=validated.granted_minutes)).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                UPDATE access_requests
                SET status = 'approved', reviewed_by = ?, reviewer_remarks = ?, token = ?, expires_at = ?
                WHERE id = ?
            """, (current_user["user_id"], validated.remarks, token, expires_at, validated.request_id))
            log_audit(conn, current_user["user_id"], "ACCESS_APPROVED", f"Approved request ID {validated.request_id} for {validated.granted_minutes}m")
            status_msg = f"Request+ID+{validated.request_id}+approved+for+{validated.granted_minutes}+minutes."
        else:
            cursor.execute("""
                UPDATE access_requests
                SET status = 'rejected', reviewed_by = ?, reviewer_remarks = ?
                WHERE id = ?
            """, (current_user["user_id"], validated.remarks, validated.request_id))
            log_audit(conn, current_user["user_id"], "ACCESS_REJECTED", f"Rejected request ID {validated.request_id}")
            status_msg = f"Request+ID+{validated.request_id}+rejected."

    return RedirectResponse(url=f"/admin/access-requests?success={status_msg}", status_code=303)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
