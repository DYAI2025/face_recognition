import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  axisPercent,
  describeAction,
  describeCameraError,
  describeEvent,
  describeExpression,
  formatAxis,
  formatDuration,
  offlineView,
  projectBox,
  pushSample,
  shouldGreet,
  sparklinePoints,
  transitionKey,
} from '../../src/face2ai_app/static/js/model.js';

const box = { top: 100, right: 400, bottom: 300, left: 200 };

test('projectBox maps a box from the sent frame into a cover-fitted view of the same aspect', () => {
  // Frame that was actually sent to the API (downscaled snapshot), view twice as large.
  const projected = projectBox(box, { width: 640, height: 360 }, { width: 1280, height: 720 });
  assert.deepEqual(projected, { x: 400, y: 200, width: 400, height: 400 });
});

test('projectBox uses the snapshot dimensions, not the camera resolution', () => {
  // Regression: boxes are returned in the coordinate space of the JPEG the client sent
  // (640 wide), never in the camera's native 1280 space.
  const fromFrame = projectBox(box, { width: 640, height: 360 }, { width: 640, height: 360 });
  const fromCamera = projectBox(box, { width: 1280, height: 720 }, { width: 640, height: 360 });
  assert.deepEqual(fromFrame, { x: 200, y: 100, width: 200, height: 200 });
  assert.notDeepEqual(fromFrame, fromCamera);
});

test('projectBox centres the overflow axis like object-fit: cover', () => {
  // 16:9 frame shown in a square view: scale by height, crop width, offset x by -(1280-720)/2.
  const projected = projectBox(box, { width: 640, height: 360 }, { width: 720, height: 720 });
  assert.equal(projected.height, 400);
  assert.equal(projected.width, 400);
  assert.equal(projected.y, 200);
  assert.equal(projected.x, 200 * 2 - 280);
});

test('describeEvent follows the server event instead of re-deriving state', () => {
  const known = describeEvent({
    state: 'KNOWN',
    can_enroll: false,
    message: null,
    faces: [{ box, matched: true, identity_id: 'id-1', display_name: 'Ada', match_distance: 0.31 }],
  });
  assert.equal(known.state, 'KNOWN');
  assert.equal(known.name, 'Ada');
  assert.equal(known.cls, 'known');
  assert.equal(known.canEnroll, false);
  assert.equal(known.faces, 1);
  assert.equal(known.distance, 0.31);
  assert.equal(known.primary.identity_id, 'id-1');
});

test('describeEvent surfaces can_enroll and server message verbatim', () => {
  const multiple = describeEvent({
    state: 'MULTIPLE_FACES',
    can_enroll: false,
    message: 'Enrollment requires exactly one visible face.',
    faces: [{ box, matched: false }, { box, matched: false }],
  });
  assert.equal(multiple.canEnroll, false);
  assert.equal(multiple.message, 'Enrollment requires exactly one visible face.');
  assert.equal(multiple.faces, 2);

  const unknown = describeEvent({ state: 'UNKNOWN', can_enroll: true, faces: [{ box, matched: false }] });
  assert.equal(unknown.canEnroll, true);
  assert.equal(unknown.cls, 'unknown');
  assert.equal(unknown.distance, null);
  assert.ok(unknown.message.length > 0);
});

test('describeEvent tolerates missing fields and unknown states without inventing data', () => {
  const empty = describeEvent({ state: 'NO_FACE' });
  assert.equal(empty.faces, 0);
  assert.equal(empty.canEnroll, false);
  assert.equal(empty.primary, null);
  const weird = describeEvent({ state: 'SOMETHING_NEW', faces: [] });
  assert.equal(weird.state, 'SOMETHING_NEW');
  assert.equal(weird.cls, 'error');
});

