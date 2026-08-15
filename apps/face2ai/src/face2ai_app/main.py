from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from face2ai_app.adapters.face_recognition_engine import FaceRecognitionEngine
from face2ai_app.adapters.json_identity_store import JsonIdentityStore
from face2ai_app.api.routes import router
from face2ai_app.config import Settings
from face2ai_app.services.identity_service import IdentityService

STATIC_DIR = Path(__file__).parent / "static"


def create_app(*, settings: Settings | None = None, engine=None, store=None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    recognition_engine = engine or FaceRecognitionEngine()
    identity_store = store or JsonIdentityStore(app_settings.identity_store_path)
    app = FastAPI(title="Face2AI", version="0.1.0", docs_url="/api/docs", redoc_url=None)
    app.state.settings = app_settings
    app.state.identity_service = IdentityService(engine=recognition_engine, store=identity_store, tolerance=app_settings.match_tolerance)
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
