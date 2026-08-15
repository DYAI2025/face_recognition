from __future__ import annotations

import math

from face2ai_app.domain.errors import EnrollmentRejected, RecognitionUnavailable
from face2ai_app.domain.models import FaceObservation, IdentityRecord, IdentitySummary, RecognitionEvent, RecognitionState
from face2ai_app.ports.identity_store import IdentityStore
from face2ai_app.ports.recognition import RecognitionEngine


class IdentityService:
    def __init__(self, engine: RecognitionEngine, store: IdentityStore, tolerance: float) -> None:
        self.engine = engine
        self.store = store
        self.tolerance = tolerance

    def _nearest(self, candidate: list[float]) -> tuple[IdentityRecord | None, float | None]:
        nearest_identity: IdentityRecord | None = None
        nearest_distance: float | None = None
        for identity in self.store.list():
            for known in identity.encodings:
                distance = math.dist(known, candidate)
                if nearest_distance is None or distance < nearest_distance:
                    nearest_identity = identity
                    nearest_distance = distance
        if nearest_distance is None or nearest_distance > self.tolerance:
            return None, nearest_distance
        return nearest_identity, nearest_distance

    def recognize(self, image_bytes: bytes) -> RecognitionEvent:
        if not self.engine.available:
            raise RecognitionUnavailable(self.engine.availability_reason or "recognition engine unavailable")
        detected = self.engine.detect(image_bytes)
        if not detected:
            return RecognitionEvent(state=RecognitionState.NO_FACE, can_enroll=False)
        observations: list[FaceObservation] = []
        for face in detected:
            identity, distance = self._nearest(face.encoding)
            observations.append(FaceObservation(box=face.box, matched=identity is not None, identity_id=identity.id if identity else None, display_name=identity.display_name if identity else None, match_distance=distance))
        if len(observations) > 1:
            return RecognitionEvent(state=RecognitionState.MULTIPLE_FACES, faces=observations, can_enroll=False, message="Enrollment requires exactly one visible face.")
        observation = observations[0]
        return RecognitionEvent(state=RecognitionState.KNOWN if observation.matched else RecognitionState.UNKNOWN, faces=observations, can_enroll=not observation.matched)

    def enroll(self, image_bytes: bytes, display_name: str, consent: bool) -> IdentitySummary:
        clean_name = display_name.strip()
        if not consent:
            raise EnrollmentRejected("explicit local biometric enrollment consent is required")
        if not clean_name or len(clean_name) > 80:
            raise EnrollmentRejected("display name must contain 1-80 characters")
        if not self.engine.available:
            raise RecognitionUnavailable(self.engine.availability_reason or "recognition engine unavailable")
        detected = self.engine.detect(image_bytes)
        if len(detected) != 1:
            raise EnrollmentRejected("enrollment requires exactly one visible face")
        record = self.store.add(IdentityRecord.new(clean_name, detected[0].encoding))
        return IdentitySummary(id=record.id, display_name=record.display_name, created_at=record.created_at, encoding_count=len(record.encodings))

    def summaries(self) -> list[IdentitySummary]:
        return [IdentitySummary(id=record.id, display_name=record.display_name, created_at=record.created_at, encoding_count=len(record.encodings)) for record in self.store.list()]
