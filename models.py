from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal

class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=120)
    password: str = Field(..., min_length=1)
    role: Optional[Literal['student', 'faculty_tpo', 'recruiter', 'admin']] = None

class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    email: str = Field(..., min_length=5, max_length=120)
    password: str = Field(..., min_length=6, max_length=120)
    role: Literal['student', 'faculty_tpo', 'recruiter']
    department_company: str = Field(default="", max_length=150)
    roll_no: Optional[str] = Field(default="", max_length=50)
    branch: Optional[str] = Field(default="", max_length=50)
    phone: Optional[str] = Field(default="", max_length=25)

class UserApprovalActionRequest(BaseModel):
    user_id: int = Field(..., gt=0)
    action: Literal['approve', 'reject']
    remarks: Optional[str] = Field(default="", max_length=500)

class ProfileUpdateRequest(BaseModel):
    phone: str = Field(..., min_length=8, max_length=20)
    cgpa: float = Field(..., ge=0.0, le=10.0, description="CGPA must be between 0.0 and 10.0")
    tenth_pct: float = Field(..., ge=0.0, le=100.0, description="10th percentage must be between 0.0 and 100.0")
    twelfth_pct: float = Field(..., ge=0.0, le=100.0, description="12th percentage must be between 0.0 and 100.0")
    backlogs: int = Field(..., ge=0, description="Backlogs count must be non-negative")
    skills: str = Field(default="", max_length=500)
    marksheet_filename: Optional[str] = Field(default="")

    @field_validator('cgpa')
    @classmethod
    def validate_cgpa(cls, v: float) -> float:
        if v < 0.0 or v > 10.0:
            raise ValueError("Guard Clause Violation: CGPA must strictly be between 0.0 and 10.0")
        return round(v, 2)

    @field_validator('tenth_pct', 'twelfth_pct')
    @classmethod
    def validate_percentage(cls, v: float) -> float:
        if v < 0.0 or v > 100.0:
            raise ValueError("Guard Clause Violation: Academic percentage must be between 0.0% and 100.0%")
        return round(v, 2)

class ProjectCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=120)
    description: str = Field(..., min_length=10, max_length=2000)
    technologies: str = Field(..., min_length=2, max_length=200)
    github_url: Optional[str] = Field(default="", max_length=300)
    live_url: Optional[str] = Field(default="", max_length=300)

class InternshipCreateRequest(BaseModel):
    company: str = Field(..., min_length=2, max_length=120)
    role: str = Field(..., min_length=2, max_length=120)
    duration_months: int = Field(..., ge=1, le=48)
    description: str = Field(..., min_length=10, max_length=2000)

class VerificationActionRequest(BaseModel):
    student_id: int = Field(..., gt=0)
    action: Literal['approve', 'reject']
    remarks: str = Field(..., min_length=3, max_length=500)

class DatabaseAccessRequestCreate(BaseModel):
    target_table: str = Field(..., min_length=2, max_length=50)
    reason: str = Field(..., min_length=10, max_length=500)
    requested_duration_minutes: int = Field(default=60, ge=5, le=1440)

class DatabaseAccessActionRequest(BaseModel):
    request_id: int = Field(..., gt=0)
    action: Literal['approve', 'reject']
    remarks: Optional[str] = Field(default="", max_length=500)
    granted_minutes: int = Field(default=60, ge=5, le=1440)