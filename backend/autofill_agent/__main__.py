"""Entry point: ``python -m autofill_agent`` or ``autofill-agent``."""

from __future__ import annotations

import sys

import uvicorn

from autofill_agent.config import LOOPBACK_HOST, get_settings
from autofill_agent.main import create_app
from autofill_agent.security import load_or_create_token


def print_token(rotate: bool = False) -> None:
    """``python -m autofill_agent token [--rotate]``: show the installation token to paste into the extension.

    ``--rotate`` replaces it, which disconnects every paired browser until it is given the new token.
    Restart the agent afterwards so it uses the new one.
    """
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if rotate:
        settings.token_path.unlink(missing_ok=True)
    print(load_or_create_token(settings.token_path))


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "token":
        print_token(rotate="--rotate" in sys.argv[2:])
        return
    settings = get_settings()
    app = create_app(settings)
    print(f"Installation token stored at: {settings.token_path}")
    # Host is validated in Settings and passed explicitly; never 0.0.0.0.
    assert settings.host == LOOPBACK_HOST
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None, server_header=False)


if __name__ == "__main__":
    main()
