"""Request/response schemas for the profile, answer library and resume APIs."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from autofill_agent.db.enums import (
    ResumeStatus,
    SensitiveField,
    SensitivePolicy,
    VerificationStatus,
)

_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
_PHONE = re.compile(r"^[0-9+()\-.\s]{7,40}$")
_POSTAL = re.compile(r"^[A-Za-z0-9 -]{2,20}$")
_KEY = re.compile(r"^[a-z][a-z0-9_]{1,99}$")

Str = Annotated[str, StringConstraints(strip_whitespace=True)]


def _blank_to_none(v):
    """An empty string means "clear this field"."""
    if isinstance(v, str) and not v.strip():
        return None
    return v


def _check_url(v: str | None) -> str | None:
    if v is not None and not re.match(r"^https?://[^\s/]+\.[^\s/]+(/\S*)?$", v):
        raise ValueError("must be an http(s) URL")
    return v


# --- Profile -----------------------------------------------------------------


class ProfileIn(BaseModel):
    """Partial update: only fields present in the request are changed; null/"" clears."""

    model_config = ConfigDict(extra="forbid")

    first_name: Str | None = Field(None, max_length=100)
    middle_name: Str | None = Field(None, max_length=100)
    last_name: Str | None = Field(None, max_length=100)
    preferred_name: Str | None = Field(None, max_length=100)
    pronouns: Str | None = Field(None, max_length=50)

    email: Str | None = Field(None, max_length=254)
    phone: Str | None = Field(None, max_length=40)
    phone_country_code: Str | None = Field(None, max_length=8)
    phone_device_type: Str | None = Field(None, max_length=20)
    phone_extension: Str | None = Field(None, max_length=10)
    linkedin_url: Str | None = Field(None, max_length=500)
    portfolio_url: Str | None = Field(None, max_length=500)
    github_url: Str | None = Field(None, max_length=500)
    website_url: Str | None = Field(None, max_length=500)

    address_line1: Str | None = Field(None, max_length=200)
    address_line2: Str | None = Field(None, max_length=200)
    city: Str | None = Field(None, max_length=100)
    state: Str | None = Field(None, max_length=100)
    country: Str | None = Field(None, max_length=100)
    postal_code: Str | None = Field(None, max_length=20)

    authorized_to_work_us: bool | None = None
    require_sponsorship_now: bool | None = None
    require_sponsorship_future: bool | None = None
    work_authorization_verified: bool | None = None

    willing_to_relocate: bool | None = None
    travel_willingness: Str | None = Field(None, max_length=100)
    remote_preference: bool | None = None
    hybrid_preference: bool | None = None
    onsite_preference: bool | None = None
    available_start_date: date | None = None
    referral_source: Str | None = Field(None, max_length=200)

    @model_validator(mode="before")
    @classmethod
    def _blanks(cls, data):
        if isinstance(data, dict):
            return {k: _blank_to_none(v) for k, v in data.items()}
        return data

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v is not None and not _EMAIL.match(v):
            raise ValueError("not a valid email address")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        if v is not None and not _PHONE.match(v):
            raise ValueError("not a valid phone number")
        return v

    @field_validator("phone_country_code")
    @classmethod
    def _cc(cls, v):
        if v is not None and not re.match(r"^\+?\d{1,4}$", v):
            raise ValueError("expected a country calling code such as +1")
        return v

    @field_validator("phone_device_type")
    @classmethod
    def _device(cls, v):
        if v is not None and v.lower() not in {"mobile", "home", "work"}:
            raise ValueError("must be mobile, home or work")
        return v.lower() if v else v

    @field_validator("phone_extension")
    @classmethod
    def _ext(cls, v):
        if v is not None and not v.isdigit():
            raise ValueError("extension must be digits")
        return v

    @field_validator("postal_code")
    @classmethod
    def _postal(cls, v):
        if v is not None and not _POSTAL.match(v):
            raise ValueError("not a valid postal code")
        return v

    @field_validator("linkedin_url", "portfolio_url", "github_url", "website_url")
    @classmethod
    def _urls(cls, v):
        return _check_url(v)


class ProfileOut(ProfileIn):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    created_at: datetime | None = None
    updated_at: datetime | None = None


class SensitivePrefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: SensitivePolicy
    value: Str | None = Field(None, max_length=200)

    @model_validator(mode="before")
    @classmethod
    def _blanks(cls, data):
        if isinstance(data, dict):
            return {k: _blank_to_none(v) for k, v in data.items()}
        return data

    @model_validator(mode="after")
    def _value_matches_policy(self):
        if self.policy is SensitivePolicy.AUTOFILL and not self.value:
            raise ValueError("AUTOFILL requires an explicit value")
        if self.policy is not SensitivePolicy.AUTOFILL and self.value is not None:
            raise ValueError("value may only be stored with the AUTOFILL policy")
        return self


class SensitivePrefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field: SensitiveField
    policy: SensitivePolicy = SensitivePolicy.ASK_ME
    value: str | None = None
    updated_at: datetime | None = None


# --- Answer library ----------------------------------------------------------


class LibraryAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Str = Field(min_length=1, max_length=64)
    value: Str | None = Field(None, max_length=4000)
    policy: SensitivePolicy = SensitivePolicy.ASK_ME
    verification: VerificationStatus = VerificationStatus.UNVERIFIED
    notes: Str | None = Field(None, max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def _blanks(cls, data):
        if isinstance(data, dict):
            return {k: _blank_to_none(v) if k != "category" else v for k, v in data.items()}
        return data

    @model_validator(mode="after")
    def _rules(self):
        if self.policy is SensitivePolicy.AUTOFILL and not self.value:
            raise ValueError("AUTOFILL requires a value")
        if self.verification is VerificationStatus.VERIFIED and not self.value:
            raise ValueError("an answer without a value cannot be VERIFIED")
        return self


class LibraryAnswerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    category: str
    value: str | None
    policy: SensitivePolicy
    verification: VerificationStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


def valid_answer_key(key: str) -> bool:
    return bool(_KEY.match(key))


# --- Resumes -----------------------------------------------------------------


class ResumeOut(BaseModel):
    """Deliberately omits the on-disk path."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    sha256: str
    mime_type: str
    size_bytes: int
    status: ResumeStatus
    is_current: bool
    uploaded_at: datetime
    parsed_at: datetime | None
    verified_at: datetime | None
    archived_at: datetime | None


class ResumeIntegrityOut(BaseModel):
    id: int
    file_exists: bool
    sha256_matches: bool
    expected_sha256: str
    actual_sha256: str | None
