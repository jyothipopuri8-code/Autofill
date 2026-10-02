"""Structured resume data (doc §8, §16-§20).

Used for parser output and for the user's verified/corrected version. Dates are
``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD`` (doc §20); ``None`` means unknown, never a guess.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

_DATE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$")
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
_URL = re.compile(r"^https?://[^\s/]+\.[^\s/]+(/\S*)?$")

Text = Annotated[str, StringConstraints(strip_whitespace=True)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _blank_to_none(cls, data):
        if isinstance(data, dict):
            return {k: (None if isinstance(v, str) and not v.strip() else v) for k, v in data.items()}
        return data


def _date(v: str | None) -> str | None:
    if v is not None and not _DATE.match(v):
        raise ValueError("date must be YYYY, YYYY-MM or YYYY-MM-DD")
    return v


class Contact(_Base):
    full_name: Text | None = Field(None, max_length=200)
    first_name: Text | None = Field(None, max_length=100)
    last_name: Text | None = Field(None, max_length=100)
    email: Text | None = Field(None, max_length=254)
    phone: Text | None = Field(None, max_length=40)
    location: Text | None = Field(None, max_length=200)
    linkedin_url: Text | None = Field(None, max_length=500)
    github_url: Text | None = Field(None, max_length=500)
    website_url: Text | None = Field(None, max_length=500)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if v is not None and not _EMAIL.match(v):
            raise ValueError("not a valid email address")
        return v

    @field_validator("linkedin_url", "github_url", "website_url")
    @classmethod
    def _url(cls, v):
        if v is not None and not _URL.match(v):
            raise ValueError("must be an http(s) URL")
        return v


class Experience(_Base):
    title: Text | None = Field(None, max_length=200)
    company: Text | None = Field(None, max_length=200)
    location: Text | None = Field(None, max_length=200)
    start_date: Text | None = None
    end_date: Text | None = None
    current: bool = False
    description: Text | None = Field(None, max_length=8000)

    _d = field_validator("start_date", "end_date")(lambda cls, v: _date(v))

    @model_validator(mode="after")
    def _current_has_no_end(self):
        if self.current and self.end_date is not None:
            raise ValueError("a current position cannot have an end date")
        return self


class Education(_Base):
    school: Text | None = Field(None, max_length=200)
    degree: Text | None = Field(None, max_length=200)
    field_of_study: Text | None = Field(None, max_length=200)
    start_date: Text | None = None
    graduation_date: Text | None = None
    expected_graduation_date: Text | None = None

    _d = field_validator("start_date", "graduation_date", "expected_graduation_date")(lambda cls, v: _date(v))


class Certification(_Base):
    name: Text | None = Field(None, max_length=200)
    number: Text | None = Field(None, max_length=100)
    issued_date: Text | None = None
    expiration_date: Text | None = None

    _d = field_validator("issued_date", "expiration_date")(lambda cls, v: _date(v))


class Language(_Base):
    language: Text | None = Field(None, max_length=60)
    proficiency: Text | None = Field(None, max_length=60)


class ResumeData(_Base):
    """What the user verifies and corrects."""

    contact: Contact = Field(default_factory=Contact)
    summary: Text | None = Field(None, max_length=8000)
    skills: list[Annotated[Text, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=300)
    experience: list[Experience] = Field(default_factory=list, max_length=50)
    education: list[Education] = Field(default_factory=list, max_length=20)
    certifications: list[Certification] = Field(default_factory=list, max_length=50)
    languages: list[Language] = Field(default_factory=list, max_length=30)


class ParsedResume(ResumeData):
    """Parser output: the data plus notes on what could not be determined."""

    warnings: list[str] = Field(default_factory=list)
