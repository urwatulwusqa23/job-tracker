from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.activity_log import ActivityLog
    from app.models.cv import CV
    from app.models.interview_prep import InterviewPrep
    from app.models.user import User


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        # Speeds up the /api/stats per-status counts and the follow-up-needed query
        Index("ix_applications_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    company_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="Applied")
    date_applied: Mapped[str | None] = mapped_column(String, nullable=True)
    salary_expected: Mapped[str | None] = mapped_column(String, nullable=True)
    job_url: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Extra columns kept for feature parity (AI prompts, Gmail auto-import, CV linking)
    job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String, default="Manual")
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    cv_id: Mapped[int | None] = mapped_column(ForeignKey("cvs.id", ondelete="SET NULL"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="applications")
    cv: Mapped["CV | None"] = relationship(back_populates="applications")
    interview_prep: Mapped["InterviewPrep | None"] = relationship(
        back_populates="application", cascade="all, delete-orphan", uselist=False
    )
    activity_logs: Mapped[list["ActivityLog"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
