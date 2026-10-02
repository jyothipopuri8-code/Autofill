import json

import httpx
import pytest
from pydantic import ValidationError

from autofill_agent.ai import OllamaDrafter, is_grounded
from autofill_agent.config import Settings
from autofill_agent.db.enums import AnswerSource
from autofill_agent.engine.descriptor import FieldDescriptor
from autofill_agent.engine.resolver import resolve_field
from tests.test_resolver import RESUME, ctx

JOB = {"title": "Security Engineer", "company": "CrowdStrike", "description": "Detect and respond to threats at scale."}


def drafter(response_text=None, status=200, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
            seen.append(str(request.url))
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json={"response": response_text})

    return OllamaDrafter("http://127.0.0.1:11434", "m", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_grounded_draft_is_returned_and_prompt_contains_only_given_facts():
    seen = []
    d = drafter("I built SIEM detection pipelines in Splunk at CrowdStrike and led incident response.", seen=seen)
    out = d(None, "Why are you interested in this role?", RESUME, JOB)
    assert out.startswith("I built SIEM")
    body, url = seen
    assert url == "http://127.0.0.1:11434/api/generate" and body["stream"] is False
    assert "Never invent" in body["system"] and "Senior Security Engineer at CrowdStrike" in body["prompt"]
    assert "jane.doe@example.com" not in body["prompt"] and "555" not in body["prompt"]  # contact details are not sent


@pytest.mark.parametrize("text", [
    "NEEDS_USER_INPUT",
    "I increased revenue by 340% at Initech.",            # invented number and employer
    "I led a team of 12 engineers.",                      # invented number
    "I hold an AWS Solutions Architect certification.",   # AWS appears in the resume? no: Architect/Solutions are not
    "",
])
def test_ungrounded_or_refusing_drafts_are_dropped(text):
    assert drafter(text)(None, "Describe your leadership experience", RESUME, JOB) is None


def test_failures_degrade_to_no_draft():
    assert drafter(status=500)(None, "q", RESUME, JOB) is None

    def boom(request):
        raise httpx.ConnectError("refused")

    d = OllamaDrafter("http://127.0.0.1:11434", "m", client=httpx.Client(transport=httpx.MockTransport(boom)))
    assert d(None, "q", RESUME, JOB) is None


def test_is_grounded_rules():
    corpus = "Built pipelines in Splunk at CrowdStrike for 3 years"
    assert is_grounded("I built pipelines in Splunk at CrowdStrike for 3 years.", corpus)
    assert not is_grounded("I built pipelines in Splunk for 5 years.", corpus)
    assert not is_grounded("I used Kubernetes daily.", corpus)
    assert not is_grounded("x" * 2000, corpus)


def test_only_local_ollama_urls_are_accepted(tmp_path):
    Settings(ollama_url="http://localhost:11434", data_dir=tmp_path, _env_file=None)
    for bad in ("https://api.example.com", "http://192.168.1.5:11434", "http://127.0.0.1.evil.com", "http://evil.com/127.0.0.1"):
        with pytest.raises(ValidationError):
            Settings(ollama_url=bad, data_dir=tmp_path, _env_file=None)


def test_resolver_uses_ai_only_for_free_text_and_never_auto_fills():
    q = FieldDescriptor(key="k", kind="textarea", label="Why are you interested in this role?", required=True)
    c = ctx(ai=lambda topic, question, resume, job: "I enjoy detection work.")
    r = resolve_field(q, c)
    assert r.source is AnswerSource.AI_DRAFT and r.value == "I enjoy detection work." and r.action == "confirm" and r.band == "DO_NOT_FILL"
    assert resolve_field(q.model_copy(update={"kind": "text"}), c).action == "ask"      # short fields: no AI
    assert resolve_field(q, ctx(ai=lambda *a: None)).action == "ask"                    # AI declined
    assert resolve_field(q, ctx(ai=lambda *a: "x", resume_blocked="mismatch")).action == "ask"  # blocked resume: no AI
    # A question the resume can answer deterministically does not call the AI at all
    called = []
    spy = lambda *a: called.append(1) or "x"
    resolve_field(FieldDescriptor(key="k", kind="textarea", label="Describe your Splunk experience"), ctx(ai=spy))
    assert not called


def test_ai_is_off_by_default(client):
    assert client.app.state.ai is None
