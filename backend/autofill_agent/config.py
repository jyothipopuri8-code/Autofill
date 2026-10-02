"""Runtime configuration.

Values come from environment variables prefixed with ``AUTOFILL_`` (or a
``.env`` file). The bind host is deliberately not free-form: the agent
handles highly sensitive personal data and must only ever listen on the
loopback interface.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def default_data_dir() -> Path:
    """Per-user data directory (Windows: %LOCALAPPDATA%, else ~/.local/share)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "AutofillAgent"
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "autofill-agent"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTOFILL_", env_file=".env", extra="ignore")

    host: str = LOOPBACK_HOST
    port: int = Field(default=DEFAULT_PORT, ge=1024, le=65535)
    data_dir: Path = Field(default_factory=default_data_dir)

    # Browser extension origins allowed to call the API, e.g.
    # "chrome-extension://abcdefghijklmnopabcdefghijklmnop". Empty means no
    # browser origin is accepted until the extension is registered.
    allowed_origins: list[str] = Field(default_factory=list)

    max_resume_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)

    log_level: str = "INFO"
    developer_mode: bool = False

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, v: str) -> str:
        if v != LOOPBACK_HOST:
            raise ValueError(f"host must be {LOOPBACK_HOST}; the agent never listens on other interfaces")
        return v

    @field_validator("allowed_origins")
    @classmethod
    def _extension_origins_only(cls, v: list[str]) -> list[str]:
        for origin in v:
            if not origin.startswith(("chrome-extension://", "extension://")) or origin.count("/") != 2:
                raise ValueError(f"allowed origin must be a browser extension origin, got {origin!r}")
        return v

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def database_path(self) -> Path:
        return self.data_dir / "agent.db"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "install_token"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def resume_dir(self) -> Path:
        return self.data_dir / "resumes"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.log_dir, self.resume_dir):
            d.mkdir(parents=True, exist_ok=True)
            _restrict_permissions(d, 0o700)


def _restrict_permissions(path: Path, mode: int) -> None:
    # chmod is a no-op for most bits on Windows; per-user AppData already scopes access there.
    try:
        os.chmod(path, mode)
    except OSError:
        pass


@lru_cache
def get_settings() -> Settings:
    return Settings()
