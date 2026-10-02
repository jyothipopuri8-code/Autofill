import pytest
from sqlalchemy.exc import IntegrityError

from autofill_agent.db.enums import (
    AnswerSource,
    ApplicationStatus,
    SensitiveField,
    SensitivePolicy,
)
from autofill_agent.db.models import (
    Application,
    ApplicationSession,
    LibraryAnswer,
    Profile,
    Resume,
    SensitivePreference,
    SessionAnswer,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def make_resume(sha=SHA_A, **kw):
    return Resume(filename="r.pdf", stored_path="/x/r.pdf", sha256=sha, mime_type="application/pdf", size_bytes=10, **kw)


def test_profile_unknown_is_none_not_false(db):
    with db.session() as s:
        s.add(Profile(first_name="Jane"))
    with db.session() as s:
        p = s.get(Profile, 1)
        assert p.authorized_to_work_us is None and p.require_sponsorship_now is None
        assert p.work_authorization_verified is False


def test_single_profile_only(db):
    with pytest.raises(IntegrityError):
        with db.session() as s:
            s.add(Profile(id=2))


def test_sensitive_preference_defaults_and_constraints(db):
    with db.session() as s:
        s.add(SensitivePreference(field=SensitiveField.GENDER))
    with db.session() as s:
        assert s.query(SensitivePreference).one().policy is SensitivePolicy.ASK_ME
    with pytest.raises(IntegrityError):
        with db.session() as s:
            s.add(SensitivePreference(field=SensitiveField.RACE, policy=SensitivePolicy.NEVER_FILL, value="x"))
    with pytest.raises(IntegrityError):  # one row per field
        with db.session() as s:
            s.add(SensitivePreference(field=SensitiveField.GENDER))


def test_resume_hash_unique_and_single_current(db):
    with db.session() as s:
        s.add(make_resume(is_current=True))
    with pytest.raises(IntegrityError):
        with db.session() as s:
            s.add(make_resume(sha=SHA_A))
    with pytest.raises(IntegrityError):
        with db.session() as s:
            s.add(make_resume(sha=SHA_B, is_current=True))
    with db.session() as s:
        s.add(make_resume(sha=SHA_B, is_current=False))


def test_resume_parsed_data_roundtrip(db):
    data = {"contact": {"email": "a@b.co"}, "experience": [{"title": "Eng", "start": "2020-01"}]}
    with db.session() as s:
        s.add(make_resume(parsed_data=data))
    with db.session() as s:
        assert s.query(Resume).one().parsed_data == data


def test_application_session_answers_and_cascade(db):
    with db.session() as s:
        r = make_resume()
        s.add(r)
        s.flush()
        app = Application(company="Acme", job_title="Eng", resume_id=r.id, resume_filename=r.filename, resume_sha256=r.sha256)
        sess = ApplicationSession(application=app)
        sess.answers.append(SessionAnswer(field_key="#fname", canonical_field="first_name", source=AnswerSource.PROFILE, confidence=99))
        s.add(app)
    with db.session() as s:
        app = s.query(Application).one()
        assert app.status is ApplicationStatus.STARTED
        assert len(app.sessions) == 1 and app.sessions[0].answers[0].proposed_value is None
        assert app.sessions[0].detected_fields == []
        s.delete(app)
    with db.session() as s:
        assert s.query(ApplicationSession).count() == 0 and s.query(SessionAnswer).count() == 0


def test_deleting_resume_keeps_application_history(db):
    with db.session() as s:
        r = make_resume()
        s.add(r)
        s.flush()
        s.add(Application(company="Acme", resume_id=r.id, resume_sha256=r.sha256, resume_filename="r.pdf"))
    with db.session() as s:
        s.delete(s.query(Resume).one())
    with db.session() as s:
        a = s.query(Application).one()
        assert a.resume_id is None and a.resume_sha256 == SHA_A


def test_session_answer_constraints(db):
    with db.session() as s:
        app = Application(company="Acme")
        sess = ApplicationSession(application=app)
        s.add(sess)
        s.flush()
        sid = sess.id
        s.add(SessionAnswer(session_id=sid, field_key="f1"))
    with pytest.raises(IntegrityError):
        with db.session() as s:
            s.add(SessionAnswer(session_id=sid, field_key="f1"))
    with pytest.raises(IntegrityError):
        with db.session() as s:
            s.add(SessionAnswer(session_id=sid, field_key="f2", confidence=101))


def test_library_answer_key_unique(db):
    with db.session() as s:
        s.add(LibraryAnswer(category="compensation", key="desired_salary", value="150000"))
    with pytest.raises(IntegrityError):
        with db.session() as s:
            s.add(LibraryAnswer(category="compensation", key="desired_salary"))


def test_foreign_keys_enforced(db):
    with pytest.raises(IntegrityError):
        with db.session() as s:
            s.add(ApplicationSession(application_id=999))
