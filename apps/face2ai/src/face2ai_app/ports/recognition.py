from __future__ import annotations

from typing import Protocol

from face2ai_app.domain.models import DetectedFace


class RecognitionEngine(Protocol):
    @property
    def available(self) -> bool: ...

    @property
    def availability_reason(self) -> str | None: ...

    def detect(self, image_bytes: bytes) -> list[DetectedFace]: ...
