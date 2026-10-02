"""What the browser extension reports about each form control (doc §12)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from autofill_agent.db.enums import FieldOwnership


def _trunc(limit: int):
    def inner(v):
        return v[:limit] if isinstance(v, str) else v

    return BeforeValidator(inner)


Short = Annotated[str | None, _trunc(300)]
Long = Annotated[str | None, _trunc(1000)]

Kind = Literal[
    "text", "email", "tel", "number", "url", "textarea", "select", "custom_select",
    "radio_group", "checkbox", "checkbox_group", "date", "month_year", "autocomplete",
    "file", "password", "captcha", "unknown",
]


class Option(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: Annotated[str, _trunc(300)] = ""
    label: Annotated[str, _trunc(300)] = ""


class SectionRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: Literal["experience", "education", "certification", "language"]
    index: int = Field(0, ge=0, le=50)


class FieldDescriptor(BaseModel):
    """One detected control. Checkbox/radio groups are reported as a single field with ``options``."""

    model_config = ConfigDict(extra="ignore")

    key: Annotated[str, Field(min_length=1, max_length=500)]
    kind: Kind = "unknown"
    label: Short = None
    name: Short = None
    id: Short = None
    placeholder: Short = None
    aria_label: Short = None
    autocomplete: Short = None
    input_type: Short = None
    nearby_text: Long = None
    legend: Long = None
    options: list[Option] = Field(default_factory=list, max_length=500)
    required: bool = False
    current_value: Annotated[str | None, _trunc(2000)] = None
    ownership: FieldOwnership = FieldOwnership.EMPTY
    section: SectionRef | None = None
    date_format: Short = None
    maxlength: int | None = Field(None, ge=0, le=100000)
    visible: bool = True
    disabled: bool = False
