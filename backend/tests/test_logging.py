import logging

from autofill_agent.logging_setup import configure_logging, redact


def test_redacts_pii_and_secrets():
    s = redact("mail jane.doe@example.com call (555) 123-4567 Authorization: Bearer abc.def-123 ssn 123-45-6789")
    assert "jane.doe" not in s and "555" not in s and "abc.def" not in s and "123-45-6789" not in s
    assert "[EMAIL]" in s and "[PHONE]" in s and "[SSN]" in s


def test_log_file_is_redacted(tmp_path):
    configure_logging(tmp_path, "INFO")
    logging.getLogger("autofill_agent.test").info("filled %s", "jane@example.com")
    for h in logging.getLogger("autofill_agent").handlers:
        h.flush()
    assert "jane@example.com" not in (tmp_path / "agent.log").read_text()
