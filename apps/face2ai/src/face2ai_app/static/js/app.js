// Face2AI browser shell. Consumes RecognitionEvent/SystemStatus from the local API and renders
// them; it never invents identity, certainty, or activity. Product loop kept intact:
// UNKNOWN -> explicit LEARN (with consent) -> leave -> return -> KNOWN -> greeting.
import * as api from './api.js';
import { CameraController } from './camera.js';
import { decryptText, installAtmosphere, installMagnets, installSpotlights } from './effects.js';
import { describeCameraError, describeEvent, offlineView, shouldGreet, transitionKey } from './model.js';

const RECOGNIZE_INTERVAL_MS = 450;
const RECOGNIZE_ERROR_BACKOFF_MS = 1500;
const STATUS_INTERVAL_MS = 5000;
const MAX_EVENTS = 8;
const TIME_FORMAT = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

const els = Object.fromEntries([...document.querySelectorAll('[id]')].map((el) => [el.id, el]));
const camera = new CameraController(els.camera, els.overlay);

const state = {
  cameraOn: false,
  starting: false,
  paused: false,
  session: 0,          // incremented on every camera start/stop; in-flight results from older sessions are dropped
  inflight: false,
  timer: null,
  frame: 0,
  lastBlob: null,
  lastEvent: null,
  lastTransition: null,
  engine: { known: false, available: false },
  cooldownMs: 0,
  greeting: { lastIdentityId: null, lastAt: 0 },
  events: 0,
  lastErrorText: null,
  enrolling: false,     // true while the enroll dialog is open or the enroll request is in flight
  enrollBlob: null,     // frame + event frozen when the dialog opened
  enrollEvent: null,
};

const IDLE_VIEW = describeEvent({ state: 'NO_FACE' });

// ---------- small UI helpers ----------

function nowTime() {
  return TIME_FORMAT.format(new Date());
}

/** Visible pill text is animated; assistive tech gets the final text once via the sr-only announcer. */
function setPill(pill, textEl, text, mode = '') {
  pill.classList.remove('online', 'warn', 'error');
  if (mode) pill.classList.add(mode);
  decryptText(textEl, text, { duration: 320 });
  els.statusAnnouncer.textContent = text;
}

let toastTimer = null;
function toast(message) {
  els.toast.textContent = message;
  els.toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => els.toast.classList.remove('show'), 2800);
}

function addEvent(title, detail = '') {
  els.emptyEvent?.remove();
  const item = document.createElement('article');
  item.className = 'event';
  const time = document.createElement('div');
  time.className = 'event-time';
  time.textContent = nowTime();
  const heading = document.createElement('div');
  heading.className = 'event-title';
  heading.textContent = title;
  const body = document.createElement('div');
  body.className = 'event-detail';
  body.textContent = detail;
  item.append(time, heading, body);
  els.eventList.prepend(item);
  state.events += 1;
  els.eventCount.textContent = `${state.events} EVENT${state.events === 1 ? '' : 'S'}`;
  while (els.eventList.children.length > MAX_EVENTS) els.eventList.lastElementChild.remove();
}

function setRecognitionValue(text, muted) {
  els.recognitionValue.textContent = text;
  els.recognitionValue.classList.toggle('muted', muted);
}

/** Loop-level indicator: scan line + chip + context badge reflect whether recognition is running. */
function setLoopIndicator() {
  const live = state.cameraOn && !state.paused && state.engine.available && !state.enrolling;
  els.stage.classList.toggle('live', live);
  els.processingChip.textContent = !state.cameraOn ? 'IDLE' : state.paused ? 'PAUSED' : state.enrolling ? 'LEARNING' : live ? 'SCANNING' : 'ENGINE OFFLINE';
  els.contextHint.textContent = !state.cameraOn ? 'OFFLINE' : state.paused ? 'PAUSED' : live ? 'LIVE' : 'DEGRADED';
}

// ---------- identity card ----------

