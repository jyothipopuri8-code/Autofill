"""Enumerations shared by the data model, taken from the design doc."""

from __future__ import annotations

import enum


class SensitivePolicy(str, enum.Enum):
    """How a sensitive or policy-governed answer may be used (doc §7, §11)."""

    AUTOFILL = "AUTOFILL"
    ASK_ME = "ASK_ME"
    NEVER_FILL = "NEVER_FILL"


class SensitiveField(str, enum.Enum):
    GENDER = "gender"
    RACE = "race"
    ETHNICITY = "ethnicity"
    HISPANIC_LATINO = "hispanic_latino"
    DISABILITY_STATUS = "disability_status"
    MEDICAL_ACCOMMODATION = "medical_accommodation"
    VETERAN_STATUS = "veteran_status"


class VerificationStatus(str, enum.Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class ResumeStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    PARSED = "PARSED"
    VERIFIED = "VERIFIED"


class ApplicationStatus(str, enum.Enum):
    """User-controlled lifecycle of an application (doc §33)."""

    STARTED = "STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    SUBMITTED = "SUBMITTED"
    INTERVIEW = "INTERVIEW"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    OFFER = "OFFER"


class SessionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class AtsProvider(str, enum.Enum):
    GENERIC = "GENERIC"
    GREENHOUSE = "GREENHOUSE"
    LEVER = "LEVER"
    WORKDAY = "WORKDAY"
    ASHBY = "ASHBY"
    ICIMS = "ICIMS"
    SMARTRECRUITERS = "SMARTRECRUITERS"
    UNKNOWN = "UNKNOWN"


class AnswerSource(str, enum.Enum):
    """Where a proposed answer came from, in resolution priority order (doc §5 step 12)."""

    USER_CURRENT = "USER_CURRENT"
    PROFILE = "PROFILE"
    RESUME = "RESUME"
    APPROVED_ANSWER = "APPROVED_ANSWER"
    CALCULATED = "CALCULATED"
    AI_DRAFT = "AI_DRAFT"
    NONE = "NONE"


class FieldStatus(str, enum.Enum):
    """Validation classification of a field (doc §17, §38)."""

    PENDING = "PENDING"
    FILLED = "FILLED"
    MISSING_REQUIRED = "MISSING_REQUIRED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
    FAILED_TO_FILL = "FAILED_TO_FILL"
    SKIPPED = "SKIPPED"
    OPTIONAL_EMPTY = "OPTIONAL_EMPTY"


class FieldOwnership(str, enum.Enum):
    """Who controls a field's current value (doc §27)."""

    EMPTY = "EMPTY"
    SITE_DEFAULT = "SITE_DEFAULT"
    AGENT_FILLED = "AGENT_FILLED"
    USER_FILLED = "USER_FILLED"
    USER_MODIFIED_AGENT_VALUE = "USER_MODIFIED_AGENT_VALUE"
