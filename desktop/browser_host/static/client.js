'use strict';

const byId = id => document.getElementById(id);
const workspace = byId('workspace');
const screen = byId('screen');
const keyboard = byId('keyboard');
const canvas = screen.getContext('2d', {alpha: false});
const storageKey = 'areion.browser.token';
let token = location.hash.slice(1);
try {
  if (token) sessionStorage.setItem(storageKey, token);
  else token = sessionStorage.getItem(storageKey) || '';
} catch { /* The fragment still works in a storage-restricted browser. */ }
if (location.hash && token) history.replaceState(null, '', location.pathname + location.search);

let lease = null;
let opening = null;
let actualSize = false;
let panning = false;
let closing = Promise.resolve();
let logical = {width: 1380, height: 930};
let activePointer = null;
let previousPress = null;
let noticeTimer;
let focusTimer;
let desiredSize = '';
let awaitingFocus = false;

function status(heading, detail, retry = true) {
  byId('status-heading').textContent = heading;
  byId('status-detail').textContent = detail;
  byId('resume').hidden = !retry;
  byId('status-panel').hidden = false;
}

function notify(message) {
  byId('notice').textContent = message;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { byId('notice').textContent = ''; }, 4200);
}

function headers(client) {
  const h = {'X-Areion-Token': token};
  if (client) h['X-Areion-Client'] = client;
  return h;
}

async function api(path, {client, body, keepalive = false, signal} = {}) {
  const h = headers(client);
  const options = {headers: h, cache: 'no-store', credentials: 'omit', redirect: 'error', keepalive, signal};
  if (body !== undefined) {
    h['Content-Type'] = 'application/json';
    options.method = 'POST';
    options.body = JSON.stringify(body);
  }
  const response = await fetch('/api/' + path, options);
  if (!response.ok) {
    const error = new Error('Console request failed');
    error.status = response.status;
    throw error;
  }
  return response;
}

function closeClient(client) {
  return api('close', {client, body: {}, keepalive: true, signal: AbortSignal.timeout(1200)}).catch(() => {});
}

function relinquish() {
  clearTimeout(focusTimer);
  if (opening) opening.cancelled = true;
  const old = lease;
  lease = null;
  desiredSize = '';
  activePointer = null;
  previousPress = null;
  if (!old) return;
  clearInterval(old.pinger);
  old.queue.length = 0;
  old.abort.abort();
  closing = closeClient(old.id);
}

function lost(session) {
  if (lease !== session) return;
  relinquish();
  status('Console disconnected', 'Reconnect to the local Areion host.');
}

function pause() {
  if (!lease && !opening) return;
  relinquish();
  awaitingFocus = true;
  status('Console paused', 'Return to this tab to resume.');
}

async function openConsole() {
  if (!token) {
    status('Open the local console', 'Start the Areion browser host and open the address printed by the launcher.', false);
    return;
  }
  if (lease || opening || document.hidden) return;
  const attempt = {cancelled: false};
  opening = attempt;
  status('Opening Areion Flight Console…', '', false);
  try {
    await closing;
    if (attempt.cancelled || document.hidden) return;
    const response = await api('session', {body: {}, signal: AbortSignal.timeout(4000)});
    const info = await response.json();
    if (!info.client) throw new Error('Missing client');
    if (attempt.cancelled || opening !== attempt || document.hidden) {
      await closeClient(info.client);
      return;
    }
    logical = {width: info.width, height: info.height};
    const current = {id: info.client, queue: [], keys: new Set(), busy: false, pinging: false,
      abort: new AbortController(), pinger: null, ready: false};
    lease = current;
    awaitingFocus = false;
    current.pinger = setInterval(async () => {
      if (lease !== current || current.pinging) return;
      current.pinging = true;
      try { await api('ping', {client: current.id, body: {}, signal: current.abort.signal}); }
      catch { lost(current); }
      finally { current.pinging = false; }
    }, 100);
    fit();
    void runFrames(current);
  } catch (e) {
    if (attempt.cancelled || opening !== attempt) return;
    if (e.status === 409) status('Console in use', 'Close the other console tab, then reconnect.');
    else if (e.status === 401 || e.status === 403)
      status('Console link expired', 'Open the current address printed by the local launcher.', false);
    else status('Could not reach the console', 'Start the local Areion browser host and try again.');
  } finally {
    if (opening === attempt) opening = null;
    if (attempt.cancelled && document.hasFocus()) resumeOnFocus();
  }
}

