# Face2AI

Face2AI is the local product layer built on top of the repository's existing `face_recognition` engine.

## Product flow

`UNKNOWN -> explicit LEARN -> leave frame -> return -> KNOWN -> greeting`

The application is intentionally local-first. Camera frames are processed in memory and are not intentionally persisted. Stored identity records contain display names and face encodings only.

## Architecture

- browser: camera preview, overlays, enrollment with explicit consent, identity management, event stream and spoken greeting; restrained ReactBits-inspired effects implemented as dependency-free CSS/ES modules (see `docs/UI_DIRECTION.md`);
- API: FastAPI on localhost;
- recognition: adapter over the repository's existing `face_recognition` package;
- storage: atomic local JSON file;
- presence + events: `GET /api/presence`, `GET /api/events` (SSE: `hello`, `presence`, `mood`, `store`, `heartbeat`), `POST /api/presence/reset` — the contract for agents / Party Mirror; no biometrics on the wire;
  - `presence` — stable presence changed (`from_state` → `to_state`, names, face count); a transition starts a fresh, mood-less presence and carries no mood fields;
  - `mood` — mood hint began/changed/ended (`from_mood` → `to_mood`, rounded valence/arousal); a `mood` with `to_mood: null` always follows the presence event that ended it (person left, presence expired or was reset), and is also published when expressions are switched off (`POST /api/expression {"enabled": false}`) while a mood is set;
- no LLM, cloud service, database, or security authorization in the recognition app itself. The optional voice agent (`apps/face2ai-agent/`, ADR-002) is a separate process that consumes the events.

## Development

Target recognition runtime: Python 3.11 on macOS. On 2026-08-17 the recognition extra also built and ran on macOS/arm64 with Python 3.12 (dlib 20.0.1) via `uv sync --extra recognition`.

From the repository root:

```bash
uv sync --project apps/face2ai --group dev --extra recognition
uv run --project apps/face2ai face2ai
```

Open `http://127.0.0.1:8765`.

The `face_recognition` dependency is resolved from the repository root through `tool.uv.sources`. The temporary `setuptools<82` compatibility pin exists because the current model package still relies on `pkg_resources`; it is explicit S0 compatibility debt, not a permanent design choice.

## Verification

```bash
PYTHONPATH=apps/face2ai/src pytest apps/face2ai/tests
python -m compileall -q apps/face2ai/src
for file in apps/face2ai/src/face2ai_app/static/js/*.js; do node --check "$file"; done
node --test 'apps/face2ai/tests/js/**/*.test.mjs'
```

Real recognition is not proven by unit tests. Before calling the product flow runtime-verified, run the target-Mac camera smoke described in `docs/boilerplate/VALIDATION.md`.
