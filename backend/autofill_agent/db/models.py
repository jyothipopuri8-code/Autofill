"""SQLAlchemy models for the local store (doc §6–§11, §24, §31, §33).

Facts the agent must never infer (work authorization, sensitive
characteristics) are nullable: ``None`` means "unknown, ask the user",
which is distinct from an explicit ``False``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from autofill_agent.db.enums import (
    AnswerSource,
    ApplicationStatus,
    AtsProvider,
    FieldOwnership,
    FieldStatus,
    ResumeStatus,
    SensitiveField,
    SensitivePolicy,
    SessionStatus,
    VerificationStatus,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enum(e: type) -> Enum:
    # Store enum values as plain strings so the database stays readable.
    return Enum(e, native_enum=False, validate_strings=True, length=32)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# --- Fixed profile -----------------------------------------------------------


class Profile(TimestampMixin, Base):
    """Fixed information that normally stays the same across applications (doc §6).

    There is a single profile per installation (id is always 1).
    """

    __tablename__ = "profile"
    __table_args__ = (CheckConstraint("id = 1", name="single_profile"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)

    # Personal
    first_name: Mapped[str | None] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    preferred_name: Mapped[str | None] = mapped_column(String(100))
    pronouns: Mapped[str | None] = mapped_column(String(50))

    # Contact
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    phone_country_code: Mapped[str | None] = mapped_column(String(8))
    phone_device_type: Mapped[str | None] = mapped_column(String(20))
    phone_extension: Mapped[str | None] = mapped_column(String(10))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    portfolio_url: Mapped[str | None] = mapped_column(String(500))
    github_url: Mapped[str | None] = mapped_column(String(500))
    website_url: Mapped[str | None] = mapped_column(String(500))

    # Location
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))

    # Work authorization: None = not provided, never inferred (doc §21)
    authorized_to_work_us: Mapped[bool | None]
    require_sponsorship_now: Mapped[bool | None]
    require_sponsorship_future: Mapped[bool | None]
    work_authorization_verified: Mapped[bool] = mapped_column(default=False)

    # Application preferences
    willing_to_relocate: Mapped[bool | None]
    travel_willingness: Mapped[str | None] = mapped_column(String(100))
    remote_preference: Mapped[bool | None]
    hybrid_preference: Mapped[bool | None]
    onsite_preference: Mapped[bool | None]
    available_start_date: Mapped[date | None] = mapped_column(Date)
    referral_source: Mapped[str | None] = mapped_column(String(200))


class SensitivePreference(TimestampMixin, Base):
    """Explicit policy for one sensitive field (doc §7). Default is ASK_ME."""

    __tablename__ = "sensitive_preference"

    id: Mapped[int] = mapped_column(primary_key=True)
    field: Mapped[SensitiveField] = mapped_column(_enum(SensitiveField), unique=True)
    policy: Mapped[SensitivePolicy] = mapped_column(_enum(SensitivePolicy), default=SensitivePolicy.ASK_ME)
    # Only used when policy is AUTOFILL; the user's own wording.
    value: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        CheckConstraint("policy != 'NEVER_FILL' OR value IS NULL", name="never_fill_has_no_value"),
    )


# --- Resumes -----------------------------------------------------------------


class Resume(TimestampMixin, Base):
    """One tailored resume file (doc §9). Identified by its SHA-256 (doc §5 step 5)."""

    __tablename__ = "resume"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[ResumeStatus] = mapped_column(_enum(ResumeStatus), default=ResumeStatus.UPLOADED)
    is_current: Mapped[bool] = mapped_column(default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Raw parser output and the user-corrected version (doc §5 step 4).
    # Structure: contact, summary, skills, experience[], education[],
    # certifications[], languages[]. Dates as YYYY-MM or YYYY-MM-DD (doc §20).
    parsed_data: Mapped[dict[str, Any] | None]
    verified_data: Mapped[dict[str, Any] | None]

    applications: Mapped[list[Application]] = relationship(back_populates="resume")

    __table_args__ = (
        CheckConstraint("length(sha256) = 64", name="sha256_hex_length"),
        # At most one current resume at a time.
        Index("one_current_resume", "is_current", unique=True, sqlite_where=text("is_current = 1")),
    )


# --- Answer library ----------------------------------------------------------


class LibraryAnswer(TimestampMixin, Base):
    """Reusable canonical answer, e.g. desired salary or relocation (doc §11)."""

    __tablename__ = "library_answer"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    # Canonical key from the field taxonomy, e.g. "desired_salary".
    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[str | None] = mapped_column(Text)
    policy: Mapped[SensitivePolicy] = mapped_column(_enum(SensitivePolicy), default=SensitivePolicy.ASK_ME)
    verification: Mapped[VerificationStatus] = mapped_column(
        _enum(VerificationStatus), default=VerificationStatus.UNVERIFIED
    )
    notes: Mapped[str | None] = mapped_column(Text)


class ApprovedAnswer(TimestampMixin, Base):
    """Question memory: an answer the user approved for a specific question (doc §24).

    ``profile_version`` and ``resume_sha256`` record what the answer depended
    on, so it can be invalidated when those change.
    """

    __tablename__ = "approved_answer"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_field: Mapped[str | None] = mapped_column(String(100), index=True)
    question_text: Mapped[str] = mapped_column(Text)
    question_hash: Mapped[str] = mapped_column(String(64), index=True)
    answer: Mapped[str] = mapped_column(Text)
    resume_sha256: Mapped[str | None] = mapped_column(String(64))
    profile_version: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded: Mapped[bool] = mapped_column(default=False)
    # Scope of reuse (doc §24): job-specific questions are tied to a company; resume/profile-derived
    # answers are dropped when that resume or profile changes.
    company: Mapped[str | None] = mapped_column(String(200))
    depends_on_resume: Mapped[bool] = mapped_column(default=False)
    depends_on_profile: Mapped[bool] = mapped_column(default=False)
    source_session_id: Mapped[int | None] = mapped_column(ForeignKey("application_session.id", ondelete="SET NULL"))


# --- Applications and sessions ----------------------------------------------


class Application(TimestampMixin, Base):
    """One job application and its history record (doc §33)."""

    __tablename__ = "application"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str | None] = mapped_column(String(200), index=True)
    job_title: Mapped[str | None] = mapped_column(String(200))
    job_id: Mapped[str | None] = mapped_column(String(100), index=True)
    job_url: Mapped[str | None] = mapped_column(String(2048), index=True)
    location: Mapped[str | None] = mapped_column(String(200))
    job_description: Mapped[str | None] = mapped_column(Text)
    ats: Mapped[AtsProvider] = mapped_column(_enum(AtsProvider), default=AtsProvider.UNKNOWN)
    status: Mapped[ApplicationStatus] = mapped_column(_enum(ApplicationStatus), default=ApplicationStatus.STARTED)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # The exact resume this application expects (doc §10). Filename and hash
    # are snapshotted so history survives deleting the resume record.
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resume.id", ondelete="SET NULL"))
    resume_filename: Mapped[str | None] = mapped_column(String(255))
    resume_sha256: Mapped[str | None] = mapped_column(String(64))

    resume: Mapped[Resume | None] = relationship(back_populates="applications")
    sessions: Mapped[list[ApplicationSession]] = relationship(
        back_populates="application", cascade="all, delete-orphan", passive_deletes=True
    )


class ApplicationSession(TimestampMixin, Base):
    """Isolated, recoverable working state for filling one application (doc §31, §32)."""

    __tablename__ = "application_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"), index=True)
    status: Mapped[SessionStatus] = mapped_column(_enum(SessionStatus), default=SessionStatus.ACTIVE)
    current_page_url: Mapped[str | None] = mapped_column(String(2048))
    current_page_index: Mapped[int] = mapped_column(default=0)
    detected_fields: Mapped[list[Any]] = mapped_column(default=list)
    errors: Mapped[list[Any]] = mapped_column(default=list)
    # canonical_field -> value chosen by the user for this application only (answers and conflict resolutions).
    overrides: Mapped[dict[str, Any]] = mapped_column(default=dict)

    application: Mapped[Application] = relationship(back_populates="sessions")
    answers: Mapped[list[SessionAnswer]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )


class SessionAnswer(TimestampMixin, Base):
    """The proposed/approved answer for one field within one session."""

    __tablename__ = "session_answer"
    __table_args__ = (
        UniqueConstraint("session_id", "page_index", "field_key", name="one_answer_per_field"),
        CheckConstraint("confidence IS NULL OR (confidence BETWEEN 0 AND 100)", name="confidence_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("application_session.id", ondelete="CASCADE"), index=True)
    page_index: Mapped[int] = mapped_column(default=0)
    # Stable identifier of the DOM field from the extension.
    field_key: Mapped[str] = mapped_column(String(500))
    label: Mapped[str | None] = mapped_column(Text)
    canonical_field: Mapped[str | None] = mapped_column(String(100))
    required: Mapped[bool] = mapped_column(default=False)

    proposed_value: Mapped[str | None] = mapped_column(Text)
    final_value: Mapped[str | None] = mapped_column(Text)
    # True when the user typed or chose this value in this application; it then wins over everything.
    user_override: Mapped[bool] = mapped_column(default=False)
    source: Mapped[AnswerSource] = mapped_column(_enum(AnswerSource), default=AnswerSource.NONE)
    confidence: Mapped[int | None]
    status: Mapped[FieldStatus] = mapped_column(_enum(FieldStatus), default=FieldStatus.PENDING)
    ownership: Mapped[FieldOwnership] = mapped_column(_enum(FieldOwnership), default=FieldOwnership.EMPTY)

    # Repeatable sections (work experience, education, ...) and how the engine decided to treat the field.
    section: Mapped[str | None] = mapped_column(String(32))
    section_index: Mapped[int | None]
    action: Mapped[str] = mapped_column(String(16), default="ask")  # fill | review | ask | skip | keep | user_action | attach | conflict
    reason: Mapped[str | None] = mapped_column(Text)
    sensitive: Mapped[bool] = mapped_column(default=False)
    band: Mapped[str | None] = mapped_column(String(16))  # READY | REVIEW | DO_NOT_FILL
    # Full engine result for this field as last analyzed (used to validate after filling).
    result: Mapped[dict[str, Any] | None]

    session: Mapped[ApplicationSession] = relationship(back_populates="answers")


class AppSetting(Base):
    """Small key/value store for agent settings such as the operating mode (doc §29)."""

    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
