from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from face2ai_app import __version__
from face2ai_app.domain.errors import EnrollmentRejected, InvalidFrame, RecognitionUnavailable
from face2ai_app.domain.models import (
    IdentitySummary,
    Presence,
    RecognitionEvent,
    StoreEvent,
    StoreEventKind,
    SystemStatus,
)
from face2ai_app.services.events import IdentityEvent, IdentityEventBroker
from face2ai_app.services.presence import PresenceTracker

router = APIRouter()

EVENT_ROLE_AGENT = "agent"
AGENT_HEADER = "X-Face2AI-Agent"  # "1"/"0" on recognize responses: fresh greeting-ownership signal for the browser


def _service(request: Request):
    return request.app.state.identity_service


def _settings(request: Request):
    return request.app.state.settings


def _presence(request: Request) -> PresenceTracker:
    return request.app.state.presence


def _events(request: Request) -> IdentityEventBroker:
    return request.app.state.events


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


def _publish_store_event(
    request: Request, kind: StoreEventKind, *, identity_id: str | None, display_name: str | None, identity_count: int
) -> None:
    _events(request).publish(
        "store",
        StoreEvent(
            at=datetime.now(timezone.utc),
            kind=kind,
            identity_id=identity_id,
            display_name=display_name,
            identity_count=identity_count,
        ),
    )


def _publish_presence(request: Request, transition) -> None:
    if transition is not None:
        _events(request).publish("presence", transition)


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
    settings = _settings(request)
    events = _events(request)
    expression_available = _expression_available(service)
    return SystemStatus(
        version=__version__,
        engine_available=service.engine.available,
        engine_reason=service.engine.availability_reason,
        identity_count=len(service.store.list()),
        greeting_cooldown_seconds=settings.greeting_cooldown_seconds,
        agent_connected=events.connected(EVENT_ROLE_AGENT),
        event_subscribers=events.subscriber_count,
        expression_available=expression_available,
        expression_reason=None if expression_available else _expression_reason(service),
        expression_enabled=bool(service.expression_enabled),
    )


def _expression_available(service) -> bool:
    return service.expression is not None and bool(service.expression.available)


def _expression_reason(service) -> str:
    if service.expression is None:
        return "not configured"
    return service.expression.availability_reason or "expression engine unavailable"


class ExpressionToggle(BaseModel):
    enabled: bool


@router.post("/api/expression")
async def set_expression(request: Request, body: ExpressionToggle) -> dict[str, bool]:
    """Runtime opt-in: attach best-effort expression hints to recognize responses. Off by default.

    Enabling needs a loaded engine (409 otherwise); disabling is always allowed.
    """
    service = _service(request)
    available = _expression_available(service)
    if body.enabled and not available:
        raise HTTPException(status_code=409, detail=f"expression engine unavailable: {_expression_reason(service)}")
    service.expression_enabled = body.enabled
    return {"enabled": service.expression_enabled, "available": available}


@router.post("/api/recognize", response_model=RecognitionEvent)
async def recognize(request: Request, response: Response) -> RecognitionEvent:
    body = await _image_body(request)
    try:
        # dlib work runs off the event loop so SSE subscribers keep receiving heartbeats/events.
        event = await run_in_threadpool(_service(request).recognize, body)
    except RecognitionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InvalidFrame as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _publish_presence(request, _presence(request).observe(event))
    response.headers[AGENT_HEADER] = "1" if _events(request).connected(EVENT_ROLE_AGENT) else "0"
    return event


@router.post("/api/enroll", response_model=IdentitySummary, status_code=201)
async def enroll(
    request: Request,
    display_name: str = Query(min_length=1, max_length=80),
    consent: bool = Query(default=False),
) -> IdentitySummary:
    body = await _image_body(request)
    service = _service(request)
    try:
        summary = await run_in_threadpool(service.enroll, body, display_name=display_name, consent=consent)
    except RecognitionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (EnrollmentRejected, InvalidFrame) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    count = await run_in_threadpool(lambda: len(service.store.list()))
    _publish_store_event(request, StoreEventKind.ENROLLED, identity_id=summary.id, display_name=summary.display_name, identity_count=count)
    return summary


