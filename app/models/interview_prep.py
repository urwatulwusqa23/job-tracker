from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.application import Application


class InterviewPrep(Base):
    __tablename__ = "interview_preps"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    technical_questions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    behavioural_questions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    salary_advice: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Remaining AI-generated fields kept for feature parity (company research, strengths,
    # gaps, questions to ask, dress code tip, overall tip) — grouped here rather than as
    # individual columns since they're display-only and not queried on.
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    application: Mapped["Application"] = relationship(back_populates="interview_prep")
