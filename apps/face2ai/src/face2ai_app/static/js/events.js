// Same-origin SSE client for the browser shell: it listens to `mood` and `action` only. Presence,
// store and heartbeat frames are ignored on purpose — the page derives its own view from the frames
// it sends. The server is the single source of truth for both entry kinds (mood hysteresis and action
// onset/apex/offset are applied there); nothing is re-derived or debounced here. `?role=browser` keeps
// this subscription apart from the voice agent's role, which would make the page hand greetings to it.
// EventSource reconnects by itself (with `Last-Event-ID`), so `onError` fires per failed attempt.

/**
 * Subscribe to the local event stream. Returns a `close()` function.
 * Handlers get the parsed JSON payload; malformed data is dropped, never thrown.
 */
export function subscribeEvents({ onMood, onAction, onOpen, onError } = {}, url = '/api/events?role=browser') {
  if (typeof EventSource !== 'function') {
    onError?.();
    return () => {};
  }
  const source = new EventSource(url);
  const parse = (e) => { try { return JSON.parse(e.data); } catch { return null; } };
  source.addEventListener('mood', (e) => { const d = parse(e); if (d) onMood?.(d); });
  source.addEventListener('action', (e) => { const d = parse(e); if (d) onAction?.(d); });
  source.onopen = () => onOpen?.();
  source.onerror = () => onError?.();
  return () => source.close();
}
