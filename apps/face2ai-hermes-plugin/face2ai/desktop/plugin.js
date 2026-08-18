// Face2AI presence — desktop half of the Hermes `face2ai` plugin.
// Plain ESM, no build step (JSX not allowed): renders a status-bar chip and a pane that show
// who is in front of the local camera, fed by the plugin's own backend namespace
// (`ctx.rest('/presence')` → /api/plugins/face2ai/presence, `ctx.socket('/events')` as accelerator).
// Nothing biometric ever reaches this UI — Face2AI's stream carries states, names, counts, timestamps
// and a hedged mood hint ("wirkt …" — a best-effort guess from facial expression, never a fact).
import { PALETTE_AREA, PANES_AREA, STATUSBAR_AREAS, haptic } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const POLL_MS = 4000
const listeners = new Set()
let latest = { source: 'none', presence: { state: 'NO_SIGNAL' }, connected: false }
let history = []
let pluginCtx = null

function publish() {
  for (const fn of listeners) fn({ latest, history })
}

async function refresh() {
  if (!pluginCtx) return
  try {
    latest = await pluginCtx.rest('/presence')
    if (latest && Array.isArray(latest.history)) history = latest.history
  } catch (error) {
    latest = { source: 'error', error: String(error && error.message ? error.message : error), presence: { state: 'NO_SIGNAL' }, connected: false }
  }
  publish()
}

function onFrame(frame) {
  if (!frame || typeof frame !== 'object') return
  const { event, data } = frame
  if (event === 'hello' || event === 'heartbeat') {
    if (data && data.presence) latest = { ...latest, source: 'live', presence: data.presence, connected: true }
  } else if (event === 'presence' && data) {
    // A transition starts a fresh, mood-less presence (the mood that ended arrives as its own `mood` frame).
    latest = { ...latest, source: 'live', connected: true, presence: { state: data.to_state, identity_id: data.identity_id, display_name: data.display_name, faces: data.faces, since: data.at, stale: false } }
    history = [...history.slice(-29), data]
  } else if (event === 'mood' && data) {
    // Hint began/changed/ended (`to_mood: null`); never a transition, never a reaction.
    latest = { ...latest, presence: { ...(latest.presence || {}), mood: data.to_mood ?? null, valence: data.valence ?? null, arousal: data.arousal ?? null } }
  } else if (event === 'lost') {
    latest = { ...latest, connected: false, source: 'lost', error: data && data.error }
  }
  publish()
}

function usePresence() {
  const [state, setState] = useState({ latest, history })
  useEffect(() => {
    listeners.add(setState)
    return () => listeners.delete(setState)
  }, [])
  return state
}

const LABELS = {
  NO_SIGNAL: { de: 'Kamera aus', en: 'camera off', tone: 'muted' },
  NO_FACE: { de: 'niemand da', en: 'nobody', tone: 'muted' },
  UNKNOWN: { de: 'Unbekannt', en: 'unknown', tone: 'warn' },
  KNOWN: { de: '', en: '', tone: 'ok' },
  MULTIPLE_FACES: { de: 'mehrere', en: 'several', tone: 'warn' },
}
const TONE_CLASS = {
  ok: 'text-(--ui-accent, #82f3d4)',
  warn: 'text-(--ui-warning, #f4ce8a)',
  muted: 'text-(--ui-text-tertiary)',
}

// Hedged mood wording — same literal table as Face2AI's UI (model.js) and the gateway half (presence.py).
const MOOD_LABELS = { Happiness: 'fröhlich', Sadness: 'traurig', Anger: 'verärgert', Fear: 'ängstlich', Surprise: 'überrascht', Disgust: 'angewidert', Contempt: 'abschätzig', Neutral: 'neutral' }

function fmtAxis(value) {
  if (!Number.isFinite(value)) return null
  const rounded = Number(value.toFixed(1)) + 0 // + 0 turns -0 into 0 so tiny negatives print as +0.0
  return (rounded >= 0 ? '+' : '') + rounded.toFixed(1)
}

/** "wirkt fröhlich (Valenz +0.6, Erregung +0.1)" or '' when there is no mood; unknown labels stay hedged. */
function moodLabel(presence) {
  const p = presence || {}
  if (typeof p.mood !== 'string' || !p.mood) return ''
  const word = Object.hasOwn(MOOD_LABELS, p.mood) ? MOOD_LABELS[p.mood] : p.mood.toLowerCase()
  const parts = [['Valenz', fmtAxis(p.valence)], ['Erregung', fmtAxis(p.arousal)]].filter(([, v]) => v !== null).map(([k, v]) => `${k} ${v}`)
  return `wirkt ${word}${parts.length ? ` (${parts.join(', ')})` : ''}`
}

