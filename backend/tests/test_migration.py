import sqlite3

from autofill_agent.db import Database
from autofill_agent.db.models import ApplicationSession, Application


def test_adds_columns_missing_from_older_database(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    # A phase-3 era table: no `overrides` column.
    con.executescript(
        """
        CREATE TABLE application (id INTEGER PRIMARY KEY, company VARCHAR(200), created_at DATETIME, updated_at DATETIME,
            job_title VARCHAR(200), job_id VARCHAR(100), job_url VARCHAR(2048), location VARCHAR(200), job_description TEXT,
            ats VARCHAR(32), status VARCHAR(32), submitted_at DATETIME, resume_id INTEGER, resume_filename VARCHAR(255), resume_sha256 VARCHAR(64));
        CREATE TABLE application_session (id INTEGER PRIMARY KEY, application_id INTEGER, status VARCHAR(32),
            current_page_url VARCHAR(2048), current_page_index INTEGER, detected_fields JSON, errors JSON, created_at DATETIME, updated_at DATETIME);
        INSERT INTO application (id, company, ats, status) VALUES (1, 'Acme', 'UNKNOWN', 'STARTED');
        INSERT INTO application_session (id, application_id, status, current_page_index) VALUES (1, 1, 'ACTIVE', 0);
        """
    )
    con.commit()
    con.close()

    db = Database(f"sqlite:///{path}")
    db.create_all()
    with db.session() as s:
        sess = s.get(ApplicationSession, 1)
        assert sess.overrides is None  # old row: NULL, code must treat as {}
        sess.overrides = {"personal.first_name": "Jane"}
    with db.session() as s:
        assert s.get(ApplicationSession, 1).overrides == {"personal.first_name": "Jane"}
        assert s.get(Application, 1).company == "Acme"
    db.create_all()  # idempotent
    db.dispose()
