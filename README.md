# Student Resume Management System (SRMS)

Enterprise-grade, secure web application for automated academic resume lifecycle management, ATS compilation, credential verification, recruiter talent acquisition, and administrative registration governance.

---

## 1. System Architecture & Tech Stack

- **Backend Framework:** FastAPI (Async ASGI, Python 3.14)
- **Database Engine:** SQLite3 with explicit ACID transactions, foreign key constraints (`PRAGMA foreign_keys = ON`), composite indexes, and unique constraints.
- **Security & RBAC:**
  - Password hashing with Bcrypt (`rounds=12`).
  - Brute-force account lockout: 5 consecutive failed attempts trigger a 15-minute lockout.
  - Tamper-proof HMAC-SHA256 signed session tokens stored in HttpOnly, SameSite cookies.
  - Strict route guards (`login_required`, `role_required`) enforcing HTTP 403 Forbidden.
- **Primary Administrator & Approval Gate (Section 7):**
  - Configured Primary System Administrator: `vallamsettyakhilesh@gmail.com` / `akhi@2007`.
  - Mandatory registration gate: all new users (Students, Faculty, Recruiters) register in `PENDING_ADMIN_APPROVAL` (`is_active = False`).
  - Automated transactional email notification triggered immediately to `vallamsettyakhilesh@gmail.com` with cryptographic one-click action links.
  - Login hold state displaying explicit notification until approved.
- **Resume Readiness Index (RRI):** Real-time weighted scoring out of 100 points ($W_{acad}: 25$, $W_{proj}: 25$, $W_{skill}: 20$, $W_{exp}: 15$, $W_{ver}: 15$).
- **PDF Compiler (MOD-04):** Headless ReportLab single-column ATS engine with retry limit (`max_retries=3`) and exponential backoff.
- **Bulk Talent Consignment (MOD-06):** In-memory ZIP compilation with standardized nomenclature (`RollNo_Name_Branch.pdf`).

---

## 2. Default System Credentials

| Role | Email | Password | Access Capabilities |
| :--- | :--- | :--- | :--- |
| **Primary System Administrator (Sec 7)** | `vallamsettyakhilesh@gmail.com` | `akhi@2007` | Unrestricted `/admin/database` console, new user approvals queue (`/admin/user-approvals`), access requests |
| **Secondary Administrator** | `admin@university.edu` | `Admin@12345` | Auxiliary administrative operations |
| **Faculty Mentor & TPO** | `faculty@university.edu` | `Faculty@12345` | `/faculty/queue` side-by-side audit viewer, mark sheet verification |
| **Corporate Recruiter** | `recruiter@techcorp.com` | `Recruiter@12345` | `/recruiter/console` multi-tag filters, PDF previews, bulk ZIP export |
| **Student 1 (Verified)** | `student1@university.edu` | `Student@12345` | `/student/portal`, 9.4 CGPA, RRI 100/100, live ATS resume preview & download |
| **Student 2 (Pending)** | `student2@university.edu` | `Student@12345` | `/student/portal`, 8.8 CGPA, verification pending, profile editor |

---

## 3. Core Modules & Endpoints

### 1. Mandatory Unified Entry Point (`/` or `/login`)
- Opens directly to `/login` before any other page can be accessed.
- Quick persona switcher for testing all roles, including Primary Admin (`vallamsettyakhilesh@gmail.com`).
- Direct link to new account application (`/register`).

### 2. New User Registration & Admin Approval Gate (`/register` & `/registration-pending`)
- New applicants register with role, email, password, and departmental/company details.
- Status is set to `PENDING_ADMIN_APPROVAL` (`is_active = False`).
- Automated notification email dispatched to `vallamsettyakhilesh@gmail.com` with one-click approve/reject URLs.
- Applicant is held in waiting state with status screen: *"Your registration request has been sent to the System Administrator (vallamsettyakhilesh@gmail.com). Please wait until your access request is approved before logging in."*

### 3. Admin User Approvals Queue (`/admin/user-approvals` & `/admin/users/email-action`)
- Administrator audits applicants and commits approval or rejection decisions.
- Approvals update status to `APPROVED` (`is_active = True`), unlock dashboard login, and trigger user confirmation email.

### 4. Isolated Database Console (`/admin/database`)
- Strictly isolated from standard students, faculty, and recruiters (HTTP 403 Forbidden).
- Table inspector and read-only SQL query runner wrapped in transaction savepoints.

### 5. Database Access Request Workflow (`/access-request` & `/admin/access-requests`)
- Non-admins submit a formal request specifying target table, duration, and compliance justification.
- Admin review grants time-scoped access with automatic expiry.

### 6. Student Portal & Profile Builder (`/student/portal`)
- Real-time RRI calculation gauge.
- Input validation guard clauses: CGPA strictly bounded $[0.0, 10.0]$, percentages $[0.0, 100.0]$.

### 7. Faculty & TPO Verification Queue (`/faculty/queue`)
- Side-by-side audit modal comparing student claims against uploaded mark sheet references.
- Approvals immediately award 15.0 RRI verification points ($W_{ver}$).

### 8. ATS Resume Compiler (`/student/resume/preview` & `/student/resume/download`)
- Single-column semantic text ATS format.
- Action verbs, clean typography, machine parseable.

### 9. Recruiter Talent Console (`/recruiter/console` & `/recruiter/export-zip`)
- Multi-tag filters: Branch, Min CGPA, Technical Skills, Verified Only, Zero Backlogs.
- Bulk ZIP download exporting files named `RollNo_Name_Branch.pdf`.

---

## 4. Running the Application

### Start Web Server:
```bash
python run_server.py
```
Open your browser at: `http://127.0.0.1:8000`

### Run Test Suite:
```bash
python -m pytest tests/test_system.py -v
```
All 13 test cases cover authentication, primary admin privileges, registration approval hold, email triggers, brute-force lockout, RBAC route escalation barriers, database isolation, RRI formula calculation, PDF generation, and bulk ZIP compilation.