// The browser's SSE client (static/js/events.js) against a fake EventSource: what it subscribes to,
// which frames reach the handlers, and what it reports when the browser has no EventSource at all.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { subscribeEvents } from '../../src/face2ai_app/static/js/events.js';

class FakeEventSource {
  constructor(url) {
    this.url = url;
    this.listeners = new Map();
    this.closed = false;
    FakeEventSource.last = this;
  }

  addEventListener(kind, handler) {
    this.listeners.set(kind, handler);
  }

  close() {
    this.closed = true;
  }

  /** Deliver one server frame the way the platform does: a MessageEvent with a JSON string. */
  emit(kind, data) {
    this.listeners.get(kind)?.({ data });
  }
}

function withEventSource(impl, run) {
  const original = globalThis.EventSource;
  globalThis.EventSource = impl;
  try {
    return run();
  } finally {
    globalThis.EventSource = original;
  }
}

test('subscribeEvents listens same-origin as the browser role and hands mood/action payloads through', () => {
  withEventSource(FakeEventSource, () => {
    const moods = [];
    const actions = [];
    const close = subscribeEvents({ onMood: (m) => moods.push(m), onAction: (a) => actions.push(a) });
    const source = FakeEventSource.last;

    assert.equal(source.url, '/api/events?role=browser');
    assert.doesNotMatch(source.url, /role=agent/); // role=agent would hand the spoken greeting to a voice agent
    assert.deepEqual([...source.listeners.keys()], ['mood', 'action']); // presence/store/heartbeat stay ignored

    source.emit('mood', JSON.stringify({ at: '2026-08-18T12:00:00Z', to_mood: 'Happiness' }));
    source.emit('action', JSON.stringify({ at: '2026-08-18T12:00:03Z', action: 'smile', duration_ms: 900 }));
    assert.deepEqual(moods, [{ at: '2026-08-18T12:00:00Z', to_mood: 'Happiness' }]);
    assert.deepEqual(actions, [{ at: '2026-08-18T12:00:03Z', action: 'smile', duration_ms: 900 }]);

    source.emit('mood', '{not json');  // dropped, never thrown
    source.emit('action', 'null');     // parses to null: nothing to say
    assert.equal(moods.length, 1);
    assert.equal(actions.length, 1);

    assert.equal(source.closed, false);
    close();
    assert.equal(source.closed, true);
  });
});

test('subscribeEvents reports a missing EventSource as unsupported, not as a reconnect', () => {
  withEventSource(undefined, () => {
    const errors = [];
    const close = subscribeEvents({ onError: (info) => errors.push(info) });
    assert.deepEqual(errors, [{ unsupported: true }]); // nothing will ever reconnect: the shell must not promise it
    assert.equal(typeof close, 'function');
    close(); // a no-op disposer, never a throw
  });
});

test('a stream error is reported as reconnectable', () => {
  withEventSource(FakeEventSource, () => {
    const errors = [];
    subscribeEvents({ onError: (info) => errors.push(info) });
    FakeEventSource.last.onerror({});
    assert.deepEqual(errors, [{ unsupported: false }]);
  });
});
