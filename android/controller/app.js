import {ApController} from './controller.js';
import {TouchInput, responses} from './touch-input.js';

const deck = document.getElementById('flight-page');
const controller = new ApController();
const storageKey = 'areion.android.touch.response.v1';
let preferred;
try { preferred = localStorage.getItem(storageKey); } catch {}
const sticks = new TouchInput(controller.controls, preferred);

const pads = [...deck.querySelectorAll('[data-pad]')].map(element => ({
  element, side: element.dataset.pad, ring: element.querySelector('.ring')
}));
const order = {roll: 0, pitch: 1, throttle: 2, yaw: 3};
const channels = [...deck.querySelectorAll('[data-channel]')].map(output => ({
  output, index: order[output.dataset.channel],
  echo: deck.querySelector('[data-echo="' + output.dataset.channel + '"]')
}));
const buttons = Object.fromEntries([...deck.querySelectorAll('[data-deck-action]')]
  .map(button => [button.dataset.deckAction, button]));
const mood = document.getElementById('arm-state');
const link = document.getElementById('link-state');
const feedback = document.getElementById('feedback');
const attitude = document.getElementById('attitude');
const aux = document.getElementById('aux-panel');
const auxList = document.getElementById('aux-channels');
const linkNames = {
  offline: 'Offline', error: 'Link error', opening: 'Connecting', handshake: 'Linking',
  connected: 'AP online', stale: 'Link stale'
};
let state;
let tickFrame = 0;
let stopping = false;
let actionError = '';
let errorUntil = 0;

function text(element, value) {
  if (element.textContent !== value) element.textContent = value;
}

function buzz(kind = 'tick') {
  try { window.AreionAndroid?.haptic(kind); } catch {}
}

function readChannels() {
  for (const {index, output, echo} of channels) {
    const pulse = controller.controls.values[index];
    const received = state?.received?.[index];
    text(output, Number.isFinite(pulse) ? String(Math.round(pulse)) : '—');
    text(echo, Number.isFinite(received) ? 'RX ' + Math.round(received) : '');
  }
}

function paintPads() {
  for (const {side, ring} of pads) {
    const point = sticks.pointers.get(side);
    if (point) {
      ring.classList.add('active');
      ring.style.setProperty('--dx', point.x * point.radius + 'px');
      ring.style.setProperty('--dy', -point.y * point.radius + 'px');
    } else if (ring.classList.contains('active')) {
      ring.classList.remove('active');
      ring.style.removeProperty('left');
      ring.style.removeProperty('top');
      ring.style.removeProperty('--dx');
      ring.style.removeProperty('--dy');
    }
  }
  readChannels();
}

function releasePads() {
  cancelAnimationFrame(tickFrame);
  tickFrame = 0;
  const held = new Map(sticks.pointers);
  sticks.release();
  for (const {side, element} of pads) {
    const id = held.get(side)?.id;
    if (id !== undefined && element.hasPointerCapture(id)) element.releasePointerCapture(id);
  }
  paintPads();
}

function tick(now) {
  tickFrame = 0;
  if (document.hidden || !controller.canEdit() || stopping) {
    releasePads();
    return;
  }
  sticks.tick(now);
  paintPads();
  if (sticks.pointers.has('left')) tickFrame = requestAnimationFrame(tick);
}

for (const {element, side, ring} of pads) {
  element.addEventListener('contextmenu', event => event.preventDefault());
  element.addEventListener('pointerdown', event => {
    if (event.button !== 0 || !controller.canEdit() || !aux.hidden || stopping) return;
    const rect = element.getBoundingClientRect();
    const radius = Math.max(18, ring.offsetWidth * .35);
    if (!sticks.begin(side, event.pointerId, event.clientX, event.clientY, radius, performance.now())) return;
    event.preventDefault();
    element.setPointerCapture(event.pointerId);
    ring.style.left = (event.clientX - rect.left) + 'px';
    ring.style.top = (event.clientY - rect.top) + 'px';
    buzz();
    paintPads();
    if (side === 'left' && !tickFrame) tickFrame = requestAnimationFrame(tick);
  });
  element.addEventListener('pointermove', event => {
    if (stopping || !controller.canEdit()) return;
    if (!sticks.move(side, event.pointerId, event.clientX, event.clientY, performance.now())) return;
    event.preventDefault();
    paintPads();
  });
  const release = event => {
    if (sticks.end(side, event.pointerId, performance.now())) paintPads();
  };
  for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) element.addEventListener(type, release);
}

function closeAux() {
  aux.hidden = true;
  buttons.aux.setAttribute('aria-expanded', 'false');
}

function releaseUI() {
  releasePads();
  closeAux();
}

const auxControls = [5, 6, 7, 8].map(channel => {
  const label = document.createElement('label');
  const name = document.createElement('span');
  name.textContent = 'CH' + channel;
  const slider = document.createElement('input');
  slider.type = 'range';
  slider.min = '1000';
  slider.max = '2000';
  slider.step = '1';
  slider.setAttribute('aria-label', 'Channel ' + channel);
  const value = document.createElement('output');
  slider.addEventListener('input', () => {
    if (!state || slider.disabled || aux.hidden || !controller.canEdit() || channel === state.modeChannel) return;
    controller.controls.values[channel - 1] = slider.valueAsNumber;
    text(value, slider.value + ' µs');
  });
  label.append(name, slider, value);
  auxList.append(label);
  return {channel, slider, value};
});

