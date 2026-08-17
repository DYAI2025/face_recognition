from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from face2ai_app.domain.models import (
    Presence,
    PresenceState,
    PresenceTransition,
    RecognitionEvent,
    RecognitionState,
)

_STATE_MAP = {
    RecognitionState.NO_FACE: PresenceState.NO_FACE,
    RecognitionState.UNKNOWN: PresenceState.UNKNOWN,
    RecognitionState.KNOWN: PresenceState.KNOWN,
    RecognitionState.MULTIPLE_FACES: PresenceState.MULTIPLE_FACES,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PresenceTracker:
    """Turns the per-frame RecognitionEvent stream into stable presence transitions.

    A candidate (state, identity) must be observed ``stable_ticks`` times in a row before it
    becomes the current presence; this filters single-frame flicker (HOG misses, motion blur)
    without touching face matching itself. Coming from NO_SIGNAL (camera just started, the
    browser reset presence, or frames stopped for longer than ``stale_after``) the first
    observation is committed immediately so consumers learn that vision is live again.

    Expiry: when no frame arrives for ``stale_after`` the presence is considered gone.
    ``expire()`` (called by the SSE heartbeat and by presence reads) turns that into an explicit
    ``X -> NO_SIGNAL`` transition; ``observe()`` applies the same rule lazily, so a person who
    leaves while the tab is hidden and comes back produces a fresh ``NO_SIGNAL -> KNOWN``.
    """

    def __init__(self, *, stable_ticks: int = 2, stale_after: timedelta = timedelta(seconds=5)) -> None:
        self._stable_ticks = max(1, stable_ticks)
        self._stale_after = stale_after
        self._lock = threading.Lock()
        self._current = Presence()
        self._candidate_key: tuple[PresenceState, str | None] | None = None
        self._candidate_count = 0

    @staticmethod
    def _key(event: RecognitionEvent) -> tuple[PresenceState, str | None]:
        state = _STATE_MAP.get(event.state, PresenceState.NO_FACE)
        primary = event.faces[0] if event.faces else None
        identity_id = primary.identity_id if (state is PresenceState.KNOWN and primary) else None
        return state, identity_id

    def _expired(self, now: datetime) -> bool:
        current = self._current
        return (
            current.state is not PresenceState.NO_SIGNAL
            and current.observed_at is not None
            and now - current.observed_at > self._stale_after
        )

    def _to_no_signal(self, now: datetime) -> PresenceTransition:
        transition = PresenceTransition(
            at=now, from_state=self._current.state, to_state=PresenceState.NO_SIGNAL, faces=0
        )
        self._current = Presence(since=now, observed_at=None)
        self._candidate_key = None
        self._candidate_count = 0
        return transition

    def observe(self, event: RecognitionEvent, now: datetime | None = None) -> PresenceTransition | None:
        """Record one recognition result; return a transition when the stable presence changes."""
        now = now or _now()
        with self._lock:
            if self._expired(now):
                # Frames stopped for a while: whatever we knew is gone. Baseline becomes NO_SIGNAL
                # so this observation commits immediately as a fresh arrival.
                self._to_no_signal(now)
            key = self._key(event)
            if key == self._candidate_key:
                self._candidate_count += 1
            else:
                self._candidate_key = key
                self._candidate_count = 1
            self._current = self._current.model_copy(update={"observed_at": now, "stale": False})

            current_key = (self._current.state, self._current.identity_id)
            if key == current_key:
                return None
            needed = 1 if self._current.state is PresenceState.NO_SIGNAL else self._stable_ticks
            if self._candidate_count < needed:
                return None
            return self._commit(key, event, now)

    def _commit(self, key: tuple[PresenceState, str | None], event: RecognitionEvent, now: datetime) -> PresenceTransition:
        state, identity_id = key
        primary = event.faces[0] if event.faces else None
        display_name = primary.display_name if (state is PresenceState.KNOWN and primary) else None
        transition = PresenceTransition(
            at=now,
            from_state=self._current.state,
            to_state=state,
            identity_id=identity_id,
            display_name=display_name,
            faces=len(event.faces),
        )
        self._current = Presence(
            state=state,
            identity_id=identity_id,
            display_name=display_name,
            faces=len(event.faces),
            since=now,
            observed_at=now,
            stale=False,
        )
        return transition

    def expire(self, now: datetime | None = None) -> PresenceTransition | None:
        """Turn a presence that received no frames for ``stale_after`` into NO_SIGNAL (or None)."""
        now = now or _now()
        with self._lock:
            if not self._expired(now):
                return None
            return self._to_no_signal(now)

    def reset(self, now: datetime | None = None) -> PresenceTransition | None:
        """Camera stopped / browser gone: back to NO_SIGNAL. Returns the transition if anything changed."""
        now = now or _now()
        with self._lock:
            self._candidate_key = None
            self._candidate_count = 0
            if self._current.state is PresenceState.NO_SIGNAL:
                self._current = Presence(since=self._current.since or now, observed_at=None)
                return None
            return self._to_no_signal(now)

    def snapshot(self, now: datetime | None = None) -> Presence:
        """Current presence; ``stale`` is set when no frame has been observed for ``stale_after``.

        Read-only: callers that want the stale presence to *become* NO_SIGNAL call ``expire()``.
        """
        now = now or _now()
        with self._lock:
            current = self._current
            if current.state is PresenceState.NO_SIGNAL or current.observed_at is None:
                return current.model_copy(update={"stale": False})
            return current.model_copy(update={"stale": now - current.observed_at > self._stale_after})
