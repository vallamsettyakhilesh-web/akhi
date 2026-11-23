import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

PRIMARY_ADMIN_EMAIL = "vallamsettyakhilesh@gmail.com"
EMAIL_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_notifications.log")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "no-reply@srms-institution.edu")

def log_email_to_file(recipient: str, subject: str, body: str):
    """Fallback logger persisting sent transactional emails to disk."""
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = (
            f"\n{'='*70}\n"
            f"TIMESTAMP: {timestamp}\n"
            f"RECIPIENT: {recipient}\n"
            f"SUBJECT:   {subject}\n"
            f"{'-'*70}\n"
            f"{body}\n"
            f"{'='*70}\n"
        )
        with open(EMAIL_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
        print(f"[EMAIL NOTIFICATION DISPATCHED] -> {recipient} | Subject: {subject}")
    except Exception as e:
        logger.error(f"Failed to write email notification log: {e}")

def send_admin_registration_notification(applicant: dict, approval_token: str, host_base: str = "http://127.0.0.1:8000") -> bool:
    """
    Triggers automated notification email to vallamsettyakhilesh@gmail.com
    containing applicant details and direct one-click secure action links.
    """
    subject = f"ACTION REQUIRED: New SRMS Registration Request - {applicant['full_name']} ({applicant['role'].upper()})"
    approve_url = f"{host_base}/admin/users/email-action?token={approval_token}&action=approve"
    reject_url = f"{host_base}/admin/users/email-action?token={approval_token}&action=reject"
    queue_url = f"{host_base}/admin/user-approvals"

    text_body = f"""
========================================================================
SRMS INSTITUTIONAL SECURITY GATE: NEW USER REGISTRATION
========================================================================

System Administrator ({PRIMARY_ADMIN_EMAIL}),

A new applicant has submitted registration for the Student Resume Management System.
The account has been placed into PENDING_ADMIN_APPROVAL status (is_active = False).

APPLICANT DETAILS:
------------------------------------------------------------------------
- Reference User ID:      {applicant.get('id', 'N/A')}
- Full Name:              {applicant.get('full_name')}
- Institutional Email:    {applicant.get('email')}
- Requested Role:         {applicant.get('role', '').upper()}
- Department / Company:   {applicant.get('department_company') or 'Not Specified'}
- Registration Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}

DIRECT SECURE ACTION LINKS:
------------------------------------------------------------------------
[APPROVE ACCOUNT ACCESS]:
{approve_url}

[REJECT ACCOUNT ACCESS]:
{reject_url}

Alternatively, you may audit and manage all pending requests in the Admin Dashboard:
{queue_url}

Institutional Security Directives:
Unapproved accounts are strictly held in a waiting state and cannot access system dashboards.
========================================================================
"""

    log_email_to_file(PRIMARY_ADMIN_EMAIL, subject, text_body)

    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        try:
            msg = MIMEMultipart()
            msg['From'] = FROM_EMAIL
            msg['To'] = PRIMARY_ADMIN_EMAIL
            msg['Subject'] = subject
            msg.attach(MIMEText(text_body, 'plain'))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
            return True
        except Exception as e:
            logger.warning(f"SMTP dispatch failed: {e}. Logged to {EMAIL_LOG_FILE}.")
            return False
    return True

def send_user_approval_confirmation(user_email: str, full_name: str, role: str, host_base: str = "http://127.0.0.1:8000") -> bool:
    """
    Sends confirmation email to user upon explicit approval by System Administrator.
    """
    subject = "Account Approved: Student Resume Management System Access Granted"
    login_url = f"{host_base}/login"

    text_body = f"""
Hello {full_name},

Your registration request for the Student Resume Management System has been approved by the System Administrator ({PRIMARY_ADMIN_EMAIL}).

ACCOUNT DETAILS:
- Registered Email: {user_email}
- Authorized Role:  {role.upper()}
- Access Status:    APPROVED (Active)

You may now log in to your institutional dashboard:
{login_url}

Thank you,
Institutional Placement & Training Cell
"""

    log_email_to_file(user_email, subject, text_body)

    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        try:
            msg = MIMEMultipart()
            msg['From'] = FROM_EMAIL
            msg['To'] = user_email
            msg['Subject'] = subject
            msg.attach(MIMEText(text_body, 'plain'))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
            return True
        except Exception as e:
            logger.warning(f"SMTP dispatch failed: {e}. Logged to {EMAIL_LOG_FILE}.")
            return False
    return True