from __future__ import annotations

from io import BytesIO

from face2ai_app.domain.errors import InvalidFrame, RecognitionUnavailable
from face2ai_app.domain.models import DetectedFace, FaceBox


class FaceRecognitionEngine:
    def __init__(self) -> None:
        self._module = None
        self._reason: str | None = None
        try:
            import face_recognition  # type: ignore
            self._module = face_recognition
        except Exception as exc:
            self._reason = f"{type(exc).__name__}: {exc}"

    @property
    def available(self) -> bool:
        return self._module is not None

    @property
    def availability_reason(self) -> str | None:
        return self._reason

    def detect(self, image_bytes: bytes) -> list[DetectedFace]:
        if self._module is None:
            raise RecognitionUnavailable(self._reason or "face_recognition engine unavailable")
        if not image_bytes:
            raise InvalidFrame("empty image payload")
        try:
            image = self._module.load_image_file(BytesIO(image_bytes))
            boxes = self._module.face_locations(image, model="hog")
            encodings = self._module.face_encodings(image, boxes, model="small")
        except Exception as exc:
            raise InvalidFrame(f"unable to decode or analyze frame: {exc}") from exc
        return [
            DetectedFace(
                box=FaceBox(top=top, right=right, bottom=bottom, left=left),
                encoding=[float(value) for value in encoding],
            )
            for (top, right, bottom, left), encoding in zip(boxes, encodings, strict=True)
        ]
