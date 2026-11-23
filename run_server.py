import uvicorn
import os

if __name__ == "__main__":
    print("=" * 65)
    print("  STUDENT RESUME MANAGEMENT SYSTEM (SRMS) - PRODUCTION RUNNER")
    print("=" * 65)
    print("  Server URL: http://0.0.0.0:8000 (accessible on LAN & localhost)")
    print("  Default Credentials:")
    print("    - Primary Admin: Head Administrator (configured)")
    print("    - Faculty:   faculty@university.edu   / Faculty@12345")
    print("    - Recruiter: recruiter@techcorp.com   / Recruiter@12345")
    print("    - Student:   student1@university.edu  / Student@12345")
    print("=" * 65)
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)