test('transitionKey changes only when state or identity changes', () => {
  const a = transitionKey({ state: 'KNOWN', faces: [{ identity_id: 'id-1' }] });
  const b = transitionKey({ state: 'KNOWN', faces: [{ identity_id: 'id-1', match_distance: 0.4 }] });
  const c = transitionKey({ state: 'KNOWN', faces: [{ identity_id: 'id-2' }] });
  const d = transitionKey({ state: 'UNKNOWN', faces: [{}] });
  assert.equal(a, b);
  assert.notEqual(a, c);
  assert.notEqual(a, d);
});

test('shouldGreet greets a new identity immediately and the same identity only after cooldown', () => {
  const cooldown = 15_000;
  assert.equal(shouldGreet({ lastIdentityId: null, lastAt: 0 }, 'id-1', 1_000, cooldown), true);
  assert.equal(shouldGreet({ lastIdentityId: 'id-1', lastAt: 1_000 }, 'id-1', 5_000, cooldown), false);
  assert.equal(shouldGreet({ lastIdentityId: 'id-1', lastAt: 1_000 }, 'id-1', 16_001, cooldown), true);
  assert.equal(shouldGreet({ lastIdentityId: 'id-1', lastAt: 1_000 }, 'id-2', 1_100, cooldown), true);
  assert.equal(shouldGreet({ lastIdentityId: 'id-1', lastAt: 1_000 }, null, 99_000, cooldown), false);
});

test('describeEvent pins fallback messages and names known people in the KNOWN message', () => {
  const known = describeEvent({ state: 'KNOWN', faces: [{ box, matched: true, identity_id: 'id-1', display_name: 'Ada' }] });
  assert.equal(known.message, 'Identity matched: Ada.');
  assert.equal(known.label, 'KNOWN');
  const unknown = describeEvent({ state: 'UNKNOWN', can_enroll: true, faces: [{ box, matched: false }] });
  assert.equal(unknown.message, 'One unknown face detected. Enrollment is available.');
  assert.equal(describeEvent().state, 'ERROR');
  assert.equal(describeEvent({ state: 42 }).state, 'ERROR');
  assert.equal(describeEvent({ state: 'MULTIPLE_FACES' }).label, 'MULTIPLE FACES');
});

test('shouldGreet cooldown boundary is inclusive', () => {
  assert.equal(shouldGreet({ lastIdentityId: 'id-1', lastAt: 1_000 }, 'id-1', 16_000, 15_000), true);
  assert.equal(shouldGreet({ lastIdentityId: 'id-1', lastAt: 1_000 }, 'id-1', 15_999, 15_000), false);
});

test('offlineView distinguishes camera-off from engine-unavailable and never claims a face', () => {
  const off = offlineView();
  assert.equal(off.state, 'OFFLINE');
  assert.equal(off.cls, '');
  assert.equal(off.faces, 0);
  assert.equal(off.canEnroll, false);
  const engineDown = offlineView('ModuleNotFoundError: dlib');
  assert.equal(engineDown.cls, 'error');
  assert.match(engineDown.sub, /ModuleNotFoundError: dlib/);
});

test('describeCameraError only calls permission problems "blocked"', () => {
  assert.equal(describeCameraError({ name: 'NotAllowedError' }).pill, 'CAMERA BLOCKED');
  assert.equal(describeCameraError({ name: 'NotReadableError' }).pill, 'CAMERA UNAVAILABLE');
  assert.match(describeCameraError({ name: 'NotFoundError' }).context, /NotFoundError/);
  assert.equal(describeCameraError(undefined).pill, 'CAMERA UNAVAILABLE');
});

// ---------- expression (Stage 1): a hint, never a fact ----------

test('describeExpression speaks in hedged German and never claims certainty', () => {
  const d = describeExpression({ dominant: 'Happiness', scores: { Happiness: 0.9 }, valence: 0.6, arousal: 0.1 }, 'de');
  assert.equal(d.label, 'wirkt fröhlich');
  assert.equal(d.tone, 'ok');
  assert.equal(describeExpression(null, 'de'), null);
  assert.equal(describeExpression({ dominant: 'Neutral', scores: {} }, 'en').label, 'looks neutral');
});

