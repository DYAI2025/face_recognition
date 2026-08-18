"""Presence + Server-Sent Events API.

The SSE stream is infinite, and Starlette's TestClient buffers a response until the app
returns, so these tests run the FastAPI app under a real uvicorn server on a loopback port
and read the stream with httpx — the same path the voice agent uses.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import uvicorn

from face2ai_app.adapters.json_identity_store import JsonIdentityStore
from face2ai_app.config import Settings
from face2ai_app.main import create_app

HEADERS = {"content-type": "image/jpeg"}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class LiveServer:
    base_url: str
    client: httpx.Client

    def sse(
        self,
        path: str,
        wanted: int,
        headers: dict | None = None,
        timeout: float = 5.0,
        *,
        skip_heartbeats: bool = False,
    ) -> list[dict]:
        """Read ``wanted`` SSE frames as [{'id':..., 'event':..., 'data':{...}}]."""
        frames: list[dict] = []
        current: dict = {}
        with self.client.stream("GET", path, headers=headers or {}, timeout=timeout) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            for line in response.iter_lines():
                if line == "":
                    if current and not (skip_heartbeats and current.get("event") == "heartbeat"):
                        frames.append(current)
                    current = {}
                    if len(frames) >= wanted:
                        break
                    continue
                key, _, value = line.partition(": ")
                current[key] = json.loads(value) if key == "data" else value
        return frames[:wanted]


@pytest.fixture
def live(tmp_path: Path, fake_engine) -> Iterator[LiveServer]:
    settings = Settings(
        data_dir=tmp_path,
        presence_stable_ticks=1,
        events_heartbeat_seconds=0.05,
        greeting_cooldown_seconds=7,
    )
    app = create_app(settings=settings, engine=fake_engine, store=JsonIdentityStore(settings.identity_store_path))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, name="test-uvicorn", daemon=True)
    thread.start()
    deadline = time.time() + 5
    while not server.started:
        assert time.time() < deadline, "uvicorn did not start"
        time.sleep(0.02)
    base_url = f"http://127.0.0.1:{port}"
    with httpx.Client(base_url=base_url, timeout=5.0) as client:
        yield LiveServer(base_url=base_url, client=client)
    server.should_exit = True
    thread.join(timeout=5)


def test_presence_endpoint_follows_recognition_and_reset(live, fake_engine, face):
    assert live.client.get("/api/presence").json()["state"] == "NO_SIGNAL"
    fake_engine.faces = [face]
    live.client.post("/api/recognize", content=b"frame", headers=HEADERS)
    presence = live.client.get("/api/presence").json()
    assert presence["state"] == "UNKNOWN"
    assert presence["faces"] == 1
    assert presence["stale"] is False
    assert live.client.post("/api/presence/reset").json()["state"] == "NO_SIGNAL"


def test_events_stream_starts_with_hello_and_replays_buffered_events(live, fake_engine, face):
    fake_engine.faces = [face]
    live.client.post("/api/recognize", content=b"frame", headers=HEADERS)  # NO_SIGNAL -> UNKNOWN (seq 1)
    enrolled = live.client.post("/api/enroll?display_name=Ada&consent=true", content=b"frame", headers=HEADERS)
    assert enrolled.status_code == 201  # seq 2

    frames = live.sse("/api/events?after=0", wanted=3)
    assert frames[0]["event"] == "hello"
    assert frames[0]["data"]["presence"]["state"] == "UNKNOWN"
    assert frames[0]["data"]["greeting_cooldown_seconds"] == 7
    assert frames[0]["data"]["last_sequence"] == 2
    assert frames[0]["data"]["engine_available"] is True

    assert frames[1]["event"] == "presence" and frames[1]["id"] == "1"
    assert frames[1]["data"]["from_state"] == "NO_SIGNAL"
    assert frames[1]["data"]["to_state"] == "UNKNOWN"

    assert frames[2]["event"] == "store" and frames[2]["id"] == "2"
    assert frames[2]["data"]["kind"] == "enrolled"
    assert frames[2]["data"]["display_name"] == "Ada"
    assert frames[2]["data"]["identity_count"] == 1


def test_live_events_arrive_while_subscribed(live, fake_engine, face):
    fake_engine.faces = [face]
    received: list[dict] = []

    def subscriber() -> None:
        received.extend(live.sse("/api/events", wanted=2, skip_heartbeats=True))

    thread = threading.Thread(target=subscriber, daemon=True)
    thread.start()
    deadline = time.time() + 3
    while live.client.get("/api/status").json()["event_subscribers"] < 1:  # deterministic handshake
        assert time.time() < deadline, "subscriber never registered"
        time.sleep(0.02)
    live.client.post("/api/recognize", content=b"frame", headers=HEADERS)
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert [f["event"] for f in received] == ["hello", "presence"]
    assert received[1]["data"]["to_state"] == "UNKNOWN"


def test_heartbeat_carries_presence_snapshot(live, fake_engine, face):
    fake_engine.faces = [face]
    live.client.post("/api/recognize", content=b"frame", headers=HEADERS)
    frames = live.sse("/api/events", wanted=2)
    assert frames[0]["event"] == "hello"
    assert frames[1]["event"] == "heartbeat"
    assert frames[1]["data"]["presence"]["state"] == "UNKNOWN"


def test_last_event_id_header_resumes(live, fake_engine, face):
    fake_engine.faces = [face]
    live.client.post("/api/recognize", content=b"frame", headers=HEADERS)  # seq 1
    live.client.post("/api/presence/reset")  # seq 2
    frames = live.sse("/api/events", wanted=2, headers={"Last-Event-ID": "1"})
    assert [f["event"] for f in frames] == ["hello", "presence"]
    assert frames[1]["id"] == "2" and frames[1]["data"]["to_state"] == "NO_SIGNAL"


def test_store_events_for_delete_and_erase(live, fake_engine, face):
    fake_engine.faces = [face]
    record = live.client.post("/api/enroll?display_name=Ada&consent=true", content=b"frame", headers=HEADERS).json()
    assert live.client.delete(f"/api/identities/{record['id']}").status_code == 204
    assert live.client.delete("/api/identities").json() == {"deleted": 0}
    frames = live.sse("/api/events?after=0", wanted=4)
    kinds = [(f["event"], f["data"].get("kind")) for f in frames[1:]]
    assert kinds == [("store", "enrolled"), ("store", "deleted"), ("store", "erased")]
    assert frames[2]["data"]["display_name"] == "Ada"
    assert frames[3]["data"]["identity_count"] == 0


def test_status_reports_agent_subscription_while_stream_is_open(live):
    assert live.client.get("/api/status").json()["agent_connected"] is False
    with live.client.stream("GET", "/api/events?role=agent") as response:
        lines = response.iter_lines()  # keep the iterator alive: dropping it closes the stream
        assert next(lines) == "event: hello"  # subscription is registered once hello arrives
        status = live.client.get("/api/status").json()
        assert status["agent_connected"] is True
        assert status["event_subscribers"] == 1
    deadline = time.time() + 3
    while live.client.get("/api/status").json()["agent_connected"] and time.time() < deadline:
        time.sleep(0.05)
    assert live.client.get("/api/status").json()["agent_connected"] is False


def test_events_stream_carries_only_the_documented_keys(live, fake_engine, face):
    """ADR-002 §2: states, names, counts, timestamps — never frames, boxes, encodings or distances."""
    fake_engine.faces = [face]
    live.client.post("/api/recognize", content=b"frame", headers=HEADERS)
    live.client.post("/api/enroll?display_name=Ada&consent=true", content=b"frame", headers=HEADERS)
    frames = live.sse("/api/events?after=0", wanted=3)
    hello, presence, store = frames
    presence_keys = {
        "state", "identity_id", "display_name", "faces", "since", "observed_at", "stale", "mood", "valence", "arousal",
    }
    assert set(hello["data"]["presence"]) == presence_keys
    assert set(presence["data"]) == {
        "sequence", "at", "from_state", "to_state", "identity_id", "display_name", "faces", "mood", "valence", "arousal",
    }
    assert set(store["data"]) == {"sequence", "at", "kind", "identity_id", "display_name", "identity_count"}
    text = json.dumps([f["data"] for f in frames])
    for forbidden in ("encoding", "box", "match_distance", "top", "left"):
        assert forbidden not in text, forbidden


def test_recognize_response_signals_agent_ownership_per_frame(live, fake_engine, face):
    fake_engine.faces = [face]
    assert live.client.post("/api/recognize", content=b"frame", headers=HEADERS).headers["x-face2ai-agent"] == "0"
    with live.client.stream("GET", "/api/events?role=agent") as response:
        lines = response.iter_lines()
        assert next(lines) == "event: hello"
        assert live.client.post("/api/recognize", content=b"frame", headers=HEADERS).headers["x-face2ai-agent"] == "1"


def test_stale_presence_expires_to_no_signal_and_is_published(tmp_path: Path, fake_engine, face):
    settings = Settings(data_dir=tmp_path, presence_stable_ticks=1, presence_stale_seconds=0.2, events_heartbeat_seconds=0.05)
    app = create_app(settings=settings, engine=fake_engine, store=JsonIdentityStore(settings.identity_store_path))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5.0) as client:
            live = LiveServer(base_url=client.base_url, client=client)
            fake_engine.faces = [face]
            client.post("/api/recognize", content=b"frame", headers=HEADERS)  # UNKNOWN
            time.sleep(0.4)  # longer than stale_seconds: no frames
            frames = live.sse("/api/events?after=0", wanted=3, skip_heartbeats=True)
            assert [f["event"] for f in frames] == ["hello", "presence", "presence"]
            assert frames[0]["data"]["presence"]["state"] == "NO_SIGNAL"  # expired before hello
            assert frames[1]["data"]["to_state"] == "UNKNOWN"
            assert frames[2]["data"]["from_state"] == "UNKNOWN" and frames[2]["data"]["to_state"] == "NO_SIGNAL"
            client.post("/api/recognize", content=b"frame", headers=HEADERS)  # back: fresh arrival
            assert client.get("/api/presence").json()["state"] == "UNKNOWN"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
