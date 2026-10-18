"""What several test files share."""

import httpx2
import pytest


@pytest.fixture
def anyio_backend():
    """The async tests run on asyncio, as the app does."""
    return "asyncio"


@pytest.fixture
def offline(monkeypatch):
    """offline(answer): the app's HTTP connections send every request to answer(request),
    a stand-in for the inspection server and its login server, instead of the network."""
    real = httpx2.AsyncClient

    def route(answer):
        class Offline(real):
            def __init__(self, **options):
                super().__init__(transport=httpx2.MockTransport(answer), **options)

        monkeypatch.setattr(httpx2, "AsyncClient", Offline)
    return route
