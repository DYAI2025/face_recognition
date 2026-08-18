# Face2AI ↔ Hermes plugin

Makes Face2AI's camera presence a first-class input for [hermes-agent](https://github.com/NousResearch/hermes-agent):
Hermes knows on every turn who is in front of the local camera, can be asked explicitly, and the
desktop app shows it live.

```
Mac                                              Hermes host (VPS)
Face2AI :8765 ──SSE /api/events──▶ (ssh -R 8765) ──▶ gateway plugin `face2ai`
   ▲                                                  ├─ pre_llm_call → "[face2ai] Ben steht vor der Kamera …" in every turn
   │ ctx.rest via dashboard :9119 (ssh -L)             ├─ tool presence_now, /presence, system-prompt section
Hermes desktop app (plugin desktop/plugin.js) ◀────── └─ dashboard/plugin_api.py → /api/plugins/face2ai/{presence,history,health,events}
```

One installable folder (`face2ai/`), two halves, both opt-in:

| Half | Where | Enable |
| --- | --- | --- |
| Python (`plugin.yaml`, `__init__.py`, `dashboard/plugin_api.py`) | Hermes host `~/.hermes/plugins/face2ai/` | `hermes plugins enable face2ai` (+ gateway/dashboard restart) |
| Desktop (`desktop/plugin.js`) | the Mac running the desktop app `~/.hermes/plugins/face2ai/` | Settings → Plugins → "Face2AI presence" |

`./deploy.sh` does both (rsync to `hermes-brain`, enable, restart, copy the desktop half).

## What Hermes gets

- **Every turn**: `pre_llm_call` returns `{"context": "[face2ai] …"}` — appended to the user message
  (Hermes' documented seam for live context; system-prompt sections are frozen per session). Withheld
  when the last frame is older than `context_max_age_seconds` (30 s) so Hermes never acts on stale presence.
- **On demand**: tool `presence_now` (JSON incl. recent transitions), slash command `/presence`.
- **Mood hint** (Face2AI expression stage 1): presence snapshots and SSE `mood` frames carry `mood`/`valence`/`arousal`.
  The store keeps them on the current presence (a `presence` transition starts a fresh, mood-less presence;
  `to_mood: null` ends the hint) and `describe()` appends one hedged sentence in the configured language —
  "Ben wirkt fröhlich (Valenz +0.6, Erregung +0.1) – nur ein Hinweis aus dem Gesichtsausdruck, keine Tatsache." /
  "Ben looks happy (valence +0.6, arousal +0.1) — only a hint from facial expression, not a fact." The `[face2ai]`
  line, `presence_now`, `/presence`, the persisted snapshot (dashboard API) and the desktop pane all carry it; a mood
  frame is never a transition, never an announcement and never gates anything. Face2AI itself persists nothing about
  expression; this plugin mirrors the *current* presence snapshot (state, name, coarse mood/valence/arousal) into its
  plugin state file for the dashboard process — overwritten, no history (the snapshot's `history` holds only the last
  10 presence transitions: states, names, timestamps — never a mood). The system-prompt section tells
  Hermes to treat it as a guess — never state it as a fact, never psychoanalyse or probe.
- **Static explanation** in the system prompt: what the `[face2ai]` line means, best-effort, never guess names, never authentication, mood hints are guesses ("wirkt …"), never facts.
- **Optional proactive**: `announce_arrivals: true` + `plugins.entries.face2ai.allow_gateway_injection: true` →
  on a fresh `→ KNOWN` transition the plugin injects a user-turn into the most recent gateway session
  (per-person cooldown). Off by default; the voice agent already greets.

Settings (`plugins.entries.face2ai.settings.*`): `events_url` (default `http://127.0.0.1:8765`),
`inject_context`, `context_max_age_seconds`, `platforms` (e.g. `[api_server, desktop]`),
`announce_arrivals`, `announce_cooldown_seconds`, `language` (`de`/`en`).

## Network

The Hermes host must reach Face2AI. On this setup the Mac's tunnel LaunchAgent
(`~/.hermes-bridge/tunnel-9119.sh`) also carries `-R 127.0.0.1:8765:127.0.0.1:8765`, so the VPS
sees Face2AI at `localhost:8765`; nothing is exposed publicly. Alternatively set `events_url` to the
Mac's Tailscale address.

## Privacy

Only what Face2AI publishes: states, display names, counts, timestamps. No frames, boxes, encodings
or match distances leave the Mac (guarded by Face2AI's tests).

## Verify

```bash
uv run --project ../face2ai --with pytest pytest tests            # 14 unit tests, no Hermes needed
ssh hermes-brain 'bash -lc "hermes plugins list | grep face2ai; curl -s 127.0.0.1:8765/api/presence"'
curl -s -H "Authorization: Bearer <dashboard token>" http://127.0.0.1:9119/api/plugins/face2ai/health   # via the 9119 tunnel
# then ask Hermes (desktop / telegram / voice agent): "Wer steht gerade vor der Kamera?"
```
