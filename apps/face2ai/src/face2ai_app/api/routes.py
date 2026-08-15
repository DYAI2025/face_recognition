from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from face2ai_app import __version__
from face2ai_app.domain.errors import EnrollmentRejected, InvalidFrame, RecognitionUnavailable
from face2ai_app.domain.models import IdentitySummary, RecognitionEvent, SystemStatus

router = APIRouter()


def _service(request: Request):
    return request.app.state.identity_service


def _settings(request: Request):
    return request.app.state.settings


async def _image_body(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "")
    if not (content_type.startswith("image/jpeg") or content_type.startswith("image/png")):
        raise HTTPException(status_code=415, detail="content-type must be image/jpeg or image/png")
    body = await request.body()
    if len(body) > _settings(request).max_frame_bytes:
        raise HTTPException(status_code=413, detail="image payload exceeds configured limit")
    if not body:
        raise HTTPException(status_code=400, detail="empty image payload")
    return body


@router.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readiness(request: Request, response: Response) -> dict[str, str | bool | None]:
    service = _service(request)
    ready = bool(service.engine.available)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"ready": ready, "reason": service.engine.availability_reason}


@router.get("/api/status", response_model=SystemStatus)
def system_status(request: Request) -> SystemStatus:
    service = _service(request)
    return SystemStatus(version=__version__, engine_available=service.engine.available, engine_reason=service.engine.availability_reason, identity_count=len(service.store.list()))


@router.post("/api/recognize", response_model=RecognitionEvent)
async def recognize(request: Request) -> RecognitionEvent:
    try:
        return _service(request).recognize(await _image_body(request))
    except RecognitionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InvalidFrame as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/enroll", response_model=IdentitySummary, status_code=201)
async def enroll(request: Request, display_name: str = Query(min_length=1, max_length=80), consent: bool = Query(default=False)) -> IdentitySummary:
    try:
        return _service(request).enroll(await _image_body(request), display_name=display_name, consent=consent)
    except RecognitionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (EnrollmentRejected, InvalidFrame) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/identities", response_model=list[IdentitySummary])
def identities(request: Request) -> list[IdentitySummary]:
    return _service(request).summaries()


@router.delete("/api/identities/{identity_id}", status_code=204)
def delete_identity(identity_id: str, request: Request) -> Response:
    if not _service(request).store.delete(identity_id):
        raise HTTPException(status_code=404, detail="identity not found")
    return Response(status_code=204)


@router.delete("/api/identities")
def delete_all_identities(request: Request) -> dict[str, int]:
    return {"deleted": _service(request).store.clear()}
