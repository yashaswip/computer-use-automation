from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest
import uvicorn

from target_app.app import app as target_app


@pytest.fixture(scope="session")
def target_url() -> Iterator[str]:
    config = uvicorn.Config(target_app, host="127.0.0.1", port=18765, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        import time

        time.sleep(0.05)
    yield "http://127.0.0.1:18765"
    server.should_exit = True
    thread.join(timeout=5)
