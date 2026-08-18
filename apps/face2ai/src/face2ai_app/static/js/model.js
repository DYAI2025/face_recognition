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
    tone: Object.hasOwn(EXPRESSION_TONES, dominant) ? EXPRESSION_TONES[dominant] : 'muted',
    valence: Number.isFinite(expr.valence) ? expr.valence : null,
    arousal: Number.isFinite(expr.arousal) ? expr.arousal : null,
  };
}

/** Bar geometry for valence/arousal: -1..1 → 0..100 (%), clamped; null when there is no number. */
export function axisPercent(value) {
  if (!Number.isFinite(value)) return null;
  return Math.round(Math.min(1, Math.max(-1, value)) * 50 + 50);
}

/** Signed two-decimal label for a valence/arousal axis ("+0.60", "-0.50"); -0.004 is "+0.00", never "-0.00"; null when there is no number. */
export function formatAxis(value) {
  if (!Number.isFinite(value)) return null;
  const v = Number(value.toFixed(2)) + 0; // + 0 turns -0 into 0 so the sign check below is honest
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}`;
}

// ---------- expression dynamics (Stage 2): action entries + valence sparkline ----------

/**
 * Wording tables for `ActionEvent.action` (see domain/models.py ACTIONS). An action is a description of
 * a movement ("brief smile (0.9 s)"), never a claim about the person and never a finding. Timing is
 * quantized to the frame rate (~0.6 s), hence "brief" ≤ 1 s and "held" ≥ 5 s rather than any
 * sub-second vocabulary (which the loop cannot resolve). Both languages stay here so the view-model is bilingual; app.js picks
 * English (`EXPRESSION_LANG`).
 */
const ACTION_WORDS = Object.freeze({
  en: Object.freeze({
    brief: 'brief ',
    held: 'held ',
    labels: Object.freeze({ smile: 'smile', frown: 'frown', brow_raise: 'brow raise', brow_furrow: 'brow furrow', eye_squint: 'eye squint', eyes_wide: 'eyes wide', nose_wrinkle: 'nose wrinkle', lip_press: 'lip press' }),
  }),
  de: Object.freeze({
    brief: 'kurzes ',
    held: 'anhaltendes ',
    labels: Object.freeze({ smile: 'Lächeln', frown: 'Mundwinkel runter', brow_raise: 'Brauen hoch', brow_furrow: 'Stirnrunzeln', eye_squint: 'Augen zusammengekniffen', eyes_wide: 'Augen weit', nose_wrinkle: 'Nasenrümpfen', lip_press: 'Lippen gepresst' }),
  }),
});
const ACTION_BRIEF_MS = 1000;
const ACTION_HELD_MS = 5000;

/** "0.9 s" — one decimal; anything that is not a finite non-negative number reads as 0.0 s. */
export function formatDuration(ms) {
  const n = Number.isFinite(ms) && ms > 0 ? ms : 0;
  return `${(n / 1000).toFixed(1)} s`;
}

/**
 * Turn an SSE `action` payload into `{ label, tone, duration }` — or null when there is nothing to say.
 * Unknown actions are hedged the same way (raw name, `_` → space) and never throw; unknown languages fall back to German.
 */
export function describeAction(action, lang = 'de') {
  const name = typeof action?.action === 'string' ? action.action : '';
  if (!name) return null;
  const words = ACTION_WORDS[lang] || ACTION_WORDS.de;
  const word = Object.hasOwn(words.labels, name) ? words.labels[name] : name.toLowerCase().replace(/_/g, ' ');
  const ms = Number.isFinite(action.duration_ms) ? action.duration_ms : 0;
  const qualifier = ms <= ACTION_BRIEF_MS ? words.brief : ms >= ACTION_HELD_MS ? words.held : '';
  const duration = formatDuration(ms);
  return { label: `${qualifier}${word} (${duration})`, tone: 'muted', duration };
}

/**
 * Append a valence sample `{ v, at }` from the browser's own frames, bounded to `max` (oldest dropped).
 * Mutates and returns `samples`; a non-number is ignored. This is a view of what the page itself sent —
 * it never re-derives the server's affect history.
 */
export function pushSample(samples, value, at, max = 120) {
  if (!Number.isFinite(value)) return samples;
  samples.push({ v: value, at });
  while (samples.length > max) samples.shift();
  return samples;
}

/** SVG polyline `points` for samples in a `w`×`h` box: -1..1 clamped, +1 at the top, newest at the right; '' when empty. */
export function sparklinePoints(samples, w, h) {
  const n = samples.length;
  if (!n) return '';
  const round = (x) => String(Math.round(x * 10) / 10);
  return samples.map((s, i) => {
    const x = n === 1 ? 0 : (i / (n - 1)) * w;
    const y = ((1 - Math.min(1, Math.max(-1, s.v))) / 2) * h;
    return `${round(x)},${round(y)}`;
  }).join(' ');
}
