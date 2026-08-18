# Face2AI

Face2AI is the local product layer built on top of the repository's existing `face_recognition` engine.

## Product flow

`UNKNOWN -> explicit LEARN -> leave frame -> return -> KNOWN -> greeting`

The application is intentionally local-first. Camera frames are processed in memory and are not intentionally persisted. Stored identity records contain display names and face encodings only.

## Architecture

- browser: camera preview, overlays, enrollment with explicit consent, identity management, event stream and spoken greeting; restrained ReactBits-inspired effects implemented as dependency-free CSS/ES modules (see `docs/UI_DIRECTION.md`);
- API: FastAPI on localhost;
- recognition: adapter over the repository's existing `face_recognition` package;
- expression (opt-in, ADR-003): a second port `ExpressionEngine` beside recognition — MediaPipe Face Landmarker + EmotiEffLib, local, CPU; attaches a hedged per-face hint (`faces[].expression`) and a debounced `Presence.mood`; never part of matching, enrollment or greeting — see [Expression hints](#expression-hints-opt-in);
- storage: atomic local JSON file;
- presence + events: `GET /api/presence`, `GET /api/events` (SSE: `hello`, `presence`, `mood`, `action`, `store`, `heartbeat`), `POST /api/presence/reset` — the contract for agents / Party Mirror; no biometrics on the wire;
  - `presence` — stable presence changed (`from_state` → `to_state`, names, face count); a transition starts a fresh, mood-less presence and carries no mood fields;
  - `mood` — mood hint began/changed/ended (`from_mood` → `to_mood`, rounded valence/arousal); a `mood` with `to_mood: null` always follows the presence event that ended it (person left, presence expired or was reset), and is also published when expressions are switched off (`POST /api/expression {"enabled": false}`) while a mood is set; semantics in [Expression hints](#expression-hints-opt-in);
  - `action` — a completed facial action (`action` ∈ smile/frown/brow_raise/brow_furrow/eye_squint/eyes_wide/nose_wrinkle/lip_press, `onset_at`/`apex_at`/`offset_at`, `peak`, `duration_ms`, `frames`, names) — expression *dynamics* at frame-rate resolution (~0.6 s from the browser loop), never micro-expressions; a hint, never a fact, and consumers must not react to it with behaviour; an action whose offset is never seen (person left, reset, toggle off) produces no event;
- no LLM, cloud service, database, or security authorization in the recognition app itself. The optional voice agent (`apps/face2ai-agent/`, ADR-002) is a separate process that consumes the events.

Architecture decisions: `docs/architecture/ADR-001-local-modular-monolith.md` (local modular monolith), `ADR-002-voice-agent.md` (event-consuming voice agent), `ADR-003-expression-engine.md` (opt-in local expression hints).

## Development

Target recognition runtime: Python 3.11 on macOS. On 2026-08-17 the recognition extra also built and ran on macOS/arm64 with Python 3.12 (dlib 20.0.1) via `uv sync --extra recognition`.

From the repository root:

```bash
uv sync --project apps/face2ai --group dev --extra recognition
uv run --project apps/face2ai face2ai
```

Open `http://127.0.0.1:8765`.

The `face_recognition` dependency is resolved from the repository root through `tool.uv.sources`. The temporary `setuptools<82` compatibility pin exists because the current model package still relies on `pkg_resources`; it is explicit S0 compatibility debt, not a permanent design choice.

## Expression hints (opt-in)

Stage 1 of the expression engine (ADR-003) reads facial expression **locally** and only when asked. Face2AI itself persists nothing about expression (the Hermes plugin mirrors the *current* presence snapshot — state, name, coarse mood/valence/arousal — into its plugin state file for the dashboard process: overwritten, no history), nothing leaves the machine, and it never gates recognition, enrollment or the greeting. It is a hint about how a face *appears* to a model — the UI says "looks happy", the German consumers say "wirkt fröhlich" — never a fact, never a lie detector. "Micro-expressions" in the strict (involuntary, < 500 ms) sense are out of scope; Stage 1 delivers expression + intensity + head pose per frame plus a debounced mood.

Install and fetch both model assets (≈ 0.75 GB installed — mediapipe pulls jax/jaxlib, opencv, matplotlib). The fetch script downloads BOTH files up front — the MediaPipe landmarker and EmotiEffLib's ONNX model into the exact cache path emotiefflib expects — so startup never touches the network; if either file is missing the engine reports `expression_available:false` with the path and this script in the reason instead of downloading anything:

```bash
uv sync --project apps/face2ai --group dev --extra recognition --extra expression
bash apps/face2ai/scripts/fetch-expression-models.sh      # face_landmarker.task (3.7 MB) → $FACE2AI_EXPRESSION_MODELS_DIR
                                                          # enet_b0_8_va_mtl.onnx (16 MB)  → ~/.emotiefflib/
```

`mediapipe` is pinned to 0.10.21 (1.0.1 aborts on macOS in `DrishtiMetalHelper`; the adapter uses the CPU delegate) and declares `numpy<2`, so `pyproject.toml` overrides numpy to 2.3.5 — verified working on the M1. Without the extra everything degrades cleanly: `expression_available:false` with a reason, toggle disabled, `faces[].expression` null, no `mood` events.

Environment: `FACE2AI_EXPRESSION_ENABLED` (default `false`; pre-enables only an available engine), `FACE2AI_EXPRESSION_MODELS_DIR` (default `$FACE2AI_DATA_DIR/models`, i.e. `~/.face2ai/models`), `FACE2AI_MOOD_STABLE_TICKS` (3), `FACE2AI_MOOD_MIN_SCORE` (0.5).

API surface:

- `POST /api/expression` with `{"enabled": true|false}` — per-session runtime toggle, off by default; 409 when enabling while the engine is unavailable, disabling is always accepted (200); switching off ends the current mood immediately (a `mood` event with `to_mood: null`). Response `{"enabled", "available"}`.
- `GET /api/status` — `expression_available`, `expression_reason`, `expression_enabled`.
- `POST /api/recognize` — while enabled each `faces[]` observation carries `expression`: `{dominant, scores{Anger,Contempt,Disgust,Fear,Happiness,Neutral,Sadness,Surprise}, valence, arousal, blendshapes{name: 0..1, only ≥ 0.2}, yaw, pitch, roll}` — or `null` when the engine could not read that face. No landmarks, crops or pixels are ever on the wire.
- `GET /api/presence` / SSE `hello`, `heartbeat` — `Presence.mood` (the hysteresis label, null until committed) and `valence`, `arousal` — since Stage 2 the *live* smoothed values (EMA over the readable frames, rounded to 3), present as soon as one frame was readable, null while nothing is; the `mood` event keeps the values frozen at commit.
- `GET /api/expression/timeline?seconds=600&identity_id=` — the bounded in-memory affect history `{seconds, samples[{at, identity_id, display_name, mood, valence, arousal}], moods[MoodTransition], actions[ActionEvent]}` of the last `seconds` (10..3600, default 600 = `FACE2AI_TIMELINE_SECONDS`), oldest first, optionally narrowed to one identity. Never persisted: cleared by `POST /api/presence/reset` and by a restart.
- SSE `mood` — emitted once per stable mood change (server-side `MoodTracker`: EMA over the scores, alpha 0.5; a label commits when the candidate has led for `FACE2AI_MOOD_STABLE_TICKS` consecutive frames and its EMA is ≥ `FACE2AI_MOOD_MIN_SCORE` at that tick; valence/arousal are frozen at commit). The mood follows the stable presence: a presence change, `stable_ticks` frames without a readable expression (several faces, no face, expression off), presence expiry/reset or the toggle-off end it with `to_mood: null`. The browser's "Mood" event-stream entries are a separate 3-frame debounce of the per-frame hints; the wire mood is the server's.

Measured on the M1 (2026-08-18, one face): adapter alone (full-frame decode + landmarker + EmotiEffLib, `examples/obama.jpg`, 910×1137) `analyze` ~146 ms cold / ~77 ms warm on the first measurement, ~84 / ~27 ms on a later warm run; live `POST /api/recognize` round trip via curl (dlib HOG + expression) `examples/obama-480p.jpg` (853×480) ~130 ms → ~150 ms with expression, `examples/obama.jpg` ~300 ms → ~330–380 ms — expression adds ~30–50 ms per frame, inside the browser's 450 ms loop.

Shell and `/assets/*` are served with `Cache-Control: no-cache` (ETag revalidation) since 2026-08-18 — a redeploy must never pair a fresh `app.js` with a heuristically cached `model.js` (this broke the shell once during verification).

Legal note, honesty section, dependency facts and review triggers: `docs/architecture/ADR-003-expression-engine.md`.

## Verification

```bash
PYTHONPATH=apps/face2ai/src pytest apps/face2ai/tests
python -m compileall -q apps/face2ai/src
for file in apps/face2ai/src/face2ai_app/static/js/*.js; do node --check "$file"; done
node --test 'apps/face2ai/tests/js/**/*.test.mjs'
```

Real recognition is not proven by unit tests. Before calling the product flow runtime-verified, run the target-Mac camera smoke described in `docs/boilerplate/VALIDATION.md`.
