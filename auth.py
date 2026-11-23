import hmac
import hashlib
import json
import base64
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
import bcrypt
from fastapi import Request, HTTPException, status, Depends
from fastapi.responses import RedirectResponse
from database import get_db_connection, log_audit

SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "system-secure-key-38491-resume-management-core")
SESSION_COOKIE_NAME = "srms_session_token"
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
HEAD_ADMIN_EMAIL = "vallamsettyakhilesh@gmail.com"
ADMIN_EMAIL = HEAD_ADMIN_EMAIL
PRIMARY_ADMIN_EMAIL = HEAD_ADMIN_EMAIL

def hash_password(password: str) -> str:
    """Hashes a plaintext password using bcrypt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plaintext password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def create_session_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Creates a tamper-proof HMAC-SHA256 signed session token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=8))
    to_encode.update({"exp": expire.timestamp()})
    
    payload_bytes = json.dumps(to_encode, sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("utf-8")
    
    signature = hmac.new(SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"

def decode_session_token(token: str) -> Optional[Dict[str, Any]]:
    """Validates and decodes the signed session token."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, signature = token.split(".", 1)
        expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        
        payload_json = base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8")
        payload = json.loads(payload_json)
        
        exp = payload.get("exp")
        if exp and datetime.now(timezone.utc).timestamp() > exp:
            return None
            
        return payload
    except Exception:
        return None

def authenticate_user(
    email: str,
    password: str,
    expected_role: Optional[str] = None,
    ip: str = "127.0.0.1"
) -> tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Authenticates a user with atomic transaction safety, 5-attempt lockout,
    and strict administrative access control:
    - ONLY vallamsettyakhilesh@gmail.com can log in as Administrator.
    - Admin login does not require selecting an admin role (automatically resolved).
    - All pending registration requests are held in waiting state.
    """
    clean_email = email.strip().lower()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (clean_email,))
        user = cursor.fetchone()
        
        if not user:
            log_audit(conn, None, "LOGIN_FAILED", f"Attempt with unknown email: {clean_email}", ip)
            return False, None, "Invalid email, password, or selected role."
        
        user_dict = dict(user)
        user_id = user_dict["id"]
        
        # Check active lockout
        locked_until_str = user_dict.get("locked_until")
        if locked_until_str:
            try:
                locked_until = datetime.fromisoformat(locked_until_str)
                if datetime.now(timezone.utc) < locked_until.replace(tzinfo=timezone.utc):
                    remaining_mins = int((locked_until.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds() / 60) + 1
                    log_audit(conn, user_id, "LOGIN_BLOCKED", f"Account locked for {remaining_mins} more minutes", ip)
                    return False, None, f"Account is locked due to 5 consecutive failed attempts. Try again in {remaining_mins} minute(s)."
                else:
                    cursor.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (user_id,))
            except Exception:
                pass

        # Verify password
        pw_ok = verify_password(password, user_dict["password_hash"])
        
        # Strict Head Admin Gate:
        # If email is HEAD_ADMIN_EMAIL, automatically authorize as 'admin'
        if clean_email == HEAD_ADMIN_EMAIL.lower():
            role_ok = True
            user_dict["role"] = "admin"
        else:
            # If a non-head user's DB role is admin, block login: only HEAD_ADMIN_EMAIL can log in as admin
            if user_dict["role"] == "admin":
                log_audit(conn, user_id, "ADMIN_ACCESS_DENIED", f"Non-head user {clean_email} blocked from admin login", ip)
                return False, None, "Administrative access is restricted exclusively to the Head Administrator."
            
            # For standard roles: verify expected_role if supplied
            if expected_role:
                role_ok = (user_dict["role"] == expected_role)
            else:
                role_ok = True

        if not (pw_ok and role_ok):
            new_attempts = user_dict["failed_attempts"] + 1
            if new_attempts >= MAX_FAILED_ATTEMPTS:
                lockout_time = (datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
                cursor.execute(
                    "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                    (new_attempts, lockout_time, user_id)
                )
                log_audit(conn, user_id, "ACCOUNT_LOCKED", f"5 consecutive failed logins reached. Locked for {LOCKOUT_MINUTES} min.", ip)
                return False, None, f"Security Alert: 5 consecutive failed login attempts reached. Your account is now locked for {LOCKOUT_MINUTES} minutes."
            else:
                cursor.execute(
                    "UPDATE users SET failed_attempts = ? WHERE id = ?",
                    (new_attempts, user_id)
                )
                remaining = MAX_FAILED_ATTEMPTS - new_attempts
                log_audit(conn, user_id, "LOGIN_FAILED", f"Failed attempt #{new_attempts}", ip)
                return False, None, f"Invalid credentials. Warning: {remaining} attempt(s) remaining before account lockout."

        # Direct Login (Permissions removed - accounts are active upon registration)
        account_status = user_dict.get("status", "APPROVED")
        is_active = user_dict.get("is_active", 1)
        
        # Head admin is always active and approved
        if clean_email == HEAD_ADMIN_EMAIL.lower():
            account_status = "APPROVED"
            is_active = 1
        
        if is_active == 0:
            log_audit(conn, user_id, "LOGIN_BLOCKED_INACTIVE", "Account is inactive", ip)
            return False, None, "Your account is currently disabled. Please contact administration."

        if account_status == "REJECTED":
            log_audit(conn, user_id, "LOGIN_REJECTED", "Account registration rejected", ip)
            return False, None, "Your account has been deactivated."

        # Success - reset attempts
        cursor.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (user_id,))
        log_audit(conn, user_id, "LOGIN_SUCCESS", f"Role: {user_dict['role']}", ip)
        return True, user_dict, ""

def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """Extracts and verifies session user from signed cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    payload = decode_session_token(token)
    if not payload:
        return None
    return payload

