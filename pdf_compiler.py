import io
import time
import logging
from typing import Dict, Any, List
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.units import inch

logger = logging.getLogger(__name__)

def _generate_pdf_canvas(student: Dict[str, Any], projects: List[Dict[str, Any]], internships: List[Dict[str, Any]]) -> bytes:
    """Internal synchronous generator using ReportLab Platypus single-column flow."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    
    # Custom ATS-compliant clean styles
    name_style = ParagraphStyle(
        'ATSName',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1E293B'),
        alignment=0, # Left-aligned for ATS
        spaceAfter=4
    )
    
    contact_style = ParagraphStyle(
        'ATSContact',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#475569'),
        spaceAfter=10
    )
    
    section_style = ParagraphStyle(
        'ATSSection',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#0F172A'),
        spaceBefore=8,
        spaceAfter=2,
        keepWithNext=True
    )
    
    item_title_style = ParagraphStyle(
        'ATSItemTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#1E293B'),
        spaceBefore=4
    )
    
    item_sub_style = ParagraphStyle(
        'ATSItemSub',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#64748B'),
        spaceAfter=2
    )
    
    body_style = ParagraphStyle(
        'ATSBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#334155'),
        spaceAfter=4
    )
    
    bullet_style = ParagraphStyle(
        'ATSBullet',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#334155'),
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=2
    )
    
    badge_style = ParagraphStyle(
        'ATSBadge',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#065F46')
    )

    story = []

    # 1. Header (Name & Contact)
    full_name = student.get('full_name', 'Student Candidate').upper()
    story.append(Paragraph(full_name, name_style))
    
    email = student.get('email', '')
    phone = student.get('phone', '')
    roll_no = student.get('roll_no', '')
    branch = student.get('branch', '')
    contact_parts = [p for p in [f"Roll: {roll_no}", f"Branch: {branch}", f"Email: {email}", f"Phone: {phone}"] if p]
    story.append(Paragraph(" | ".join(contact_parts), contact_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E1'), spaceBefore=2, spaceAfter=8))

    # Verification Seal Banner (if verified)
    if student.get('is_verified'):
        v_by = student.get('verified_by_name', 'Faculty Mentor / TPO Office')
        v_date = student.get('verified_at', 'Verified')
        seal_text = f"OFFICIALLY VERIFIED CANDIDATE | Verified by: {v_by} on {v_date} | TPO Credentials Approved"
        t_seal = Table([[Paragraph(seal_text, badge_style)]], colWidths=[doc.width])
        t_seal.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#D1FAE5')),
            ('PADDING', (0,0), (-1,-1), 4),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#10B981')),
            ('ALIGN', (0,0), (-1,-1), 'CENTER')
        ]))
        story.append(t_seal)
        story.append(Spacer(1, 8))

    # 2. Education
    story.append(Paragraph("ACADEMIC PROFILE", section_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#E2E8F0'), spaceBefore=1, spaceAfter=4))
    
    cgpa = student.get('cgpa', 0.0)
    tenth = student.get('tenth_pct', 0.0)
    twelfth = student.get('twelfth_pct', 0.0)
    backlogs = student.get('backlogs', 0)
    backlog_str = "Zero Active Backlogs" if backlogs == 0 else f"{backlogs} Active Backlog(s)"
    
    edu_text = f"<b>Bachelor of Technology in {branch}</b> | CGPA: <b>{cgpa:.2f} / 10.0</b> ({backlog_str})<br/>" \
               f"Senior Secondary (12th Grade): <b>{twelfth:.1f}%</b> | Secondary (10th Grade): <b>{tenth:.1f}%</b>"
    story.append(Paragraph(edu_text, body_style))
    story.append(Spacer(1, 6))

    # 3. Technical Skills
    skills_raw = student.get('skills', '')
    if skills_raw:
        story.append(Paragraph("TECHNICAL PROFICIENCIES", section_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#E2E8F0'), spaceBefore=1, spaceAfter=4))
        skills_clean = ", ".join([s.strip() for s in skills_raw.split(",") if s.strip()])
        story.append(Paragraph(f"<b>Core Technologies & Tools:</b> {skills_clean}", body_style))
        story.append(Spacer(1, 6))

    # 4. Technical Projects
    if projects:
        story.append(Paragraph("TECHNICAL & ACADEMIC PROJECTS", section_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#E2E8F0'), spaceBefore=1, spaceAfter=4))
        for proj in projects:
            title = proj.get('title', 'Project')
            tech = proj.get('technologies', '')
            desc = proj.get('description', '')
            gh = proj.get('github_url', '')
            links = f" [GitHub: {gh}]" if gh else ""
            
            story.append(Paragraph(f"<b>{title}</b> &mdash; <i>{tech}</i>{links}", item_title_style))
            # Format bullets with action verbs
            sentences = [s.strip() for s in desc.replace("\r", "").split("\n") if s.strip()]
            if not sentences:
                sentences = [desc]
            for s in sentences:
                story.append(Paragraph(f"&bull; {s}", bullet_style))
            story.append(Spacer(1, 4))
        story.append(Spacer(1, 4))

    # 5. Internships & Work Experience
    if internships:
        story.append(Paragraph("PROFESSIONAL INTERNSHIPS & INDUSTRY EXPERIENCE", section_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#E2E8F0'), spaceBefore=1, spaceAfter=4))
        for exp in internships:
            comp = exp.get('company', 'Company')
            role = exp.get('role', 'Intern')
            dur = exp.get('duration_months', 1)
            desc = exp.get('description', '')
            story.append(Paragraph(f"<b>{role}</b> &mdash; {comp} ({dur} Month{'s' if dur > 1 else ''})", item_title_style))
            sentences = [s.strip() for s in desc.replace("\r", "").split("\n") if s.strip()]
            if not sentences:
                sentences = [desc]
            for s in sentences:
                story.append(Paragraph(f"&bull; {s}", bullet_style))
            story.append(Spacer(1, 4))

    doc.build(story)
    return buffer.getvalue()

def compile_resume_pdf(student: Dict[str, Any], projects: List[Dict[str, Any]], internships: List[Dict[str, Any]], max_retries: int = 3) -> bytes:
    """
    ATS Resume Compiler background worker wrapper.
    Implements strict retry limit (max_retries=3) with exponential backoff to eliminate infinite loops.
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            return _generate_pdf_canvas(student, projects, internships)
        except Exception as e:
            last_error = e
            backoff_delay = 0.1 * (2 ** (attempt - 1))
            logger.warning(f"PDF compilation attempt {attempt}/{max_retries} failed: {e}. Retrying in {backoff_delay:.2f}s...")
            time.sleep(backoff_delay)
            
    raise RuntimeError(f"PDF compilation failed after {max_retries} attempts: {last_error}")
