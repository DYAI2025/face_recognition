from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from face2ai_app.adapters.face_recognition_engine import FaceRecognitionEngine
from face2ai_app.adapters.json_identity_store import JsonIdentityStore
from face2ai_app.adapters.mediapipe_expression import MediaPipeExpressionEngine
from face2ai_app.api.routes import router
from face2ai_app.config import Settings
from face2ai_app.domain.errors import IdentityStoreCorrupted
from face2ai_app.services.events import IdentityEventBroker
from face2ai_app.services.identity_service import IdentityService
from face2ai_app.services.mood import MoodTracker
from face2ai_app.services.presence import PresenceTracker

STATIC_DIR = Path(__file__).parent / "static"

logger = logging.getLogger(__name__)


def _log_engine(name: str, available: bool, reason: str | None, *, level: int = logging.WARNING) -> None:
    """One startup line per engine; ``level`` applies to the unavailable case."""
    if available:
        logger.info("%s engine available", name)
    else:
        logger.log(level, "%s engine unavailable: %s", name, reason or "no reason given")


def create_app(*, settings: Settings | None = None, engine=None, store=None, expression=None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    recognition_engine = engine or FaceRecognitionEngine()
    identity_store = store or JsonIdentityStore(app_settings.identity_store_path)
    # Always constructed: it is unavailable-not-crashing when the extra or the model asset is missing.
    expression_engine = expression or MediaPipeExpressionEngine(app_settings.expression_models_dir)
    _log_engine("recognition", recognition_engine.available, recognition_engine.availability_reason)
    # Expression is opt-in: unavailable while nobody asked is information; unavailable while
    # FACE2AI_EXPRESSION_ENABLED is set is the one warning (the opt-in then stays off).
    _log_engine(
        "expression",
        expression_engine.available,
        expression_engine.availability_reason,
        level=logging.WARNING if app_settings.expression_enabled else logging.INFO,
    )

    app = FastAPI(title="Face2AI", version="0.1.0", docs_url="/api/docs", redoc_url=None)
    app.state.settings = app_settings
    service = IdentityService(
        engine=recognition_engine,
        store=identity_store,
        tolerance=app_settings.match_tolerance,
        expression=expression_engine,
    )
    # Opt-in: env can pre-enable, but only an available engine; POST /api/expression toggles at runtime.
    service.expression_enabled = bool(app_settings.expression_enabled and expression_engine.available)
    app.state.identity_service = service
    # Presence + events: derived from RecognitionEvents, consumed by agents / Party Mirror.
    # They never touch matching and never carry frames or encodings.
    app.state.presence = PresenceTracker(
        stable_ticks=app_settings.presence_stable_ticks,
        stale_after=timedelta(seconds=app_settings.presence_stale_seconds),
    )
    # Mood decorates the presence (a hint, never a fact); fed only while expression is enabled.
    app.state.mood = MoodTracker(stable_ticks=app_settings.mood_stable_ticks, min_score=app_settings.mood_min_score)
    app.state.events = IdentityEventBroker(buffer_size=app_settings.events_buffer_size)

    @app.exception_handler(IdentityStoreCorrupted)
    async def identity_store_corrupted_handler(
        request: Request, exc: IdentityStoreCorrupted
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    app.include_router(router)
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()


def run() -> None:
    settings = Settings.from_env()
    uvicorn.run("face2ai_app.main:app", host=settings.host, port=settings.port, reload=False)
