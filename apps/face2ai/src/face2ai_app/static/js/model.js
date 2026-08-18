// Pure view-model helpers for the Face2AI shell. No DOM, no fetch — testable with `node --test`.
// The browser is a consumer of RecognitionEvent objects produced by the API; nothing here
// re-derives recognition state or invents identity data.

export const STATE_LABELS = Object.freeze({
  NO_FACE: { name: 'No identity', sub: 'No face detected', cls: '', message: 'Waiting for a person.' },
  UNKNOWN: { name: 'Unknown', sub: 'Not enrolled', cls: 'unknown', message: 'One unknown face detected. Enrollment is available.' },
  LEARNING: { name: 'Learning', sub: 'Enrollment in progress', cls: 'unknown', message: 'Storing a local face encoding.' },
  KNOWN: { name: 'Known identity', sub: 'Recognized', cls: 'known', message: 'Identity matched.' },
  MULTIPLE_FACES: { name: 'Multiple people', sub: 'Enrollment unavailable', cls: '', message: 'Multiple faces detected. Enrollment is blocked.' },
  ERROR: { name: 'Unavailable', sub: 'Recognition error', cls: 'error', message: 'Recognition error.' },
});

const FALLBACK = Object.freeze({ name: 'Unavailable', sub: 'Unknown state', cls: 'error', message: 'Unrecognized recognition state.' });

/**
 * Turn a RecognitionEvent (see domain/models.py) into display fields.
 * `can_enroll` and `message` come from the server and are never re-derived here.
 */
export function describeEvent(event = {}) {
  const state = typeof event.state === 'string' ? event.state : 'ERROR';
  const faces = Array.isArray(event.faces) ? event.faces : [];
  const primary = faces.length ? faces[0] : null;
  const labels = STATE_LABELS[state] || FALLBACK;
  const distance = Number.isFinite(primary?.match_distance) ? primary.match_distance : null;
  const name = state === 'KNOWN' && primary?.display_name ? primary.display_name : labels.name;
  const serverMessage = typeof event.message === 'string' && event.message ? event.message : null;
  const message = serverMessage || (state === 'KNOWN' && primary?.display_name ? `Identity matched: ${primary.display_name}.` : labels.message);
  return {
    state,
    label: state.replace(/_/g, ' '),
    name,
    sub: labels.sub,
    cls: labels.cls,
    faces: faces.length,
    primary,
    distance,
    canEnroll: event.can_enroll === true,
    message,
  };
}

/** Views for states the server never sends: camera off, and engine unavailable while the camera runs. */
export function offlineView(reason = null) {
  return {
    state: 'OFFLINE',
    label: 'OFFLINE',
    name: 'No identity',
    sub: reason ? `Engine unavailable · ${reason}` : 'Vision inactive',
    cls: reason ? 'error' : '',
    faces: 0,
    primary: null,
    distance: null,
    canEnroll: false,
    message: reason || 'Vision inactive.',
  };
}

/** Key that changes only when the visible state or the resolved identity changes. */
export function transitionKey(event = {}) {
  const primary = Array.isArray(event.faces) && event.faces.length ? event.faces[0] : null;
  return `${event.state || ''}:${primary?.identity_id || ''}`;
}

/**
 * Project a face box from the coordinate space of the frame that was sent to the API
 * ({top,right,bottom,left} in pixels of that JPEG) into a view that displays the frame
 * with `object-fit: cover` semantics (scale to fill, crop the overflow axis, centred).
 */
export function projectBox(box, frame, view) {
  const scale = Math.max(view.width / frame.width, view.height / frame.height);
  const offsetX = (view.width - frame.width * scale) / 2;
  const offsetY = (view.height - frame.height * scale) / 2;
  return {
    x: box.left * scale + offsetX,
    y: box.top * scale + offsetY,
    width: (box.right - box.left) * scale,
    height: (box.bottom - box.top) * scale,
  };
}

/** Greeting policy: a newly seen identity is greeted at once, the same identity only after the cooldown. */
export function shouldGreet(last, identityId, now, cooldownMs) {
  if (!identityId) return false;
  if (last.lastIdentityId !== identityId) return true;
  return now - last.lastAt >= cooldownMs;
}