function renderIdentity(view) {
  decryptText(els.identityName, view.name, { duration: 520 });
  els.identityAnnouncer.textContent = `${view.name}. ${view.sub}.`;
  els.identityState.className = `identity-state ${view.cls}`.trim();
  decryptText(els.identityStateText, view.sub, { duration: 360 });
  els.identityMini.textContent = view.label;
  els.distanceValue.textContent = view.distance === null ? '—' : view.distance.toFixed(3);
  els.distanceValue.classList.toggle('muted', view.distance === null);
  els.facesValue.textContent = String(view.faces);
  els.faceCountChip.textContent = `${view.faces} FACE${view.faces === 1 ? '' : 'S'}`;
  els.learnButton.disabled = !(view.canEnroll && state.cameraOn && !state.paused && !state.enrolling);
}

// ---------- engine / status ----------

function applyEngine(available, reason) {
  const changed = !state.engine.known || state.engine.available !== available;
  state.engine = { known: true, available };
  if (available) {
    setPill(els.enginePill, els.engineStatus, 'ENGINE READY', 'online');
    els.engineContext.textContent = 'Ready';
    if (!state.cameraOn) setRecognitionValue('Ready', false);
  } else {
    setPill(els.enginePill, els.engineStatus, 'ENGINE OFFLINE', 'warn');
    els.engineContext.textContent = reason ? `Offline · ${reason}` : 'Offline';
    setRecognitionValue('Offline', true);
    camera.clearOverlay();
    state.lastEvent = null;
    if (state.cameraOn) renderIdentity(offlineView(reason || 'engine unavailable'));
    els.learnButton.disabled = true;
  }
  setLoopIndicator();
  if (changed) {
    addEvent(available ? 'Engine ready' : 'Engine offline', available ? 'Face recognition engine is loaded.' : (reason || 'Face recognition engine is not available on this runtime.'));
    if (!available) toast('Face recognition engine is not ready on this runtime.');
    if (available && state.cameraOn && !state.paused) {
      renderIdentity(IDLE_VIEW);
      schedule(0);
    }
  }
}

async function refreshStatus() {
  try {
    const status = await api.getStatus();
    state.cooldownMs = Math.max(0, Number(status.greeting_cooldown_seconds) || 0) * 1000;
    els.cooldownContext.textContent = `${Math.round(state.cooldownMs / 1000)} s`;
    els.identityCount.textContent = String(status.identity_count ?? '—');
    applyEngine(status.engine_available === true, status.engine_reason);
  } catch (error) {
    setPill(els.enginePill, els.engineStatus, 'API OFFLINE', 'error');
    els.engineContext.textContent = `API unreachable · ${error.message}`;
    setRecognitionValue('Offline', true);
    els.learnButton.disabled = true;
    if (state.engine.known && state.engine.available) addEvent('API unreachable', error.message);
    state.engine = { known: true, available: false };
    setLoopIndicator();
  }
}

// ---------- recognition loop ----------

function loopAllowed() {
  return state.cameraOn && !state.paused && state.engine.available && !state.enrolling && !document.hidden;
}

function schedule(delay = RECOGNIZE_INTERVAL_MS) {
  clearTimeout(state.timer);
  if (!loopAllowed()) return;
  state.timer = setTimeout(tick, delay);
}

async function tick() {
  if (state.inflight) { schedule(); return; }
  if (!loopAllowed()) return;
  const session = state.session;
  state.inflight = true;
  let delay = RECOGNIZE_INTERVAL_MS;
  try {
    const blob = await camera.snapshot();
    if (!blob || session !== state.session) return;
    state.lastBlob = blob;
    state.frame += 1;
    els.frameInfo.textContent = `FRAME ${String(state.frame).padStart(4, '0')}`;
    const event = await api.recognize(blob);
    if (session !== state.session || state.paused || state.enrolling) return; // stale result: drop it
    handleRecognition(event);
  } catch (error) {
    if (session !== state.session || state.paused) return;
    delay = RECOGNIZE_ERROR_BACKOFF_MS;
    handleRecognitionError(error);
  } finally {
    state.inflight = false;
    if (session === state.session) schedule(delay);
  }
}

