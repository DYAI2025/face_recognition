from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from face2ai.presence import PresenceStore, SseFrame, context_line, describe, parse_sse  # noqa: E402

T0 = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def frames(*specs):
    return [SseFrame(event=e, data=d, id=i) for e, d, i in specs]


def test_parse_sse_frames():
    out = list(parse_sse(["id: 3", "event: presence", 'data: {"to_state": "KNOWN"}', "", ": ping", "event: heartbeat", 'data: {"presence": {"state": "KNOWN"}}', ""]))
    assert [f.event for f in out] == ["presence", "heartbeat"]
    assert out[0].id == "3" and out[0].data["to_state"] == "KNOWN"


def test_store_hello_transition_and_describe_de_and_en():
    store = PresenceStore()
    assert "nicht verbunden" in describe(store, now=T0)
    store.apply(SseFrame("hello", {"presence": {"state": "NO_FACE", "since": T0.isoformat()}, "last_sequence": 5, "engine_available": True}), now=T0)
    assert store.connected and store.hello_sequence == 5
    assert "niemand steht davor" in describe(store, now=T0 + timedelta(seconds=3))
    t = store.apply(SseFrame("presence", {"sequence": 6, "at": T0.isoformat(), "from_state": "NO_FACE", "to_state": "KNOWN", "identity_id": "a", "display_name": "Ben", "faces": 1}), now=T0)
    assert t is not None and t.display_name == "Ben"
    de = describe(store, now=T0 + timedelta(seconds=40))
    assert de.startswith("Ben steht vor der Kamera seit etwa 40 s")
    en = describe(store, now=T0 + timedelta(seconds=40), language="en")
    assert en.startswith("Ben is in front of the camera for about 40 s")
    assert "keine Gewissheit" in de and "not certainty" in en


def test_replayed_transitions_update_state_but_do_not_react():
    store = PresenceStore()
    store.apply(SseFrame("hello", {"presence": {"state": "NO_SIGNAL"}, "last_sequence": 10}), now=T0)
    replayed = store.apply(SseFrame("presence", {"sequence": 9, "from_state": "NO_SIGNAL", "to_state": "KNOWN", "identity_id": "a", "display_name": "Ben", "faces": 1, "at": T0.isoformat()}), now=T0)
    assert replayed is None and store.current.state == "KNOWN"
    live = store.apply(SseFrame("presence", {"sequence": 11, "from_state": "KNOWN", "to_state": "UNKNOWN", "faces": 1, "at": T0.isoformat()}), now=T0)
    assert live is not None and live.to_state == "UNKNOWN"


def test_unknown_multiple_stale_and_engine_down_wording():
    store = PresenceStore()
    store.apply(SseFrame("hello", {"presence": {"state": "UNKNOWN", "faces": 1, "stale": True}, "engine_available": False}), now=T0)
    text = describe(store, now=T0)
    assert "kennt sie nicht" in text and "Rate keinen Namen" in text
    assert "keine frischen Frames" in text.lower() or "Keine frischen Frames" in text
    assert "nicht verfügbar" in text
    store.apply(SseFrame("heartbeat", {"presence": {"state": "MULTIPLE_FACES", "faces": 3}}), now=T0)
    assert "3 Personen" in describe(store, now=T0)


def test_recently_seen_lists_only_other_known_people():
    store = PresenceStore()
    store.apply(SseFrame("hello", {"presence": {"state": "NO_FACE"}, "last_sequence": 0}), now=T0)
    store.apply(SseFrame("presence", {"sequence": 1, "at": T0.isoformat(), "from_state": "NO_FACE", "to_state": "KNOWN", "identity_id": "a", "display_name": "Ada", "faces": 1}), now=T0)
    store.apply(SseFrame("presence", {"sequence": 2, "at": (T0 + timedelta(seconds=30)).isoformat(), "from_state": "KNOWN", "to_state": "NO_FACE", "faces": 0}), now=T0)
    store.apply(SseFrame("presence", {"sequence": 3, "at": (T0 + timedelta(seconds=60)).isoformat(), "from_state": "NO_FACE", "to_state": "KNOWN", "identity_id": "b", "display_name": "Ben", "faces": 1}), now=T0)
    text = describe(store, now=T0 + timedelta(seconds=61))
    assert text.startswith("Ben steht vor der Kamera")
    assert "Zuletzt gesehen: Ada" in text and "no face" not in text.lower()


def test_context_line_is_withheld_when_frames_are_old():
    store = PresenceStore()
    store.apply(SseFrame("hello", {"presence": {"state": "KNOWN", "display_name": "Ben", "identity_id": "a"}}), now=T0)
    assert context_line(store, now=T0 + timedelta(seconds=5)).startswith("[face2ai] Ben steht vor der Kamera")
    assert context_line(store, now=T0 + timedelta(seconds=45)) is None  # older than 30 s without a heartbeat
    store.apply(SseFrame("heartbeat", {"presence": {"state": "KNOWN", "display_name": "Ben", "identity_id": "a"}}), now=T0 + timedelta(seconds=44))
    assert context_line(store, now=T0 + timedelta(seconds=45)) is not None
    store.mark_lost("boom")
    assert "nicht verbunden" in context_line(store, now=T0 + timedelta(seconds=45))


def test_snapshot_is_json_friendly():
    import json

    store = PresenceStore()
    store.apply(SseFrame("hello", {"presence": {"state": "NO_FACE", "since": T0.isoformat()}}), now=T0)
    store.apply(SseFrame("store", {"kind": "enrolled", "identity_count": 2}), now=T0)
    snap = store.snapshot()
    json.dumps(snap)
    assert snap["identity_count"] == 2 and snap["presence"]["since"] == T0.isoformat()