/** Map a getUserMedia failure to the pill/context wording; only permission problems read as "blocked". */
export function describeCameraError(error) {
  const name = error?.name || '';
  if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') {
    return { pill: 'CAMERA BLOCKED', context: 'Permission blocked' };
  }
  return { pill: 'CAMERA UNAVAILABLE', context: name ? `Unavailable · ${name}` : 'Unavailable' };
}

// ---------- expression (Stage 1): a best-effort mood hint, never a fact ----------

/**
 * Wording tables for `Expression.dominant` (see domain/models.py EMOTIONS). Every label is hedged
 * ("wirkt …" / "looks …"): the engine reports how a face *appears*, never how someone *is* — and
 * nothing here may read as a finding, a diagnosis or a lie detector.
 */
const EXPRESSION_WORDS = Object.freeze({
  de: Object.freeze({
    prefix: 'wirkt ',
    labels: Object.freeze({ Happiness: 'fröhlich', Sadness: 'traurig', Anger: 'verärgert', Fear: 'ängstlich', Surprise: 'überrascht', Disgust: 'angewidert', Contempt: 'abschätzig', Neutral: 'neutral' }),
  }),
  en: Object.freeze({
    prefix: 'looks ',
    labels: Object.freeze({ Happiness: 'happy', Sadness: 'sad', Anger: 'angry', Fear: 'fearful', Surprise: 'surprised', Disgust: 'disgusted', Contempt: 'contemptuous', Neutral: 'neutral' }),
  }),
});

/** Tile tone per label: mint for a pleasant hint, neutral for neutral/surprise, amber for the rest; unknown labels stay neutral. */
const EXPRESSION_TONES = Object.freeze({ Happiness: 'ok', Neutral: 'muted', Surprise: 'muted', Sadness: 'warn', Anger: 'warn', Fear: 'warn', Disgust: 'warn', Contempt: 'warn' });

/**
 * Turn `DetectedFace.expression` (or null) into `{ label, tone, valence, arousal }` — or null when
 * there is nothing to say. Unknown labels are hedged too and never throw.
 */
export function describeExpression(expr, lang = 'de') {
  const dominant = typeof expr?.dominant === 'string' ? expr.dominant : '';
  if (!dominant) return null;
  const words = EXPRESSION_WORDS[lang] || EXPRESSION_WORDS.de;
  const word = Object.hasOwn(words.labels, dominant) ? words.labels[dominant] : dominant.toLowerCase();
  return {
    label: `${words.prefix}${word}`,
    tone: EXPRESSION_TONES[dominant] || 'muted',
    valence: Number.isFinite(expr.valence) ? expr.valence : null,
    arousal: Number.isFinite(expr.arousal) ? expr.arousal : null,
  };
}

/** Bar geometry for valence/arousal: -1..1 → 0..100 (%), clamped; null when there is no number. */
export function axisPercent(value) {
  if (!Number.isFinite(value)) return null;
  return Math.round(Math.min(1, Math.max(-1, value)) * 50 + 50);
}

/**
 * Event-stream policy for mood entries. Per-frame hints flicker; the log is an evidence layer,
 * so a hedged label is logged only once it has held for `stableTicks` consecutive frames and
 * differs from the last logged one. `stableTicks` frames without a label end the mood, so the
 * same mood logs again when it returns (mirrors the server-side MoodTracker's reset).
 * Returns the next tracker plus `log` (the label to log, or null). Start with `trackMood(null, …)`.
 */
export function trackMood(prev, label, stableTicks = 3) {
  const t = prev || { candidate: null, streak: 0, missing: 0, logged: null };
  if (!label) {
    const missing = t.missing + 1;
    return { candidate: null, streak: 0, missing, logged: missing >= stableTicks ? null : t.logged, log: null };
  }
  const streak = label === t.candidate ? t.streak + 1 : 1;
  const log = streak >= stableTicks && label !== t.logged ? label : null;
  return { candidate: label, streak, missing: 0, logged: log || t.logged, log };
}