function labelFor(presence, lang = 'de') {
  const p = presence || {}
  const state = p.state || 'NO_SIGNAL'
  if (state === 'KNOWN') return { text: p.display_name || (lang === 'de' ? 'bekannt' : 'known'), tone: 'ok' }
  const entry = LABELS[state] || LABELS.NO_SIGNAL
  return { text: entry[lang] || entry.en, tone: entry.tone }
}

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function Chip() {
  const { latest: current } = usePresence()
  const { text, tone } = labelFor(current.presence)
  const dot = current.connected ? '●' : '○'
  return jsx('button', {
    type: 'button',
    title: current.connected ? `Face2AI · ${current.source}` : `Face2AI nicht verbunden${current.error ? ': ' + current.error : ''}`,
    className: `px-1.5 text-[0.6875rem] ${TONE_CLASS[tone]}`,
    onClick: () => {
      haptic('tap')
      void refresh()
    },
    children: `${dot} 👤 ${text}`,
  })
}

function Pane() {
  const { latest: current, history: items } = usePresence()
  const p = current.presence || {}
  const { text, tone } = labelFor(p)
  const rows = [...items].reverse().slice(0, 12)
  return jsxs('div', {
    className: 'flex h-full flex-col gap-3 p-3 text-sm',
    children: [
      jsxs('div', {
        className: 'flex items-baseline justify-between',
        children: [
          jsx('div', { className: 'text-[0.6875rem] uppercase tracking-wider text-(--ui-text-tertiary)', children: 'Face2AI · Kamera' }),
          jsx('div', { className: 'text-[0.6875rem] text-(--ui-text-tertiary)', children: current.connected ? current.source : 'offline' }),
        ],
      }),
      jsxs('div', {
        children: [
          jsx('div', { className: `text-2xl font-semibold ${TONE_CLASS[tone]}`, children: text }),
          jsx('div', { className: 'text-(--ui-text-tertiary)', children: `${p.state || 'NO_SIGNAL'} · ${p.faces || 0} ${p.faces === 1 ? 'Gesicht' : 'Gesichter'}${p.since ? ' · seit ' + fmtTime(p.since) : ''}${p.stale ? ' · keine frischen Frames' : ''}` }),
          moodLabel(p) ? jsx('div', { className: 'text-[0.75rem] text-(--ui-text-tertiary)', title: 'Vermutung aus dem Gesichtsausdruck, keine Tatsache', children: moodLabel(p) }) : null,
        ],
      }),
      current.error ? jsx('div', { className: 'text-[0.75rem] text-(--ui-warning, #f4ce8a)', children: String(current.error) }) : null,
      jsxs('div', {
        className: 'flex flex-col gap-1',
        children: [
          jsx('div', { className: 'text-[0.6875rem] uppercase tracking-wider text-(--ui-text-tertiary)', children: 'Übergänge' }),
          rows.length === 0
            ? jsx('div', { className: 'text-(--ui-text-tertiary)', children: 'Noch keine Ereignisse.' })
            : rows.map((t, i) => jsxs('div', {
                className: 'flex justify-between gap-2 text-[0.75rem]',
                children: [
                  jsx('span', { className: 'text-(--ui-text-tertiary)', children: fmtTime(t.at) }),
                  jsx('span', { children: `${t.from_state} → ${t.to_state}${t.display_name ? ' · ' + t.display_name : ''}` }),
                ],
              }, `${t.at || i}-${i}`)),
        ],
      }),
      jsxs('div', {
        className: 'mt-auto flex gap-2',
        children: [
          jsx('button', { type: 'button', className: 'rounded border px-2 py-1 text-[0.75rem]', onClick: () => void refresh(), children: 'Aktualisieren' }),
          jsx('button', { type: 'button', className: 'rounded border px-2 py-1 text-[0.75rem]', onClick: () => void pluginCtx?.os.openExternal('http://127.0.0.1:8765/'), children: 'Face2AI öffnen' }),
        ],
      }),
    ],
  })
}

export default {
  id: 'face2ai',
  name: 'Face2AI presence',
  defaultEnabled: false,
  register(ctx) {
    pluginCtx = ctx
    ctx.register({ id: 'chip', area: STATUSBAR_AREAS.right, order: 115, render: () => jsx(Chip, {}) })
    ctx.register({ id: 'pane', area: PANES_AREA, title: 'Face2AI', data: { placement: 'right', width: '280px' }, render: () => jsx(Pane, {}) })
    ctx.register({
      id: 'open-app',
      area: PALETTE_AREA,
      data: { id: 'face2ai.open', label: 'Face2AI: Kamera-App öffnen', keywords: ['face2ai', 'kamera', 'camera', 'presence'], run: () => void ctx.os.openExternal('http://127.0.0.1:8765/') },
    })
    ctx.register({
      id: 'refresh',
      area: PALETTE_AREA,
      data: { id: 'face2ai.refresh', label: 'Face2AI: Präsenz aktualisieren', keywords: ['face2ai', 'presence'], run: () => void refresh() },
    })
    void refresh()
    const timer = setInterval(() => void refresh(), POLL_MS)
    const stopSocket = ctx.socket('/events', onFrame)
    // Disposer (used by hot reload when the host honours it): stop polling and the live socket.
    return () => {
      clearInterval(timer)
      stopSocket()
      pluginCtx = null
    }
  },
}