def login_required(request: Request) -> Dict[str, Any]:
    """Dependency enforcing that a user must be logged in. Redirects to /login if not."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"Location": "/login"}
        )
    return user

def role_required(allowed_roles: List[str]):
    """
    Route guard dependency enforcing strict role-based access control.
    Raises strict HTTP 403 Forbidden if user role is not authorized.
    """
    def role_checker(request: Request) -> Dict[str, Any]:
        user = get_current_user(request)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required. Please log in.",
                headers={"Location": "/login"}
            )
        
        # Strict Administrator Guard: only HEAD_ADMIN_EMAIL can access admin-only endpoints
        if "admin" in allowed_roles and len(allowed_roles) == 1:
            if user.get("email", "").lower().replace(" ", "") != HEAD_ADMIN_EMAIL.lower().replace(" ", ""):
                with get_db_connection() as conn:
                    log_audit(
                        conn,
                        user.get("user_id"),
                        "UNAUTHORIZED_ADMIN_BREACH_ATTEMPT",
                        f"User '{user.get('email')}' attempted to access admin-only endpoint: {request.url.path}",
                        request.client.host if request.client else "127.0.0.1"
                    )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access Denied: Exclusive access restricted to the Head Administrator (vallamsettyakhilesh@gmail.com)."
                )

        if user.get("role") not in allowed_roles:
            with get_db_connection() as conn:
                log_audit(
                    conn,
                    user.get("user_id"),
                    "UNAUTHORIZED_ACCESS_BLOCKED",
                    f"User role '{user.get('role')}' denied access to '{request.url.path}'. Required: {allowed_roles}",
                    request.client.host if request.client else "127.0.0.1"
                )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access Denied: Role '{user.get('role')}' is not authorized to access this resource. HTTP 403 Forbidden."
            )
        return user
    return role_checker

def has_active_table_access(user_id: int, table_name: str) -> bool:
    """Checks if a user has an approved, unexpired database access token for a table."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, expires_at FROM access_requests 
            WHERE user_id = ? AND (target_table = ? OR target_table = 'ALL') 
            AND status = 'approved'
            ORDER BY id DESC LIMIT 1
        """, (user_id, table_name))
        row = cursor.fetchone()
        if not row:
            return False
        expires_at_str = row["expires_at"]
        if not expires_at_str:
            return False
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            if datetime.now(timezone.utc) < expires_at.replace(tzinfo=timezone.utc):
                return True
        except Exception:
            return False
        return False