@router.get("/api/identities", response_model=list[IdentitySummary])
def identities(request: Request) -> list[IdentitySummary]:
    return _service(request).summaries()


@router.delete("/api/identities/{identity_id}", status_code=204)
async def delete_identity(identity_id: str, request: Request) -> Response:
    store = _service(request).store

    def _delete() -> tuple[bool, str | None, int]:
        display_name = next((r.display_name for r in store.list() if r.id == identity_id), None)
        deleted = store.delete(identity_id)
        return deleted, display_name, len(store.list()) if deleted else 0

    deleted, display_name, count = await run_in_threadpool(_delete)
    if not deleted:
        raise HTTPException(status_code=404, detail="identity not found")
    _publish_store_event(request, StoreEventKind.DELETED, identity_id=identity_id, display_name=display_name, identity_count=count)
    return Response(status_code=204)


@router.delete("/api/identities")
async def delete_all_identities(request: Request) -> dict[str, int]:
    deleted = await run_in_threadpool(_service(request).store.clear)
    _publish_store_event(request, StoreEventKind.ERASED, identity_id=None, display_name=None, identity_count=0)
    return {"deleted": deleted}


# ----------------------------------------------------------------- presence + events


@router.get("/api/presence", response_model=Presence)
async def presence(request: Request) -> Presence:
    _publish_presence(request, _presence(request).expire())
    return _presence(request).snapshot()


@router.post("/api/presence/reset", response_model=Presence)
async def reset_presence(request: Request) -> Presence:
    """Browser stopped/paused the camera or the page is going away: presence returns to NO_SIGNAL."""
    _publish_presence(request, _presence(request).reset())
    return _presence(request).snapshot()


def _sse(event: str, data: dict[str, Any], event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"


def _sse_event(event: IdentityEvent) -> str:
    return _sse(event.kind, {"sequence": event.sequence, **event.payload}, event.sequence)


@router.get("/api/events")
async def events(
    request: Request,
    role: str = Query(default="client", min_length=1, max_length=32),
    after: int | None = Query(default=None, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Server-Sent Events: `hello`, then `presence` / `store` events, `heartbeat` while idle.

    Consumers such as the voice agent subscribe with ``?role=agent``; the browser then knows an
    agent is present (``/api/status.agent_connected``) and leaves greetings to it. Reconnects may
    pass ``Last-Event-ID`` (or ``?after=``) to replay buffered events.
    """
    broker = _events(request)
    tracker = _presence(request)
    settings = _settings(request)
    resume_from = after
    if resume_from is None and last_event_id and last_event_id.isdigit():
        resume_from = int(last_event_id)

    async def stream() -> AsyncIterator[str]:
        subscription = broker.subscribe(role)
        last_sent = subscription.since_sequence
        try:
            _publish_presence(request, tracker.expire())
            yield _sse(
                "hello",
                {
                    "presence": tracker.snapshot().model_dump(mode="json"),
                    "last_sequence": subscription.since_sequence,
                    "greeting_cooldown_seconds": settings.greeting_cooldown_seconds,
                    "engine_available": bool(_service(request).engine.available),
                },
            )
            if resume_from is not None:
                # Replay only up to the sequence seen at subscribe time; everything after that
                # arrives through the queue, so nothing is delivered twice.
                for missed in broker.replay(resume_from, up_to=subscription.since_sequence):
                    yield _sse_event(missed)
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(
                        subscription.queue.get(), timeout=settings.events_heartbeat_seconds
                    )
                except asyncio.TimeoutError:
                    expired = tracker.expire()
                    if expired is not None:
                        _publish_presence(request, expired)  # delivered through the queue on the next loop
                        continue
                    yield _sse("heartbeat", {"presence": tracker.snapshot().model_dump(mode="json")})
                    continue
                if event.sequence <= last_sent:
                    continue
                last_sent = event.sequence
                yield _sse_event(event)
        finally:
            broker.unsubscribe(subscription)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
