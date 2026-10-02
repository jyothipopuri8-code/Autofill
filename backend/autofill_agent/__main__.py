"""Entry point: ``python -m autofill_agent`` or ``autofill-agent``."""

from __future__ import annotations

import uvicorn

from autofill_agent.config import LOOPBACK_HOST, get_settings
from autofill_agent.main import create_app


def main() -> None:
    settings = get_settings()
    app = create_app(settings)
    print(f"Installation token stored at: {settings.token_path}")
    # Host is validated in Settings and passed explicitly; never 0.0.0.0.
    assert settings.host == LOOPBACK_HOST
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None, server_header=False)


if __name__ == "__main__":
    main()
