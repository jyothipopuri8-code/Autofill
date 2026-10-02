import pytest
from fastapi.testclient import TestClient

from autofill_agent.config import Settings
from autofill_agent.db import Database
from autofill_agent.main import create_app

EXT_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", allowed_origins=[EXT_ORIGIN], _env_file=None)


@pytest.fixture
def client(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth(client):
    return {"Authorization": f"Bearer {client.app.state.install_token}"}


@pytest.fixture
def db():
    d = Database("sqlite:///:memory:")
    d.create_all()
    yield d
    d.dispose()
