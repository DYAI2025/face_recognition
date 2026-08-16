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
        )
