"""Optional local AI drafts through Ollama (doc §23, §34, Phase 35).

Off by default. When enabled it only talks to a loopback Ollama server, only sees the facts it is
given (the verified resume and the job description), and its output is accepted only if it passes
a grounding check. A draft is never filled automatically: the resolver marks it for review.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

log = logging.getLogger("autofill_agent.ai")

SYSTEM = (
    "You help a job applicant draft an answer to one application question. Use ONLY the facts provided. "
    "If the facts do not support an honest answer, reply with exactly NEEDS_USER_INPUT. "
    "Never invent employers, job titles, dates, numbers, tools, certifications, degrees or outcomes. "
    "Write in the first person, plain text, at most 120 words."
)
_NUMBER = re.compile(r"\d[\d,.]*%?")
_PROPER = re.compile(r"\b[A-Z][A-Za-z0-9+#.\-]{2,}\b")
_COMMON = {"the", "this", "that", "with", "and", "for", "from", "have", "has", "had", "while", "during", "also", "such", "when", "where", "which"}


def facts_from(resume: dict[str, Any], job: dict[str, Any]) -> str:
    lines: list[str] = []
    for p in resume.get("experience") or []:
        end = "present" if p.get("current") else (p.get("end_date") or "?")
        lines.append(f"- {p.get('title') or '?'} at {p.get('company') or '?'} ({p.get('start_date') or '?'} to {end}): {(p.get('description') or '').replace(chr(10), ' ')}")
    if resume.get("skills"):
        lines.append("Skills: " + ", ".join(resume["skills"][:60]))
    for c in resume.get("certifications") or []:
        lines.append(f"Certification: {c.get('name')}")
    for e in resume.get("education") or []:
        lines.append(f"Education: {e.get('degree') or ''} {e.get('field_of_study') or ''}, {e.get('school') or ''}")
    if resume.get("summary"):
        lines.append("Summary: " + resume["summary"])
    jd = (job.get("description") or "")[:4000]
    header = f"Job: {job.get('title') or '?'} at {job.get('company') or '?'}"
    return "\n".join(["RESUME FACTS:", *lines, "", header, f"Job description: {jd}" if jd else ""])


def is_grounded(answer: str, corpus: str) -> bool:
    """Reject drafts that introduce numbers or proper names that are not in the supplied facts."""
    low = corpus.lower()
    if len(answer) > 1500:
        return False
    # Dates like 2020-12 contribute their year only, so a month number cannot vouch for an invented "12".
    known = {n.rstrip(".,%") for n in _NUMBER.findall(re.sub(r"(\d{4})-\d{2}(-\d{2})?", r"\1", corpus))}
    for n in _NUMBER.findall(answer):
        if n.rstrip(".,%") not in known:
            return False
    for sent in re.split(r"(?<=[.!?])\s+|\n", answer):
        words = sent.split()
        for w in words[1:]:  # the first word of a sentence is capitalised anyway
            m = _PROPER.fullmatch(w.strip(".,;:()\"'"))
            if m and m.group(0).lower() not in _COMMON and m.group(0).lower() not in low:
                return False
    return True


class OllamaDrafter:
    def __init__(self, url: str, model: str, timeout: float = 90.0, client: httpx.Client | None = None) -> None:
        self.url, self.model = url.rstrip("/"), model
        self._client = client or httpx.Client(timeout=timeout)

    def __call__(self, topic: str | None, question: str, resume: dict[str, Any], job: dict[str, Any]) -> str | None:
        facts = facts_from(resume, job)
        prompt = f"{facts}\n\nQuestion: {question}\n" + (f"Focus: {topic}\n" if topic else "") + "Answer:"
        try:
            r = self._client.post(f"{self.url}/api/generate", json={
                "model": self.model, "system": SYSTEM, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}})
            r.raise_for_status()
            text = (r.json().get("response") or "").strip()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("Local AI unavailable (%s)", type(e).__name__)
            return None
        if not text or "NEEDS_USER_INPUT" in text:
            return None
        if not is_grounded(text, facts + "\n" + question):
            log.info("Discarded an AI draft that was not grounded in the resume")
            return None
        return text
