"""The dashboard API half (`/api/plugins/face2ai/*`) — needs fastapi + httpx, which the plain plugin test
environment (and CI) does not have: skipped there, runs locally with
`uv run --no-project --with pytest==9.0.2 --with fastapi --with httpx pytest apps/face2ai-hermes-plugin/tests`."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "face2ai" / "dashboard"))

import plugin_api  # noqa: E402


def _app():
    app = fastapi.FastAPI()
    app.include_router(plugin_api.router)
    return app


class _Response:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        return self._payload


def _fake_client(calls, payload=None, status=200, exc=None):
    class FakeAsyncClient:
        def __init__(self, *a, **kw):
            calls.append(("init", kw))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            calls.append(("get", url, dict(params or {})))
            if exc:
                raise exc
            return _Response(payload, status)

    return FakeAsyncClient


def test_timeline_proxies_face2ai_with_clamped_seconds_and_identity(monkeypatch):
    calls = []
    upstream = {"seconds": 3600, "samples": [{"at": "2026-08-18T12:00:00Z", "identity_id": "a", "display_name": "Ben", "mood": "Happiness", "valence": 0.6, "arousal": 0.1}], "moods": [], "actions": [{"action": "smile", "duration_ms": 900}]}
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(calls, upstream))
    monkeypatch.setattr(plugin_api, "_events_url", lambda: "http://face2ai.test:8765")
    client = TestClient(_app())
    body = client.get("/timeline", params={"seconds": 99999, "identity_id": "a"}).json()
    assert body == upstream and "error" not in body
    assert calls[-1] == ("get", "http://face2ai.test:8765/api/expression/timeline", {"seconds": 3600, "identity_id": "a"})
    assert calls[-2][1]["timeout"] == 3.0
    client.get("/timeline", params={"seconds": 5})
    assert calls[-1][2] == {"seconds": 10}  # clamped up, no identity_id key when not given
    client.get("/timeline")
    assert calls[-1][2] == {"seconds": 600}


def test_timeline_error_keeps_the_shape(monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _fake_client(calls, exc=httpx.ConnectError("refused")))
    monkeypatch.setattr(plugin_api, "_events_url", lambda: "http://face2ai.test:8765")
    client = TestClient(_app())
    body = client.get("/timeline", params={"seconds": 120}).json()
    assert body == {"error": "refused", "seconds": 120, "samples": [], "moods": [], "actions": []}
