from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, Field

Encoding = list[float]


class RecognitionState(StrEnum):
    NO_FACE = "NO_FACE"
    UNKNOWN = "UNKNOWN"
    LEARNING = "LEARNING"
    KNOWN = "KNOWN"
    MULTIPLE_FACES = "MULTIPLE_FACES"
    ERROR = "ERROR"


class FaceBox(BaseModel):
    top: int
    right: int
    bottom: int
    left: int


class DetectedFace(BaseModel):
    box: FaceBox
    encoding: Annotated[Encoding, Field(min_length=128, max_length=128)]


class FaceObservation(BaseModel):
    box: FaceBox
    matched: bool = False
    identity_id: str | None = None
    display_name: str | None = None
    match_distance: float | None = None


class RecognitionEvent(BaseModel):
    state: RecognitionState
    faces: list[FaceObservation] = Field(default_factory=list)
    can_enroll: bool = False
    message: str | None = None


class IdentityRecord(BaseModel):
    id: str
    display_name: str
    encodings: list[Encoding]
    created_at: datetime
    purpose: str = "local Face2AI recognition"

    @classmethod
    def new(cls, display_name: str, encoding: Encoding) -> "IdentityRecord":
        return cls(
            id=str(uuid4()),
            display_name=display_name.strip(),
            encodings=[encoding],
            created_at=datetime.now(timezone.utc),
        )


class IdentitySummary(BaseModel):
    id: str
    display_name: str
    created_at: datetime
    encoding_count: int


class SystemStatus(BaseModel):
    app: str = "Face2AI"
    version: str
    engine_available: bool
    engine_reason: str | None = None
    identity_count: int
    greeting_cooldown_seconds: int
