# Face2AI Agent Instructions

## Goal

Preserve the shortest real product loop: `UNKNOWN -> explicit LEARN -> leave -> return -> KNOWN -> greeting`.

## Architecture rules

- Do not modify the upstream `face_recognition/` package for Face2AI product features unless a separate ADR explicitly requires it.
- `domain/` must not import FastAPI, browser code, storage adapters, or `face_recognition`.
- Third-party recognition belongs behind `RecognitionEngine`.
- Persistence belongs behind `IdentityStore`.
- HTTP belongs in `api/`; browser behavior belongs in `static/`.
- New Party Mirror or agent behavior must consume identity/recognition events instead of being inserted into face matching.
- Do not persist raw camera frames by default.
- Do not represent face distance as a confidence percentage.
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
```

Mock/injected recognition tests are not evidence that real camera recognition works. Real recognition requires the target-Mac gate in `docs/boilerplate/VALIDATION.md`.
