from pydantic import BaseModel

# Wire format matches the original flat prep_json structure the frontend already renders.


class QAItem(BaseModel):
    question: str
    ideal_answer: str | None = None
    tip: str | None = None


class GapItem(BaseModel):
    gap: str
    how_to_handle: str | None = None


class InterviewPrepOut(BaseModel):
    technical_questions: list[QAItem] = []
    behavioral_questions: list[QAItem] = []
    company_research: list[str] = []
    strengths_to_highlight: list[str] = []
    gaps_to_address: list[GapItem] = []
    questions_to_ask: list[str] = []
    salary_negotiation: str | None = None
    dress_code_tip: str | None = None
    overall_tip: str | None = None