test('describeExpression maps every emotion label to hedged wording in both languages', () => {
  const de = { Happiness: 'wirkt fröhlich', Sadness: 'wirkt traurig', Anger: 'wirkt verärgert', Fear: 'wirkt ängstlich', Surprise: 'wirkt überrascht', Disgust: 'wirkt angewidert', Contempt: 'wirkt abschätzig', Neutral: 'wirkt neutral' };
  const en = { Happiness: 'looks happy', Sadness: 'looks sad', Anger: 'looks angry', Fear: 'looks fearful', Surprise: 'looks surprised', Disgust: 'looks disgusted', Contempt: 'looks contemptuous', Neutral: 'looks neutral' };
  for (const [dominant, label] of Object.entries(de)) assert.equal(describeExpression({ dominant }, 'de').label, label);
  for (const [dominant, label] of Object.entries(en)) assert.equal(describeExpression({ dominant }, 'en').label, label);
  // Every label is hedged; none reads as a finding.
  for (const lang of ['de', 'en']) {
    for (const dominant of Object.keys(de)) {
      const { label } = describeExpression({ dominant }, lang);
      assert.match(label, /^(wirkt|looks) /);
      assert.doesNotMatch(label, /\b(ist|is|erkannt|detected|recognized)\b/);
    }
  }
});

test('describeExpression tone: happiness ok, neutral/surprise muted, the rest warn', () => {
  assert.equal(describeExpression({ dominant: 'Happiness' }).tone, 'ok');
  assert.equal(describeExpression({ dominant: 'Neutral' }).tone, 'muted');
  assert.equal(describeExpression({ dominant: 'Surprise' }).tone, 'muted');
  for (const dominant of ['Sadness', 'Anger', 'Fear', 'Disgust', 'Contempt']) assert.equal(describeExpression({ dominant }).tone, 'warn');
});

test('describeExpression tolerates unknown labels, unknown languages and missing numbers without throwing', () => {
  const odd = describeExpression({ dominant: 'Boredom' }, 'de');
  assert.equal(odd.label, 'wirkt boredom');
  assert.equal(odd.tone, 'muted');
  assert.equal(describeExpression({ dominant: 'Happiness' }, 'fr').label, 'wirkt fröhlich'); // falls back to German
  assert.equal(describeExpression({ dominant: 'Happiness' }).label, 'wirkt fröhlich'); // default language
  assert.equal(describeExpression({}), null);
  assert.equal(describeExpression({ dominant: '' }), null);
  assert.equal(describeExpression({ dominant: 42 }), null);
  const bare = describeExpression({ dominant: 'Neutral' });
  assert.equal(bare.valence, null);
  assert.equal(bare.arousal, null);
  const full = describeExpression({ dominant: 'Neutral', valence: -0.25, arousal: 'x' });
  assert.equal(full.valence, -0.25);
  assert.equal(full.arousal, null);
});

test('formatAxis prints a signed two-decimal label and never a negative zero', () => {
  assert.equal(formatAxis(-0.004), '+0.00');
  assert.equal(formatAxis(0.6), '+0.60');
  assert.equal(formatAxis(-0.5), '-0.50');
  assert.equal(formatAxis(0), '+0.00');
  assert.equal(formatAxis(null), null);
  assert.equal(formatAxis(NaN), null);
});

test('axisPercent maps -1..1 onto 0..100 and clamps', () => {
  assert.equal(axisPercent(-1), 0);
  assert.equal(axisPercent(0), 50);
  assert.equal(axisPercent(1), 100);
  assert.equal(axisPercent(0.6), 80);
  assert.equal(axisPercent(2), 100);
  assert.equal(axisPercent(-3), 0);
  assert.equal(axisPercent(null), null);
  assert.equal(axisPercent(undefined), null);
  assert.equal(axisPercent(NaN), null);
});

