import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  describeCameraError,
  describeEvent,
  offlineView,
  projectBox,
  shouldGreet,
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
