from typing import Dict, Any, List

def calculate_rri(
    cgpa: float,
    tenth_pct: float,
    twelfth_pct: float,
    backlogs: int,
    skills: List[str] | str,
    projects_count: int,
    has_project_links: bool,
    internships_count: int,
    total_internship_months: int,
    is_verified: bool
) -> Dict[str, Any]:
    """
    Calculates the Resume Readiness Index (RRI) based on the official specification:
    Total: 100 points
    W_acad: 25 points
    W_proj: 25 points
    W_skill: 20 points
    W_exp: 15 points
    W_ver: 15 points
    """
    # Guard clauses on numeric boundaries
    cgpa = max(0.0, min(10.0, float(cgpa)))
    tenth_pct = max(0.0, min(100.0, float(tenth_pct)))
    twelfth_pct = max(0.0, min(100.0, float(twelfth_pct)))
    backlogs = max(0, int(backlogs))

    # 1. Academic Weight (W_acad: Max 25)
    cgpa_points = (cgpa / 10.0) * 18.0
    schooling_avg = (tenth_pct + twelfth_pct) / 2.0
    if schooling_avg >= 80.0:
        schooling_points = 7.0
    elif schooling_avg >= 60.0:
        schooling_points = 4.0
    else:
        schooling_points = 2.0
    
    backlog_penalty = backlogs * 5.0
    w_acad = max(0.0, min(25.0, cgpa_points + schooling_points - backlog_penalty))

    # 2. Project Weight (W_proj: Max 25)
    if projects_count == 0:
        proj_base = 0.0
    elif projects_count == 1:
        proj_base = 12.0
    elif projects_count == 2:
        proj_base = 20.0
    else:
        proj_base = 22.0
    
    link_bonus = 3.0 if (projects_count > 0 and has_project_links) else 0.0
    w_proj = min(25.0, proj_base + link_bonus)

    # 3. Technical Skills Weight (W_skill: Max 20)
    if isinstance(skills, str):
        skill_list = [s.strip() for s in skills.split(",") if s.strip()]
    else:
        skill_list = list(skills)
    
    skill_count = len(skill_list)
    if skill_count == 0:
        w_skill = 0.0
    elif skill_count in (1, 2):
        w_skill = 8.0
    elif skill_count in (3, 4):
        w_skill = 14.0
    else:
        w_skill = 20.0

    # 4. Internships & Experience Weight (W_exp: Max 15)
    if internships_count == 0:
        w_exp = 0.0
    elif internships_count == 1 and total_internship_months < 3:
        w_exp = 10.0
    else:
        w_exp = 15.0

    # 5. Faculty / TPO Verification Weight (W_ver: Max 15)
    w_ver = 15.0 if is_verified else 0.0

    # Aggregate calculation
    total_rri = round(w_acad + w_proj + w_skill + w_exp + w_ver, 1)
    total_rri = max(0.0, min(100.0, total_rri))

    # Classification
    if total_rri >= 85.0:
        tier = "Placement Ready (Tier 1)"
        tier_color = "emerald"
    elif total_rri >= 70.0:
        tier = "Competitive (Tier 2)"
        tier_color = "blue"
    elif total_rri >= 50.0:
        tier = "Intermediate (Action Needed)"
        tier_color = "amber"
    else:
        tier = "Incomplete Profile"
        tier_color = "rose"

    return {
        "total_rri": total_rri,
        "tier": tier,
        "tier_color": tier_color,
        "breakdown": {
            "w_acad": round(w_acad, 1),
            "w_acad_max": 25,
            "w_proj": round(w_proj, 1),
            "w_proj_max": 25,
            "w_skill": round(w_skill, 1),
            "w_skill_max": 20,
            "w_exp": round(w_exp, 1),
            "w_exp_max": 15,
            "w_ver": round(w_ver, 1),
            "w_ver_max": 15,
        }
    }