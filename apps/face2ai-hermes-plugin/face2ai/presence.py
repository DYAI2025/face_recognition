"""Face2AI presence: SSE parsing, a thread-safe store and the text Hermes gets to see.

Pure Python (stdlib only) so it unit-tests without Hermes and can be imported by both the
gateway plugin (writer) and the dashboard API (reader). Nothing here handles frames or face
encodings — Face2AI's event stream never carries them.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

STATES = ("NO_SIGNAL", "NO_FACE", "UNKNOWN", "KNOWN", "MULTIPLE_FACES")


@dataclass(frozen=True)
class SseFrame:
    event: str
    data: dict[str, Any]
    id: str | None = None


def parse_sse(lines: Iterable[str]) -> Iterator[SseFrame]:
    """Minimal SSE parser: one frame per blank-line-terminated block."""
    event, data_lines, frame_id = "message", [], None
    for raw in lines:
        line = raw.rstrip("\r")
        if line == "":
            if data_lines:
                try:
                    data = json.loads("\n".join(data_lines))
                except json.JSONDecodeError:
                    data = {"raw": "\n".join(data_lines)}
                yield SseFrame(event=event, data=data, id=frame_id)
            event, data_lines, frame_id = "message", [], None
            continue
        if line.startswith(":"):
            continue
        key, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if key == "event":
            event = value
        elif key == "data":
            data_lines.append(value)
        elif key == "id":
            frame_id = value


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@dataclass
class Presence:
    state: str = "NO_SIGNAL"
    identity_id: str | None = None
    display_name: str | None = None
    faces: int = 0
    since: datetime | None = None
    stale: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Presence":
        state = payload.get("state") if payload.get("state") in STATES else "NO_SIGNAL"
        return cls(
            state=state,
            identity_id=payload.get("identity_id"),
            display_name=payload.get("display_name"),
            faces=int(payload.get("faces") or 0),
            since=_parse_time(payload.get("since")),
            stale=bool(payload.get("stale", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["since"] = _iso(self.since)
        return d


@dataclass
class Transition:
    at: datetime
    from_state: str
    to_state: str
    identity_id: str | None
    display_name: str | None
    faces: int

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Transition":
        return cls(
            at=_parse_time(payload.get("at")) or datetime.now(timezone.utc),
            from_state=str(payload.get("from_state", "NO_SIGNAL")),
            to_state=str(payload.get("to_state", "NO_SIGNAL")),
            identity_id=payload.get("identity_id"),
            display_name=payload.get("display_name"),
            faces=int(payload.get("faces") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["at"] = _iso(self.at)
        return d


class PresenceStore:
    """Latest presence + recent transitions, safe to read from hook callbacks on any thread."""

    def __init__(self, *, history: int = 30) -> None:
        self._lock = threading.Lock()
        self.current = Presence()
        self.connected = False
        self.engine_available: bool | None = None
        self.last_frame_at: datetime | None = None
        self.hello_sequence = 0
        self.history: deque[Transition] = deque(maxlen=history)
        self.identity_count: int | None = None
        self.last_error: str | None = None

    # ------------------------------------------------------------------ writers

    def apply(self, frame: SseFrame, now: datetime | None = None) -> Transition | None:
        """Apply one SSE frame; returns the transition when a `presence` frame arrived (for reactions)."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            self.last_frame_at = now
            if frame.event == "hello":
                self.connected = True
                self.last_error = None
                self.current = Presence.from_payload(frame.data.get("presence") or {})
                self.engine_available = frame.data.get("engine_available")
                seq = frame.data.get("last_sequence")
                self.hello_sequence = seq if isinstance(seq, int) else 0
                return None
            if frame.event == "heartbeat":
                payload = frame.data.get("presence") or {}
                if payload:
                    self.current = Presence.from_payload(payload)
                return None
            if frame.event == "presence":
                transition = Transition.from_payload(frame.data)
                self.history.append(transition)
                self.current = Presence(
                    state=transition.to_state,
                    identity_id=transition.identity_id,
                    display_name=transition.display_name,
                    faces=transition.faces,
                    since=transition.at,
                )
                seq = frame.data.get("sequence")
                replayed = isinstance(seq, int) and seq <= self.hello_sequence
                return None if replayed else transition
            if frame.event == "store":
                count = frame.data.get("identity_count")
                if isinstance(count, int):
                    self.identity_count = count
                return None
            return None

    def mark_lost(self, error: str) -> None:
        with self._lock:
            self.connected = False
            self.last_error = error

    # ------------------------------------------------------------------ readers

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "connected": self.connected,
                "engine_available": self.engine_available,
                "identity_count": self.identity_count,
                "last_frame_at": _iso(self.last_frame_at),
                "last_error": self.last_error,
                "presence": self.current.to_dict(),
                "history": [t.to_dict() for t in list(self.history)[-10:]],
            }

    def age_seconds(self, now: datetime | None = None) -> float | None:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            if self.last_frame_at is None:
                return None
            return max(0.0, (now - self.last_frame_at).total_seconds())