function fit() {
  const box = workspace.getBoundingClientRect();
  if (box.width < 1 || box.height < 1) return;
  const hostScale = Math.min(1, 2048 / box.width, 1536 / box.height);
  const width = Math.max(900, Math.round(box.width * hostScale));
  const height = Math.max(700, Math.round(box.height * hostScale));
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const signature = [width, height, dpr].join('x');
  if (lease && desiredSize !== signature) {
    desiredSize = signature;
    send({type: 'resize', width, height, dpr});
  }
  const scale = Math.min(box.width / logical.width, box.height / logical.height);
  const full = actualSize && scale < .995;
  workspace.classList.toggle('actual', full);
  if (!full) panning = false;
  workspace.classList.toggle('panning', panning);
  byId('pan-toggle').hidden = !full;
  byId('pan-toggle').setAttribute('aria-pressed', String(panning));
  screen.style.width = Math.max(1, Math.floor(logical.width * (full ? 1 : scale))) + 'px';
  screen.style.height = Math.max(1, Math.floor(logical.height * (full ? 1 : scale))) + 'px';
  byId('size-toggle').hidden = scale >= .995;
  byId('size-toggle').textContent = full ? 'Fit to window' : 'Actual size';
}

async function decodeImage(blob) {
  if (typeof createImageBitmap === 'function') return createImageBitmap(blob);
  const url = URL.createObjectURL(blob);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    return image;
  } finally { URL.revokeObjectURL(url); }
}

async function runFrames(session) {
  let seq = 0;
  while (lease === session && !document.hidden) {
    try {
      const r = await api('frame?after=' + seq, {client: session.id, signal: session.abort.signal});
      if (r.status === 204) continue;
      const img = await decodeImage(await r.blob());
      try {
        if (lease !== session) return;
        const width = Number(r.headers.get('X-Frame-Width')) || img.width;
        const height = Number(r.headers.get('X-Frame-Height')) || img.height;
        if (screen.width !== img.width || screen.height !== img.height) {
          screen.width = img.width;
          screen.height = img.height;
        }
        canvas.drawImage(img, 0, 0);
        const sizeChanged = logical.width !== width || logical.height !== height;
        logical = {width, height};
        if (sizeChanged) fit();
        seq = Number(r.headers.get('X-Frame-Id'));
        if (!session.ready) {
          session.ready = true;
          byId('status-panel').hidden = true;
          if (!byId('clipboard-dialog').open) screen.focus({preventScroll: true});
        }
      } finally { img.close?.(); }
    } catch { lost(session); return; }
  }
}

function send(event) {
  const current = lease;
  if (!current || (!current.ready && event.type !== 'resize')) return;
  if (event.type === 'reset') current.keys.clear();
  const last = current.queue[current.queue.length - 1];
  if (last && (event.type === 'move' || event.type === 'resize') && last.type === event.type)
    current.queue[current.queue.length - 1] = event;
  else current.queue.push(event);
  if (current.queue.length > 96) { lost(current); return; }
  if (!current.busy) void flush(current);
}

async function flush(current) {
  current.busy = true;
  try {
    while (current.queue.length && lease === current) {
      const events = current.queue.splice(0, 24);
      await api('events', {client: current.id, body: {events}, signal: current.abort.signal});
    }
  } catch { lost(current); }
  finally { current.busy = false; }
}

function modifiers(e) {
  return ['Shift', 'Control', 'Alt', 'Meta'].filter(m => e.getModifierState(m));
}

function locationInFrame(e) {
  const box = screen.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(logical.width - 1, Math.floor((e.clientX - box.left) * logical.width / box.width))),
    y: Math.max(0, Math.min(logical.height - 1, Math.floor((e.clientY - box.top) * logical.height / box.height)))
  };
}

function pointerEvent(type, e) {
  send({type, ...locationInFrame(e), button: Math.max(0, e.button), mods: modifiers(e)});
}

screen.addEventListener('pointerdown', e => {
  if (panning || !lease?.ready || (activePointer !== null && activePointer !== e.pointerId) || e.button > 2) return;
  e.preventDefault();
  screen.focus({preventScroll: true});
  activePointer = e.pointerId;
  screen.setPointerCapture(e.pointerId);
  const point = locationInFrame(e);
  const double = previousPress && e.button === previousPress.button &&
    e.timeStamp - previousPress.t < 400 && Math.abs(point.x - previousPress.x) < 5 &&
    Math.abs(point.y - previousPress.y) < 5;
  previousPress = double ? null : {...point, t: e.timeStamp, button: e.button};
  pointerEvent(double ? 'dblclick' : 'down', e);
});