// ---------- expression dynamics (Stage 2): action entries come from the server's SSE `action` events ----------

test('describeAction is hedged, quantised and bilingual', () => {
  const brief = describeAction({ action: 'smile', duration_ms: 900, peak: 0.9 }, 'en');
  assert.equal(brief.label, 'brief smile (0.9 s)');
  assert.equal(brief.tone, 'muted');
  assert.equal(brief.duration, '0.9 s');
  assert.equal(describeAction({ action: 'brow_raise', duration_ms: 2300 }, 'en').label, 'brow raise (2.3 s)');
  assert.equal(describeAction({ action: 'smile', duration_ms: 6000 }, 'en').label, 'held smile (6.0 s)');
  assert.equal(describeAction({ action: 'smile', duration_ms: 900 }, 'de').label, 'kurzes Lächeln (0.9 s)');
  assert.equal(describeAction({ action: 'smile', duration_ms: 6000 }, 'de').label, 'anhaltendes Lächeln (6.0 s)');
  assert.equal(describeAction({ action: 'wink', duration_ms: 900 }, 'en').label, 'brief wink (0.9 s)'); // unknown label never throws
  assert.equal(describeAction({ action: 'lip_press', duration_ms: 1200 }, 'fr').label, 'Lippen gepresst (1.2 s)'); // unknown language falls back to German
  assert.equal(describeAction(null, 'en'), null);
  assert.equal(describeAction({}, 'en'), null);
  assert.equal(describeAction({ action: 42 }, 'en'), null);
});

test('describeAction never reads as a finding: every action label in both languages is free of "is"/"detected"', () => {
  for (const lang of ['de', 'en']) {
    for (const action of ['smile', 'frown', 'brow_raise', 'brow_furrow', 'eye_squint', 'eyes_wide', 'nose_wrinkle', 'lip_press']) {
      for (const duration_ms of [400, 2000, 7000]) {
        const { label } = describeAction({ action, duration_ms }, lang);
        assert.doesNotMatch(label, /\b(is|ist|erkannt|detected|recognized|smiling|frowning)\b/, `${lang} ${action}: ${label}`);
        assert.match(label, /\(\d+\.\d s\)$/, label);
      }
    }
  }
});

test('formatDuration prints one decimal in seconds and tolerates junk', () => {
  assert.equal(formatDuration(900), '0.9 s');
  assert.equal(formatDuration(6000), '6.0 s');
  assert.equal(formatDuration(0), '0.0 s');
  assert.equal(formatDuration(1250), '1.3 s');
  assert.equal(formatDuration(-5), '0.0 s');
  assert.equal(formatDuration(null), '0.0 s');
  assert.equal(formatDuration('x'), '0.0 s');
});

test('sparkline maps -1..1 samples into the box, newest right', () => {
  const s = pushSample([], 0, 1); pushSample(s, 1, 2); pushSample(s, -1, 3);
  assert.equal(sparklinePoints(s, 120, 24), '0,12 60,0 120,24');
  assert.equal(sparklinePoints([], 120, 24), '');
  assert.equal(sparklinePoints([{ v: 0.5, at: 1 }], 120, 24), '0,6'); // a single sample sits at the left edge, never NaN
  assert.equal(sparklinePoints([{ v: 3, at: 1 }, { v: -3, at: 2 }], 120, 24), '0,0 120,24'); // clamped
  assert.equal(pushSample(Array.from({ length: 120 }, (_, i) => ({ v: 0, at: i })), 0.5, 999, 120).length, 120); // bounded
  const bounded = pushSample(Array.from({ length: 3 }, (_, i) => ({ v: 0, at: i })), 0.5, 99, 3);
  assert.deepEqual(bounded, [{ v: 0, at: 1 }, { v: 0, at: 2 }, { v: 0.5, at: 99 }]); // drops the oldest, keeps the newest
  assert.equal(pushSample([], NaN, 1).length, 0); // a non-number is not a sample
});