def describe(store: PresenceStore, *, now: datetime | None = None, language: str = "de") -> str:
    """One or two plain sentences for the model — honest about staleness and gaps."""
    now = now or datetime.now(timezone.utc)
    snap = store.snapshot()
    de = language.lower().startswith("de")
    if not snap["connected"]:
        return ("Face2AI (Kamera-Präsenz) ist gerade nicht verbunden; du kannst nicht sehen, wer da ist."
                if de else "Face2AI (camera presence) is not connected; you cannot see who is here.")
    p = snap["presence"]
    since = _parse_time(p.get("since"))
    seconds = int((now - since).total_seconds()) if since else None
    for_text = (f" seit etwa {seconds} s" if de else f" for about {seconds} s") if seconds is not None and seconds >= 0 else ""
    state = p["state"]
    if state == "NO_SIGNAL":
        text = "Die Kamera ist aus (kein Bildsignal)." if de else "The camera is off (no vision signal)."
    elif state == "NO_FACE":
        text = f"Die Kamera läuft, aber niemand steht davor{for_text}." if de else f"The camera is on but nobody is in front of it{for_text}."
    elif state == "UNKNOWN":
        text = (f"Eine Person steht vor der Kamera{for_text}, Face2AI kennt sie nicht (nicht enrollt). Rate keinen Namen."
                if de else f"One person is in front of the camera{for_text}; Face2AI does not recognize them (not enrolled). Do not guess a name.")
    elif state == "KNOWN":
        name = p.get("display_name") or ("eine bekannte Person" if de else "a known person")
        text = (f"{name} steht vor der Kamera{for_text} (von Face2AI erkannt, beste Übereinstimmung, keine Gewissheit)."
                if de else f"{name} is in front of the camera{for_text} (recognized by Face2AI — best match, not certainty).")
    else:
        text = (f"{p.get('faces', 0)} Personen stehen vor der Kamera{for_text}; bei mehreren Gesichtern ordnet Face2AI keine Identität zu."
                if de else f"{p.get('faces', 0)} people are in front of the camera{for_text}; Face2AI does not attribute identity with several faces.")
    if p.get("stale"):
        text += " (Keine frischen Frames – der Browser-Tab pausiert vielleicht.)" if de else " (No fresh frames lately — the browser tab may be paused.)"
    if snap.get("engine_available") is False:
        text += " Die Erkennungs-Engine meldet sich als nicht verfügbar." if de else " The recognition engine reports itself unavailable."
    recent = [t for t in snap["history"] if t["to_state"] == "KNOWN" and t["display_name"] and t["identity_id"] != p.get("identity_id")][-4:]
    if recent:
        names = ", ".join(f"{t['display_name']} ({(_parse_time(t['at']) or now).astimezone().strftime('%H:%M')})" for t in recent)
        text += (f" Zuletzt gesehen: {names}." if de else f" Recently seen: {names}.")
    return text


def context_line(store: PresenceStore, *, now: datetime | None = None, language: str = "de", max_age_seconds: int = 30) -> str | None:
    """The line injected into a turn, or None when the information is not trustworthy enough."""
    age = store.age_seconds(now)
    if age is None or age > max_age_seconds:
        return None
    return f"[face2ai] {describe(store, now=now, language=language)}"