function handleRecognition(event) {
  state.lastEvent = event;
  state.lastErrorText = null;
  const view = describeEvent(event);
  camera.drawFaces(Array.isArray(event.faces) ? event.faces : []);
  renderIdentity(view);
  setRecognitionValue('Live', false);

  const key = transitionKey(event);
  if (key !== state.lastTransition) {
    state.lastTransition = key;
    addEvent(view.label, view.message);
  }
  if (view.state === 'KNOWN' && view.primary?.identity_id) greet(view.primary);
}

function handleRecognitionError(error) {
  camera.clearOverlay();
  state.lastEvent = null;
  if (error.status === 503) {
    // Engine unavailable: the server said so explicitly; applyEngine renders the offline view.
    applyEngine(false, error.message);
    return;
  }
  renderIdentity(describeEvent({ state: 'ERROR', message: error.message }));
  setRecognitionValue('Error', true);
  if (state.lastErrorText !== error.message) {
    state.lastErrorText = error.message;
    addEvent('Recognition error', error.message);
  }
}

function greet(face) {
  const now = Date.now();
  if (!shouldGreet(state.greeting, face.identity_id, now, state.cooldownMs)) return;
  state.greeting = { lastIdentityId: face.identity_id, lastAt: now };
  const name = face.display_name || 'there';
  if ('speechSynthesis' in window) {
    speechSynthesis.cancel();
    speechSynthesis.speak(new SpeechSynthesisUtterance(`Hi ${name}.`));
    addEvent('Greeting spoken', `Hi ${name}.`);
  } else {
    addEvent('Greeting', `Hi ${name}. (Speech synthesis unavailable in this browser.)`);
  }
}

// ---------- camera control ----------

function setCameraButtons(busy) {
  els.activateButton.disabled = busy;
  els.visionToggle.disabled = busy;
}

async function startCamera() {
  if (state.cameraOn || state.starting) return;
  if (!navigator.mediaDevices?.getUserMedia) {
    toast('Camera access is not supported in this browser.');
    return;
  }
  state.starting = true;
  setCameraButtons(true);
  try {
    await camera.start();
  } catch (error) {
    const wording = describeCameraError(error);
    setPill(els.cameraPill, els.cameraStatus, wording.pill, 'warn');
    els.cameraContext.textContent = wording.context;
    addEvent('Camera unavailable', `${error.name || 'Error'}: ${error.message}`);
    toast(`Camera unavailable: ${error.message}`);
    return;
  } finally {
    state.starting = false;
    setCameraButtons(false);
  }
  state.session += 1;
  state.cameraOn = true;
  state.paused = false;
  state.frame = 0;
  state.lastTransition = null;
  state.lastEvent = null;
  els.stage.classList.add('camera-on');
  els.centerState.inert = true;
  els.visionToggle.title = 'Stop vision';
  els.visionToggle.setAttribute('aria-label', 'Stop vision');
  setPill(els.cameraPill, els.cameraStatus, 'VISION ONLINE', 'online');
  els.cameraContext.textContent = 'Live';
  els.sessionContext.textContent = nowTime();
  els.pauseButton.disabled = false;
  els.pauseLabel.textContent = 'Pause vision';
  addEvent('Vision activated', 'Local camera stream started. Frames stay on this device.');
  if (state.engine.available) {
    renderIdentity(IDLE_VIEW);
    setRecognitionValue('Live', false);
    schedule(150);
  } else {
    renderIdentity(offlineView('engine unavailable'));
    setRecognitionValue('Offline', true);
  }
  setLoopIndicator();
}

function stopCamera() {
  if (!state.cameraOn) return;
  state.session += 1;
  clearTimeout(state.timer);
  camera.stop();
  state.cameraOn = false;
  state.paused = false;
  state.lastBlob = null;
  state.lastEvent = null;
  els.stage.classList.remove('camera-on');
  els.centerState.inert = false;
  els.visionToggle.title = 'Activate vision';
  els.visionToggle.setAttribute('aria-label', 'Activate vision');
  setPill(els.cameraPill, els.cameraStatus, 'VISION OFFLINE', '');
  els.cameraContext.textContent = 'Inactive';
  els.sessionContext.textContent = 'Not started';
  els.pauseButton.disabled = true;
  els.frameInfo.textContent = 'FRAME —';
  setRecognitionValue(state.engine.available ? 'Ready' : 'Offline', !state.engine.available);
  addEvent('Vision stopped', 'Camera stream closed. No frames are being processed.');
  renderIdentity(offlineView());
  setLoopIndicator();
}

