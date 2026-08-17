# Face2AI Agent Instructions

## Goal

Preserve the shortest real product loop: `UNKNOWN -> explicit LEARN -> leave -> return -> KNOWN -> greeting`.

## Architecture rules

- Do not modify the upstream `face_recognition/` package for Face2AI product features unless a separate ADR explicitly requires it.
- `domain/` must not import FastAPI, browser code, storage adapters, or `face_recognition`.
- Third-party recognition belongs behind `RecognitionEngine`.
- Persistence belongs behind `IdentityStore`.
- HTTP belongs in `api/`; browser behavior belongs in `static/` (ES modules, no build step; visual rules in `docs/UI_DIRECTION.md`).
- Browser view logic that needs no DOM lives in `static/js/model.js` and is covered by `tests/js/*.test.mjs` (`node --test`).
- New Party Mirror or agent behavior must consume identity/recognition events instead of being inserted into face matching. The event surface is `services/presence.py` (`PresenceTracker`, debounced transitions) + `services/events.py` (`IdentityEventBroker`) exposed as `GET /api/events` (SSE) and `GET /api/presence`; it carries states, names, counts and timestamps only — never frames, boxes or encodings (a test enforces this).
- The voice agent lives in `apps/face2ai-agent/` (LiveKit Agents, own uv project, ADR-002). It subscribes with `?role=agent`; while it is connected the browser leaves the spoken greeting to it (`SystemStatus.agent_connected`).
- Do not persist raw camera frames by default.
- Do not represent face distance as a confidence percentage.
- The browser consumes `RecognitionEvent.can_enroll` / `message` and `SystemStatus.engine_available`; it never re-derives recognition state or engine readiness client-side.
- Destructive actions confirm in a native `<dialog>`, never via `confirm()`/`alert()`.
- Do not use face recognition as authentication or authorization.

## Before changing code

1. State the user-visible outcome.
2. Identify the existing boundary that owns it.
3. Add/adjust acceptance tests first where practical.
4. Keep WIP to one vertical slice.
5. Do not add a database, cloud service, queue, React, Tauri, LLM, or new runtime unless an architecture trigger is documented.

## Required checks

```bash
PYTHONPATH=apps/face2ai/src pytest apps/face2ai/tests
python -m compileall -q apps/face2ai/src
for file in apps/face2ai/src/face2ai_app/static/js/*.js; do node --check "$file"; done
node --test 'apps/face2ai/tests/js/**/*.test.mjs'
```

Mock/injected recognition tests are not evidence that real camera recognition works. Real recognition requires the target-Mac gate in `docs/boilerplate/VALIDATION.md`.
