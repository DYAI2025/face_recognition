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
