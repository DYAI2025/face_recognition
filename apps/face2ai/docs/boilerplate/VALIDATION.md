# Validation

## Automated gates

Run from repository root:

```bash
PYTHONPATH=apps/face2ai/src pytest apps/face2ai/tests
python -m compileall -q apps/face2ai/src
for file in apps/face2ai/src/face2ai_app/static/js/*.js; do node --check "$file"; done
node --test 'apps/face2ai/tests/js/**/*.test.mjs'
```

## Runtime shell smoke

```bash
PYTHONPATH=apps/face2ai/src uvicorn face2ai_app.main:app --host 127.0.0.1 --port 8765
curl -fsS http://127.0.0.1:8765/healthz
```

`/healthz` proves the app process only. `/readyz` returns 503 until the actual face-recognition engine can import and initialize.

## Required target-Mac recognition smoke

This is mandatory before claiming the real product flow works:

1. `uv sync --project apps/face2ai --group dev --extra recognition` on the target Mac.
2. Start Face2AI.
3. Confirm `/readyz` returns `ready: true`.
4. Grant browser camera permission.
5. Verify `NO_FACE -> UNKNOWN` with one consenting adult participant.
6. Enroll the participant explicitly.
7. Leave frame, return, verify `KNOWN` and spoken greeting.
8. Verify delete-one and erase-all remove the identity.
9. Record versions, command outputs, match distances, failures, and latency observation.

Unit or injected-adapter tests do not satisfy this real-boundary gate.

## Voice agent gate (apps/face2ai-agent, ADR-002)

```bash
cd apps/face2ai-agent && uv sync --group dev --extra groq
uv run pytest                                   # unit tests, no network
uv run face2ai-agent check                      # live: Face2AI reachable, SSE hello, LLM round trip (+ local TTS)
uv run face2ai-agent smoke "Wer ist gerade vor der Kamera?"   # live text turn with tool calls
uv run face2ai-agent console                    # manual: speak; step in front of the camera as an enrolled person -> spoken greeting by name
```

Required manual gate: with the browser running and one enrolled adult, `console` must greet the
person by name when Face2AI recognizes them, must not greet again within the cooldown, and the
browser's event stream must show "Greeting delegated" instead of speaking itself.

## Expression gate (ADR-003, opt-in mood hints)

Unit tests inject a `FakeExpressionEngine`; the adapter's pure helpers run without the extra. None of that proves
the models read a real face. Mandatory on the target Mac before claiming the expression stage runs:

```bash
uv sync --project apps/face2ai --group dev --extra recognition --extra expression
bash apps/face2ai/scripts/fetch-expression-models.sh
uv run --project apps/face2ai face2ai
curl -s http://127.0.0.1:8765/api/status | grep -o '"expression_[a-z]*":[^,}]*'      # expression_available:true, expression_enabled:false
curl -s -X POST http://127.0.0.1:8765/api/expression -H 'content-type: application/json' -d '{"enabled":true}'   # {"enabled":true,"available":true}
curl -s -N http://127.0.0.1:8765/api/events?role=probe                               # leave running: expect `event: mood` frames below
```

1. Toggle-on works from the browser as well ("Expression: on"; the button is disabled while `/api/status` says the engine is unavailable).
2. Smile at the camera → the expression tile reads "looks happy" within ~3 ticks (the tile is per frame; the "Mood" event-stream entry appears once the label has held for 3 frames).
3. Frown / look sad → the tile changes (e.g. "looks sad" or "looks neutral"); valence bar moves left.
4. `/api/events` shows `event: mood` with `to_mood` for the change, and `/api/presence` carries `mood`, `valence`, `arousal`.
5. Leave the frame → after the presence transition a `mood` event with `to_mood: null` follows it.
6. `POST /api/expression {"enabled": false}` → next `/api/recognize` has `faces[].expression: null`, a `mood` end event was published, tile shows "off".
7. Voice agent (browser + agent running, one enrolled adult): `uv run face2ai-agent smoke "Wie wirke ich gerade?"` → hedged German answer ("… wirkt …", "nur ein Hinweis"), never "ist fröhlich".
8. Hermes plugin: `/presence` in Hermes shows the mood line ("wirkt … – nur ein Hinweis aus dem Gesichtsausdruck, keine Tatsache").
9. Record: mediapipe/emotiefflib/onnxruntime versions, per-frame `analyze` timing (M1 reference: ~146 ms cold, ~77 ms warm for one face), which labels you could and could not provoke.

Nothing in this gate may be described as the person *being* happy/sad — record what the tile *said*.
