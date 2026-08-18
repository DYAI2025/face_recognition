from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    match_tolerance: float = 0.6
    max_frame_bytes: int = 5 * 1024 * 1024
    data_dir: Path = Path.home() / ".face2ai"
    greeting_cooldown_seconds: int = 15
    presence_stable_ticks: int = 2
    presence_stale_seconds: float = 5.0
    events_heartbeat_seconds: float = 15.0
    events_buffer_size: int = 200
    expression_enabled: bool = False
    expression_models_dir: Path = Path.home() / ".face2ai" / "models"
    mood_stable_ticks: int = 3
    mood_min_score: float = 0.5

    def __post_init__(self) -> None:
        if self.presence_stale_seconds <= 0:
            raise ValueError("FACE2AI_PRESENCE_STALE_SECONDS must be > 0")
        if self.events_heartbeat_seconds <= 0:
            raise ValueError("FACE2AI_EVENTS_HEARTBEAT_SECONDS must be > 0")
        if self.presence_stable_ticks < 1:
            raise ValueError("FACE2AI_PRESENCE_STABLE_TICKS must be >= 1")
        if self.events_buffer_size < 1:
            raise ValueError("FACE2AI_EVENTS_BUFFER_SIZE must be >= 1")
        if self.mood_stable_ticks < 1:
            raise ValueError("FACE2AI_MOOD_STABLE_TICKS must be >= 1")
        if not 0 < self.mood_min_score <= 1:
            raise ValueError("FACE2AI_MOOD_MIN_SCORE must be in (0, 1]")

    @property
    def identity_store_path(self) -> Path:
        return self.data_dir / "identities.json"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.getenv("FACE2AI_HOST", "127.0.0.1"),
            port=int(os.getenv("FACE2AI_PORT", "8765")),
            match_tolerance=float(os.getenv("FACE2AI_MATCH_TOLERANCE", "0.6")),
            max_frame_bytes=int(os.getenv("FACE2AI_MAX_FRAME_BYTES", str(5 * 1024 * 1024))),
            data_dir=Path(os.getenv("FACE2AI_DATA_DIR", str(Path.home() / ".face2ai"))).expanduser(),
            greeting_cooldown_seconds=int(os.getenv("FACE2AI_GREETING_COOLDOWN_SECONDS", "15")),
            presence_stable_ticks=int(os.getenv("FACE2AI_PRESENCE_STABLE_TICKS", "2")),
            presence_stale_seconds=float(os.getenv("FACE2AI_PRESENCE_STALE_SECONDS", "5")),
            events_heartbeat_seconds=float(os.getenv("FACE2AI_EVENTS_HEARTBEAT_SECONDS", "15")),
            events_buffer_size=int(os.getenv("FACE2AI_EVENTS_BUFFER_SIZE", "200")),
            expression_enabled=os.getenv("FACE2AI_EXPRESSION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
            expression_models_dir=Path(
                os.getenv("FACE2AI_EXPRESSION_MODELS_DIR", str(Path.home() / ".face2ai" / "models"))
            ).expanduser(),
            mood_stable_ticks=int(os.getenv("FACE2AI_MOOD_STABLE_TICKS", "3")),
            mood_min_score=float(os.getenv("FACE2AI_MOOD_MIN_SCORE", "0.5")),
        )