function togglePause() {
  if (!state.cameraOn) return;
  state.paused = !state.paused;
  if (state.paused) {
    clearTimeout(state.timer);
    camera.clearOverlay();
    state.lastEvent = null;
    els.pauseLabel.textContent = 'Resume vision';
    setRecognitionValue('Paused', true);
    els.learnButton.disabled = true;
    addEvent('Recognition paused', 'Camera preview stays local and visible; recognition requests are stopped.');
  } else {
    els.pauseLabel.textContent = 'Pause vision';
    setRecognitionValue(state.engine.available ? 'Live' : 'Offline', !state.engine.available);
    addEvent('Recognition resumed', 'Identity processing resumed.');
    schedule(0);
  }
  setLoopIndicator();
}

// ---------- enrollment ----------

function openEnrollDialog() {
  if (!state.lastEvent || !state.lastBlob) return;
  // Freeze the frame and event the user is enrolling; the loop pauses while the dialog is open.
  state.enrollBlob = state.lastBlob;
  state.enrollEvent = state.lastEvent;
  state.enrolling = true;
  clearTimeout(state.timer);
  els.enrollError.hidden = true;
  els.enrollError.textContent = '';
  setLoopIndicator();
  els.enrollDialog.showModal();
  setTimeout(() => els.displayName.focus(), 40);
}

function showEnrollError(message) {
  els.enrollError.textContent = message;
  els.enrollError.hidden = false;
}

async function submitEnrollment(event) {
  event.preventDefault();
  const name = els.displayName.value.trim();
  const consent = els.consent.checked;
  const frozen = describeEvent(state.enrollEvent || {});
  if (!name) { showEnrollError('Enter a display name.'); els.displayName.focus(); return; }
  if (!consent) { showEnrollError('Explicit consent is required before a face encoding is stored.'); els.consent.focus(); return; }
  if (!state.enrollBlob || frozen.state !== 'UNKNOWN' || !frozen.canEnroll) {
    showEnrollError('Enrollment needs exactly one unknown face. Close this dialog and try again.');
    return;
  }

  els.enrollSubmit.disabled = true;
  renderIdentity(describeEvent({ ...state.enrollEvent, state: 'LEARNING', can_enroll: false }));
  try {
    const record = await api.enroll(state.enrollBlob, name, consent);
    els.enrollDialog.close('learned');
    els.displayName.value = '';
    els.consent.checked = false;
    addEvent('Identity learned', `${record.display_name} stored locally. Step out of frame and return to verify recognition.`);
    toast(`${record.display_name} stored locally.`);
    state.lastTransition = null;
    els.identityCard.focus();
    await refreshStatus();
  } catch (error) {
    showEnrollError(error.message);
    addEvent('Enrollment rejected', error.message);
    renderIdentity(frozen);
  } finally {
    els.enrollSubmit.disabled = false;
  }
}

function onEnrollDialogClosed() {
  state.enrolling = false;
  state.enrollBlob = null;
  state.enrollEvent = null;
  setLoopIndicator();
  schedule(0);
}

// ---------- identity store ----------

