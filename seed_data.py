from database import get_db_connection, init_db
from auth import hash_password
from datetime import datetime, timezone

PRIMARY_ADMIN_EMAIL = "vallamsettyakhilesh@gmail.com"
PRIMARY_ADMIN_PASS = "akhi@2007"

def seed_database():
    """Seeds database with production-grade sample users, profiles, and credentials."""
    init_db()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Ensure Primary System Administrator exists with exact credentials
        cursor.execute("SELECT id FROM users WHERE email = ?", (PRIMARY_ADMIN_EMAIL,))
        primary_admin = cursor.fetchone()
        if not primary_admin:
            cursor.execute("""
                INSERT INTO users (email, password_hash, plain_password, role, full_name, is_active, status, department_company)
                VALUES (?, ?, ?, 'admin', 'System Administrator (vallamsettyakhilesh)', 1, 'APPROVED', 'Institutional IT Services')
            """, (PRIMARY_ADMIN_EMAIL, hash_password(PRIMARY_ADMIN_PASS), PRIMARY_ADMIN_PASS))
            print(f"Provisioned primary system administrator: {PRIMARY_ADMIN_EMAIL}")
        else:
            # Update password hash and status to ensure exact match and approved state
            cursor.execute("""
                UPDATE users 
                SET password_hash = ?, plain_password = ?, role = 'admin', is_active = 1, status = 'APPROVED'
                WHERE email = ?
            """, (hash_password(PRIMARY_ADMIN_PASS), PRIMARY_ADMIN_PASS, PRIMARY_ADMIN_EMAIL))
            print(f"Synchronized primary system administrator: {PRIMARY_ADMIN_EMAIL}")

        # Enforce strictly SINGLE ADMIN for entire website: only PRIMARY_ADMIN_EMAIL
        cursor.execute("UPDATE users SET role = 'faculty_tpo' WHERE role = 'admin' AND email != ?", (PRIMARY_ADMIN_EMAIL,))
        # Enforce all registered users are active immediately
        cursor.execute("UPDATE users SET is_active = 1, status = 'APPROVED' WHERE is_active = 0 OR status = 'PENDING_ADMIN_APPROVAL'")

        # Backfill default known passwords for demo accounts
        known_defaults = {
            "admin@university.edu": "Admin@12345",
            "faculty@university.edu": "Faculty@12345",
            "recruiter@techcorp.com": "Recruiter@12345",
            "student1@university.edu": "Student@12345",
            "student2@university.edu": "Student@12345",
            "student3@university.edu": "Student@12345",
            "student4@university.edu": "Student@12345",
        }
        for u_email, u_pass in known_defaults.items():
            cursor.execute("UPDATE users SET plain_password = ? WHERE email = ? AND (plain_password IS NULL OR plain_password = '')", (u_pass, u_email))

        # Check if base demo records are already seeded
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE role != 'admin';")
        if cursor.fetchone()["count"] > 0:
            print("Base user records already present.")
            return

        print("Seeding database with system credentials...")

        # 1. Faculty Mentor & TPO
        cursor.execute("""
            INSERT INTO users (email, password_hash, role, full_name, is_active, status, department_company)
            VALUES (?, ?, 'faculty_tpo', ?, 1, 'APPROVED', 'Training & Placement Cell')
        """, ("faculty@university.edu", hash_password("Faculty@12345"), "Prof. Sunita Deshmukh (Head TPO)"))
        faculty_id = cursor.lastrowid

        # 3. Corporate Recruiter
        cursor.execute("""
            INSERT INTO users (email, password_hash, role, full_name, is_active, status, department_company)
            VALUES (?, ?, 'recruiter', ?, 1, 'APPROVED', 'TechCorp Global')
        """, ("recruiter@techcorp.com", hash_password("Recruiter@12345"), "Vikram Malhotra (Lead Talent Acquisition)"))

        # 4. Student 1: Aarav Sharma (Verified, Tier 1)
        cursor.execute("""
            INSERT INTO users (email, password_hash, role, full_name, is_active, status, department_company)
            VALUES (?, ?, 'student', ?, 1, 'APPROVED', 'Computer Science & Engineering')
        """, ("student1@university.edu", hash_password("Student@12345"), "Aarav Sharma"))
        s1_user_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO students (
                user_id, roll_no, branch, phone, cgpa, tenth_pct, twelfth_pct,
                backlogs, skills, marksheet_filename, is_verified, verified_by,
                verification_remarks, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            s1_user_id, "21CS042", "CSE", "+91 98765 43210", 9.4, 95.0, 94.0,
            0, "Python, FastAPI, React, PostgreSQL, Docker, Redis", "aarav_sem6_transcript.pdf",
            1, faculty_id, "All original semester mark sheets verified against university ERP database.",
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        ))
        s1_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO projects (student_id, title, description, technologies, github_url, live_url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            s1_id,
            "Distributed Task Orchestration Engine",
            "Engineered high-throughput asynchronous task scheduler processing 10,000+ jobs/min.\nIntegrated distributed worker pools with automatic fault tolerance and Redis queues.\nReduced pipeline execution latency by 42% using connection multiplexing.",
            "Python, FastAPI, Redis, Docker, Celery",
            "https://github.com/aaravsharma/task-orchestrator",
            "https://tasks.aarav.dev"
        ))
        cursor.execute("""
            INSERT INTO projects (student_id, title, description, technologies, github_url, live_url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            s1_id,
            "Real-Time Collaborative Code Playground",
            "Architected operational-transform collaborative editor supporting concurrent code editing.\nImplemented low-latency WebSocket event streams and syntax tree analysis.",
            "React, TypeScript, WebSockets, Node.js",
            "https://github.com/aaravsharma/collab-code",
            "https://code.aarav.dev"
        ))

        cursor.execute("""
            INSERT INTO internships (student_id, company, role, duration_months, description)
            VALUES (?, ?, ?, ?, ?)
        """, (
            s1_id,
            "CloudScale Technologies",
            "Backend Engineering Intern",
            4,
            "Developed REST microservices for cloud billing pipeline handling $2M monthly volume.\nOptimized SQL queries and composite indexes, cutting DB query time by 35%."
        ))

        # 5. Student 2: Priya Patel (Pending Verification)
        cursor.execute("""
            INSERT INTO users (email, password_hash, role, full_name, is_active, status, department_company)
            VALUES (?, ?, 'student', ?, 1, 'APPROVED', 'Information Technology')
        """, ("student2@university.edu", hash_password("Student@12345"), "Priya Patel"))
        s2_user_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO students (
                user_id, roll_no, branch, phone, cgpa, tenth_pct, twelfth_pct,
                backlogs, skills, marksheet_filename, is_verified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            s2_user_id, "21IT019", "IT", "+91 91234 56789", 8.8, 89.0, 87.5,
            0, "Java, Spring Boot, MySQL, Angular, AWS", "priya_sem6_marksheets.pdf", 0
        ))

        # 6. Student 3: Rohan Verma (Unverified, 1 Backlog)
        cursor.execute("""
            INSERT INTO users (email, password_hash, role, full_name, is_active, status, department_company)
            VALUES (?, ?, 'student', ?, 1, 'APPROVED', 'Electronics & Communication')
        """, ("student3@university.edu", hash_password("Student@12345"), "Rohan Verma"))
        s3_user_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO students (
                user_id, roll_no, branch, phone, cgpa, tenth_pct, twelfth_pct,
                backlogs, skills, marksheet_filename, is_verified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            s3_user_id, "21EC088", "ECE", "+91 99887 76655", 7.6, 78.0, 74.0,
            1, "Embedded C, IoT, Python, Arduino", "rohan_ec_grades.pdf", 0
        ))

        # 7. Student 4: Ananya Gupta (Verified, High CGPA, AI focus)
        cursor.execute("""
            INSERT INTO users (email, password_hash, role, full_name, is_active, status, department_company)
            VALUES (?, ?, 'student', ?, 1, 'APPROVED', 'Computer Science & Engineering')
        """, ("student4@university.edu", hash_password("Student@12345"), "Ananya Gupta"))
        s4_user_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO students (
                user_id, roll_no, branch, phone, cgpa, tenth_pct, twelfth_pct,
                backlogs, skills, marksheet_filename, is_verified, verified_by,
                verification_remarks, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            s4_user_id, "21CS105", "CSE", "+91 97654 32109", 9.6, 96.0, 95.5,
            0, "Python, PyTorch, TensorFlow, Computer Vision, FastAPI, SQL", "ananya_official_transcript.pdf",
            1, faculty_id, "Dean's list top ranker. Official grade transcripts verified with registrar.",
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        ))

        print("Database seeding completed successfully.")

if __name__ == "__main__":
    seed_database()