screen.addEventListener('pointermove', e => {
  if (!panning && (activePointer === e.pointerId || (activePointer === null && e.pointerType !== 'touch')))
    pointerEvent('move', e);
});
screen.addEventListener('pointerup', e => {
  if (activePointer !== e.pointerId) return;
  pointerEvent('up', e);
  activePointer = null;
  if (screen.hasPointerCapture(e.pointerId)) screen.releasePointerCapture(e.pointerId);
});
for (const name of ['pointercancel', 'lostpointercapture']) {
  screen.addEventListener(name, e => {
    if (activePointer !== e.pointerId) return;
    activePointer = null;
    previousPress = null;
    send({type: 'reset'});
  });
}
screen.addEventListener('contextmenu', e => e.preventDefault());
screen.addEventListener('wheel', e => {
  if (!lease?.ready || panning) return;
  e.preventDefault();
  const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? screen.clientHeight : 1;
  send({type: 'wheel', ...locationInFrame(e), dx: e.deltaX * unit, dy: e.deltaY * unit, mods: modifiers(e)});
}, {passive: false});

function keyEvent(type, e) {
  return {type, key: e.key, code: e.code, text: [...e.key].length === 1 ? e.key : '', repeat: e.repeat, mods: modifiers(e)};
}
function forwardKey(e) {
  if (!lease?.ready || e.isComposing || e.key === 'Process' || e.key === 'Dead') return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') return;
  if (e.target === keyboard && [...e.key].length === 1 && !(e.ctrlKey || e.metaKey)) return;
  e.preventDefault();
  const key = e.code || e.key;
  if (e.type === 'keydown') {
    if (e.repeat && !lease.keys.has(key)) return;
    lease.keys.add(key);
  } else if (!lease.keys.delete(key)) return;
  send(keyEvent(e.type === 'keydown' ? 'keyDown' : 'keyUp', e));
}
for (const target of [screen, keyboard]) {
  target.addEventListener('keydown', forwardKey);
  target.addEventListener('keyup', forwardKey);
}
screen.addEventListener('paste', e => {
  const text = e.clipboardData?.getData('text/plain');
  if (text) { e.preventDefault(); send({type: 'text', text}); }
});
keyboard.addEventListener('input', e => {
  if (e.isComposing) return;
  if (keyboard.value) send({type: 'text', text: keyboard.value});
  keyboard.value = '';
});
keyboard.addEventListener('beforeinput', e => {
  const key = {'deleteContentBackward': 'Backspace', 'deleteContentForward': 'Delete', 'insertLineBreak': 'Enter'}[e.inputType];
  if (key && !e.isComposing) {
    e.preventDefault();
    for (const type of ['keyDown', 'keyUp']) send({type, key, code: key, text: '', mods: []});
  }
});
document.addEventListener('focusout', e => {
  if ((e.target === screen || e.target === keyboard) && e.relatedTarget !== screen && e.relatedTarget !== keyboard)
    send({type: 'reset'});
});
byId('keyboard-toggle').addEventListener('click', () => {
  keyboard.hidden = !keyboard.hidden;
  byId('keyboard-toggle').setAttribute('aria-expanded', String(!keyboard.hidden));
  (keyboard.hidden ? screen : keyboard).focus();
});
byId('pan-toggle').addEventListener('click', () => { panning = !panning; send({type: 'reset'}); fit(); });
byId('size-toggle').addEventListener('click', () => { actualSize = !actualSize; fit(); });
if (document.fullscreenEnabled) {
  const full = byId('fullscreen');
  full.hidden = false;
  full.addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch { notify('Full screen is unavailable.'); }
  });
  document.addEventListener('fullscreenchange', () => { full.textContent = document.fullscreenElement ? 'Exit full screen' : 'Full screen'; });
}
byId('clipboard').addEventListener('click', async () => {
  const current = lease;
  if (!current?.ready) { notify('Open the console to copy its clipboard.'); return; }
  let text;
  try {
    const r = await api('clipboard', {client: current.id, signal: current.abort.signal});
    text = (await r.json()).text;
  } catch { notify('Could not read the console clipboard.'); return; }
  if (!text) { notify('Console clipboard is empty.'); return; }
  try { await navigator.clipboard.writeText(text); notify('Copied to device clipboard.'); }
  catch {
    byId('clipboard-value').value = text;
    byId('clipboard-dialog').showModal();
    byId('clipboard-value').select();
  }
});
byId('clipboard-dialog').addEventListener('close', () => {
  byId('clipboard-value').value = '';
  screen.focus({preventScroll: true});
});
byId('resume').addEventListener('click', openConsole);
function resumeOnFocus() {
  if (document.hidden || !awaitingFocus) return;
  clearTimeout(focusTimer);
  focusTimer = setTimeout(openConsole, 175);
}
window.addEventListener('blur', pause);
window.addEventListener('focus', resumeOnFocus);
document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); else resumeOnFocus(); });
window.addEventListener('pagehide', () => { relinquish(); awaitingFocus = true; });
window.addEventListener('pageshow', e => { if (e.persisted) resumeOnFocus(); });
new ResizeObserver(fit).observe(workspace);
void openConsole();
