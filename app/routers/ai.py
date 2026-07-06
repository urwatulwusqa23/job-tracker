from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.activity_log import ActivityLog
from app.models.application import Application
from app.models.cv import CV
from app.models.interview_prep import InterviewPrep
from app.models.user import User
from app.schemas.ai import (
    ExtractJobRequest,
    ExtractJobResponse,
    JobRecommendationsResponse,
    SkillsGapResponse,
)
from app.schemas.interview_prep import InterviewPrepOut
from app.services.ai_service import (
    ai_extract_job,
    build_interview_prep_prompt,
    build_job_keywords_prompt,
    build_skills_gap_prompt,
    grok,
    parse_json_response,
    require_ai,
)
from app.services.job_board_service import fetch_remotive_jobs

router = APIRouter(prefix="/api", tags=["ai"])


@router.post("/extract_job", response_model=ExtractJobResponse)
def extract_job(payload: ExtractJobRequest, user: User = Depends(get_current_user)):
    client = require_ai()
    if not payload.text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No text provided")
    result = ai_extract_job(client, payload.text)
    if not result:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="AI could not parse the text")
    return ExtractJobResponse(**result)


def _prep_to_out(prep: InterviewPrep) -> InterviewPrepOut:
    extra = prep.extra or {}
    return InterviewPrepOut(
        technical_questions=prep.technical_questions or [],
        behavioral_questions=prep.behavioural_questions or [],
        company_research=extra.get("company_research") or [],
        strengths_to_highlight=extra.get("strengths_to_highlight") or [],
        gaps_to_address=extra.get("gaps_to_address") or [],
        questions_to_ask=extra.get("questions_to_ask") or [],
        salary_negotiation=prep.salary_advice,
        dress_code_tip=extra.get("dress_code_tip"),
        overall_tip=extra.get("overall_tip"),
    )


@router.get("/interview_prep/{app_id}", response_model=InterviewPrepOut)
def get_prep(app_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    app = db.query(Application).filter_by(id=app_id, user_id=user.id).first()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not app.interview_prep:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No prep generated yet")
    return _prep_to_out(app.interview_prep)


@router.post("/interview_prep/{app_id}", response_model=InterviewPrepOut)
def generate_prep(app_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    client = require_ai()

    app = db.query(Application).filter_by(id=app_id, user_id=user.id).first()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    cv = db.query(CV).filter_by(user_id=user.id, is_active=True).first()
    cv_text = cv.extracted_text if cv else "CV not provided"

    prompt = build_interview_prep_prompt(
        role=app.role, company=app.company_name, location=app.location,
        salary=app.salary_expected, job_description=app.job_description, cv_text=cv_text or "",
    )
    try:
        raw = grok(client, prompt, max_tokens=3500)
        result = parse_json_response(raw)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"AI parse error: {e}")

    prep = app.interview_prep or InterviewPrep(application_id=app.id)
    prep.technical_questions = result.get("technical_questions")
    prep.behavioural_questions = result.get("behavioral_questions")
    prep.salary_advice = result.get("salary_negotiation")
    prep.extra = {
        "company_research": result.get("company_research"),
        "strengths_to_highlight": result.get("strengths_to_highlight"),
        "gaps_to_address": result.get("gaps_to_address"),
        "questions_to_ask": result.get("questions_to_ask"),
        "dress_code_tip": result.get("dress_code_tip"),
        "overall_tip": result.get("overall_tip"),
    }
    db.add(prep)
    db.add(ActivityLog(application_id=app.id, action="Interview prep generated"))
    db.commit()
    db.refresh(prep)
    return _prep_to_out(prep)


@router.post("/skills_gap", response_model=SkillsGapResponse)
def skills_gap(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    client = require_ai()

    cv = db.query(CV).filter_by(user_id=user.id, is_active=True).first()
    if not cv:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload your CV first")

    app_rows = (
        db.query(Application)
        .filter(Application.user_id == user.id, Application.job_description.isnot(None))
        .limit(10)
        .all()
    )
    jd_ctx = "\n".join(f"- {a.role}: {(a.job_description or '')[:200]}" for a in app_rows)
    prompt = build_skills_gap_prompt(cv.extracted_text or "", jd_ctx)

    try:
        raw = grok(client, prompt, max_tokens=3500)
        return SkillsGapResponse(**parse_json_response(raw))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"AI parse error: {e}")


@router.post("/job_recommendations", response_model=JobRecommendationsResponse)
def job_recommendations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    client = require_ai()

    cv = db.query(CV).filter_by(user_id=user.id, is_active=True).first()
    if not cv:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload your CV first")

    try:
        raw = grok(client, build_job_keywords_prompt(cv.extracted_text or ""), max_tokens=80)
        keywords = parse_json_response(raw)
    except Exception:
        keywords = ["software developer", "engineer", "developer"]

    jobs = fetch_remotive_jobs(keywords)
    return JobRecommendationsResponse(keywords=keywords, jobs=jobs)