function paintAux() {
  if (!state || aux.hidden) return;
  for (const {channel, slider, value} of auxControls) {
    const modeChannel = channel === (state.modeChannel ?? 5);
    slider.disabled = modeChannel || !controller.canEdit() || stopping;
    const pulse = controller.controls.values[channel - 1];
    slider.value = String(pulse);
    text(value, modeChannel ? 'Flight mode' : pulse + ' µs');
  }
}

function render(nextState) {
  state = nextState;
  sticks.synchronize();
  if ((!state.canEdit || stopping) && sticks.pointers.size) releasePads();
  paintPads();
  paintAux();
  const busy = ['opening', 'handshake'].includes(state.connection);
  const linked = state.connection === 'connected';
  const disarm = state.armed === true && state.sending;
  text(link, linkNames[state.connection] ?? 'Offline');
  link.dataset.state = state.connection;
  text(mood, state.armed === true ? 'Armed' : state.armed === false ? 'Disarmed' : 'Arm —');
  mood.dataset.armed = state.armed == null ? 'unknown' : String(state.armed);
  text(buttons.connect, linked || state.connection === 'stale' ? 'Disconnect' : busy ? 'Cancel' : 'Connect AP');
  buttons.connect.disabled = !state.canConnect;
  buttons.wifi.hidden = typeof window.AreionAndroid?.openWifiSettings !== 'function';
  buttons.wifi.disabled = state.sending || busy;
  buttons.source.hidden = !linked || state.selected == null || state.selected === 1;
  buttons.source.disabled = !state.canChooseAp;
  text(buttons.send, state.sending ? 'Stop sender' : 'Start sender');
  buttons.send.disabled = !state.canSend;
  text(buttons.arm, disarm ? 'Disarm' : 'Arm');
  buttons.arm.disabled = (!disarm && !state.canArm) || stopping;
  text(buttons.mode, state.mode === 0 ? 'Angle' : state.mode === 1 ? 'Rate / Acro' : 'Mode —');
  buttons.mode.disabled = !state.canMode;
  buttons.mode.setAttribute('aria-label', state.mode === 0 ? 'Angle mode, switch to Rate / Acro' :
    state.mode === 1 ? 'Rate / Acro mode, switch to Angle' : 'Flight mode unavailable');
  text(buttons.preset, sticks.preset);
  buttons.preset.setAttribute('aria-label', 'Stick response: ' + sticks.preset);
  for (const {element} of pads) element.setAttribute('aria-disabled', String(!state.canEdit || stopping));
  let message = state.feedback || (state.ready ? 'Sender active' : 'Sender off');
  if (state.ready && state.senderHz > 0) message += ' · ' + Math.round(state.senderHz) + ' Hz';
  text(feedback, errorUntil > performance.now() ? actionError : message);
  attitude.hidden = !linked || !state.imu;
  if (!attitude.hidden) {
    const angle = n => Number.isFinite(n) ? Math.round(n) + '°' : '—';
    text(attitude, 'R ' + angle(state.imu.roll) + '  P ' + angle(state.imu.pitch) + '  Y ' + angle(state.imu.yaw));
  }
}

async function execute(action) {
  try { return await action(); }
  catch (error) {
    actionError = error?.message || 'Command failed';
    errorUntil = performance.now() + 5000;
    text(feedback, actionError);
  }
}

async function stop() {
  if (stopping) return;
  stopping = true;
  releaseUI();
  buzz('stop');
  try { await execute(() => controller.stop()); }
  finally {
    stopping = false;
    if (state) render(state);
  }
}

buttons.stop.addEventListener('pointerdown', event => {
  if (event.button !== 0) return;
  event.preventDefault();
  void stop();
});
// A non-primary finger can reach pointerdown without generating a click.
// Keyboard and accessibility actions still activate the same command.
buttons.stop.addEventListener('click', event => { if (event.detail === 0) void stop(); });
buttons.wifi.onclick = () => {
  releaseUI();
  controller.suspend();
  window.AreionAndroid?.openWifiSettings();
};
buttons.connect.onclick = () => { releaseUI(); buzz(); void execute(() => controller.connect()); };
buttons.source.onclick = () => { releaseUI(); buzz('confirm'); void execute(() => controller.chooseAp()); };
buttons.send.onclick = () => { releaseUI(); buzz(); void execute(() => controller.toggleSender()); };
buttons.arm.onclick = () => {
  if (state?.armed && state.sending) { void stop(); return; }
  buzz('confirm');
  void execute(() => controller.arm());
};
buttons.mode.onclick = () => {
  if (!state?.canMode) return;
  buzz();
  void execute(() => controller.setMode(state.mode === 0 ? 1 : 0));
};
buttons.preset.onclick = () => {
  if (sticks.pointers.size) return;
  const presets = Object.keys(responses);
  sticks.preset = presets[(presets.indexOf(sticks.preset) + 1) % presets.length];
  try { localStorage.setItem(storageKey, sticks.preset); } catch {}
  buzz();
  if (state) render(state);
};
buttons.aux.onclick = () => {
  if (sticks.pointers.size) return;
  aux.hidden = !aux.hidden;
  buttons.aux.setAttribute('aria-expanded', String(!aux.hidden));
  buzz();
  paintAux();
};
buttons.closeAux.onclick = () => { closeAux(); buzz(); };
window.addEventListener('areion-app-pause', releaseUI);
window.addEventListener('blur', releaseUI);
document.addEventListener('visibilitychange', () => { if (document.hidden) releaseUI(); });

controller.subscribe(render);
