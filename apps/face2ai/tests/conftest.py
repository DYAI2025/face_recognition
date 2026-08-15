from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from face2ai_app.adapters.json_identity_store import JsonIdentityStore
from face2ai_app.config import Settings
from face2ai_app.domain.models import DetectedFace, FaceBox
from face2ai_app.main import create_app


class FakeEngine:
    available = True
    availability_reason = None

    def __init__(self) -> None:
        self.faces: list[DetectedFace] = []

    def detect(self, image_bytes: bytes) -> list[DetectedFace]:
        return self.faces


@pytest.fixture
def fake_engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def client(tmp_path: Path, fake_engine: FakeEngine) -> TestClient:
    settings = Settings(data_dir=tmp_path)
    store = JsonIdentityStore(settings.identity_store_path)
    return TestClient(create_app(settings=settings, engine=fake_engine, store=store))


@pytest.fixture
def face() -> DetectedFace:
    return DetectedFace(box=FaceBox(top=10, right=110, bottom=120, left=20), encoding=[0.1] * 128)