function identityRow(item) {
  const row = document.createElement('div');
  row.className = 'identity-item';
  const text = document.createElement('div');
  const strong = document.createElement('strong');
  strong.textContent = item.display_name;
  const small = document.createElement('small');
  const created = item.created_at ? new Date(item.created_at).toLocaleString() : 'unknown time';
  small.textContent = `${item.encoding_count} encoding${item.encoding_count === 1 ? '' : 's'} · ${created}`;
  text.append(strong, small);
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'ghost-btn';
  remove.textContent = 'Delete';
  remove.setAttribute('aria-label', `Delete ${item.display_name}`);
  remove.addEventListener('click', async () => {
    remove.disabled = true;
    const index = [...els.identityList.children].indexOf(row);
    try {
      await api.deleteIdentity(item.id);
      addEvent('Identity deleted', `${item.display_name} removed from the local store.`);
      toast(`${item.display_name} deleted.`);
      state.lastTransition = null;
    } catch (error) {
      remove.disabled = false;
      toast(`Delete failed: ${error.message}`);
      if (error.status !== 404) return;
    }
    await Promise.all([renderIdentities(), refreshStatus()]);
    focusInDrawer(index);
  });
  row.append(text, remove);
  return row;
}

/** Keep keyboard focus inside the drawer after the list re-renders: same row index, else the close button. */
function focusInDrawer(index = 0) {
  const buttons = els.identityList.querySelectorAll('button');
  const target = buttons[Math.min(index, buttons.length - 1)] || els.identityDialog.querySelector('form button');
  target?.focus();
}

async function renderIdentities() {
  const root = els.identityList;
  try {
    const list = await api.listIdentities();
    root.replaceChildren();
    if (!list.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-list';
      empty.textContent = 'No identities are enrolled on this device.';
      root.append(empty);
      return;
    }
    root.append(...list.map(identityRow));
  } catch (error) {
    root.replaceChildren();
    const failed = document.createElement('div');
    failed.className = 'empty-list';
    failed.textContent = `Identity store unavailable: ${error.message}`;
    root.append(failed);
  }
}

async function openIdentities() {
  els.identityDialog.showModal();
  await renderIdentities();
}

async function submitErase(event) {
  event.preventDefault();
  els.eraseSubmit.disabled = true;
  try {
    const result = await api.eraseAll();
    els.eraseDialog.close('erased');
    addEvent('Identity store erased', `${result.deleted} identit${result.deleted === 1 ? 'y' : 'ies'} removed from this device.`);
    toast('Local identity store erased.');
    state.lastTransition = null;
    state.greeting = { lastIdentityId: null, lastAt: 0 };
    if (els.identityDialog.open) {
      await renderIdentities();
      focusInDrawer(0);
    }
    await refreshStatus();
  } catch (error) {
    els.eraseDialog.close();
    toast(`Erase failed: ${error.message}`);
  } finally {
    els.eraseSubmit.disabled = false;
  }
}

// ---------- wiring ----------

els.activateButton.addEventListener('click', startCamera);
els.visionToggle.addEventListener('click', () => (state.cameraOn ? stopCamera() : startCamera()));
els.pauseButton.addEventListener('click', togglePause);
els.learnButton.addEventListener('click', openEnrollDialog);
els.enrollForm.addEventListener('submit', submitEnrollment);
els.enrollCancel.addEventListener('click', () => els.enrollDialog.close('cancel'));
els.enrollDialog.addEventListener('close', onEnrollDialogClosed);
els.identitiesButton.addEventListener('click', openIdentities);
els.openIdentitiesButton.addEventListener('click', openIdentities);
els.eraseButton.addEventListener('click', () => els.eraseDialog.showModal());
els.drawerEraseButton.addEventListener('click', () => els.eraseDialog.showModal());
els.eraseForm.addEventListener('submit', submitErase);
els.eraseCancel.addEventListener('click', () => els.eraseDialog.close('cancel'));

// Visibility hygiene: no recognition work while the tab is hidden; camera stays user-controlled.
document.addEventListener('visibilitychange', () => {
  if (document.hidden) clearTimeout(state.timer);
  else schedule(0);
});
window.addEventListener('resize', () => {
  if (state.lastEvent && loopAllowed()) camera.drawFaces(state.lastEvent.faces || []);
});

function tickClock() { els.clock.textContent = nowTime(); }
tickClock();
setInterval(tickClock, 1000);

installSpotlights();
installMagnets();
installAtmosphere(els.stage);
renderIdentity(offlineView());
setLoopIndicator();
await refreshStatus();
setInterval(refreshStatus, STATUS_INTERVAL_MS);
