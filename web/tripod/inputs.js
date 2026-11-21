import {clamp, startSimulator, stopSimulator, releaseInputs} from './tripod-physics.js';
import {stickPoint, pulseForAxis} from '../stick-geometry.js';

export const PAD_TRAVEL = .40;
export const inputNames = {local:'Virtual sticks', PPM:'PPM receiver', AP:'AP Wi-Fi input', USB:'USB input', receiver:'Active kit input'};

export class SimulatorInput {
  constructor(sim, source = 'local') {
    this.sim = sim;
    this.source = source;
    this.identity = null;
  }
  get local() { return this.source === 'local'; }
  receiver(kit, now) {
    if (!kit || this.local) return null;
    const accepted = kit.input;
    const sample = this.source === 'receiver' || accepted?.source === this.source ? accepted :
      this.source === 'PPM' ? kit.rawPpm : null;
    return sample && now < sample.until ? sample : null;
  }
  stop() {
    Object.assign(this.sim.pid, this.sim.pendingPID);
    stopSimulator(this.sim);
    this.identity = null;
  }
  virtualStartPulse() {
    return this.sim.throttle < this.sim.settings.throttleLow ? 1500 : Math.round(this.sim.throttle);
  }
  start(kit, now) {
    if (this.sim.running) return '';
    const sample = this.receiver(kit,now);
    if (this.local) {
      // Explicit software-only run. Show this starting pulse on the Run button.
      if (!startSimulator(this.sim, this.virtualStartPulse())) return 'Set a valid virtual throttle';
    } else {
      if (!sample) return 'Waiting for '+inputNames[this.source];
      this.sim.throttle = sample.channels[2];
      if (!startSimulator(this.sim)) return 'Lower throttle to start';
      this.identity = sample.identity;
      this.sample(kit,now);
    }
    return '';
  }
  sample(kit, now) {
    if (this.local) return '';
    const input = this.receiver(kit,now);
    if (!input || (this.sim.running && input.identity !== this.identity)) {
      const running = this.sim.running;
      if (running || this.sim.throttle !== 1000 || this.sim.cmdRoll || this.sim.cmdPitch || this.sim.cmdYaw) this.stop();
      return running ? 'Receiver lost or changed · run again at low throttle' : '';
    }
    const [roll, pitch, throttle, yaw] = input.channels;
    const axis = value => clamp((value - 1500) / 500, -1, 1);
    this.sim.throttle = clamp(throttle,1000,2000);
    this.sim.cmdRoll = axis(roll); this.sim.cmdPitch = axis(pitch); this.sim.cmdYaw = axis(yaw);
    return '';
  }
}

// Render the two gimbals from the same values that drive the FC's mixer.
export function bindSticks(root, sim, local, signal, toggleRun, changed) {
  const keys = new Set(), pointers = new Map();
  const pads = [...root.querySelectorAll('[data-pad]')];
  const available = () => local() && root.isConnected && !root.closest('[hidden]') && !document.hidden;
  const signed = (plus, minus) => Number(keys.has(plus)) - Number(keys.has(minus));
  function update(dt = 0) {
    if (!available()) return;
    const left = pointers.get('left'), right = pointers.get('right');
    sim.cmdRoll = right?.x ?? signed('ArrowRight','ArrowLeft');
    sim.cmdPitch = right?.y ?? signed('ArrowUp','ArrowDown');
    sim.cmdYaw = left?.x ?? signed('KeyD','KeyA');
    if (!left && (keys.has('KeyW') || keys.has('KeyS')))
      sim.throttle = clamp(sim.throttle + signed('KeyW','KeyS') * 500 * Math.min(dt,.08),1000,2000);
  }
  function paint() { update(); changed(); }
  for (const pad of pads) {
    const side = pad.dataset.pad;
    const move = event => {
      const contact = pointers.get(side);
      if (contact?.id !== event.pointerId || !available()) return;
      Object.assign(contact, stickPoint(pad.getBoundingClientRect(),event.clientX,event.clientY,PAD_TRAVEL));
      if (side === 'left') sim.throttle = pulseForAxis(contact.y);
      sim.pulse = null;
      paint();
    };
    pad.addEventListener('pointerdown', event => {
      if (!available() || event.button !== 0 || pointers.has(side)) return;
      event.preventDefault();
      pad.focus({preventScroll:true}); pad.setPointerCapture(event.pointerId);
      pointers.set(side,{id:event.pointerId,x:0,y:0}); move(event);
    },{signal});
    pad.addEventListener('pointermove',move,{signal});
    for (const name of ['pointerup','pointercancel','lostpointercapture']) {
      pad.addEventListener(name,event=>{
        if (pointers.get(side)?.id !== event.pointerId) return;
        pointers.delete(side); paint();
      },{signal});
    }
  }
  const allowed = ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','KeyA','KeyD','KeyW','KeyS','KeyR'];
  window.addEventListener('keydown',event=>{
    if (!available() || event.ctrlKey || event.metaKey || event.altKey ||
        event.target.closest?.('input,textarea,select,[contenteditable=true],dialog') || document.querySelector('dialog[open]') ||
        !allowed.includes(event.code)) return;
    event.preventDefault();
    if (event.code === 'KeyR') { if (!event.repeat) toggleRun(); return; }
    if (!event.repeat && (event.code === 'KeyW' || event.code === 'KeyS') && !pointers.has('left'))
      sim.throttle = clamp(sim.throttle + (event.code === 'KeyW' ? 5 : -5),1000,2000);
    sim.pulse=null;keys.add(event.code);paint();
  },{signal});
  window.addEventListener('keyup',event=>{if(keys.delete(event.code))paint();},{signal});
  function release() {
    for (const pad of pads) {
      const id = pointers.get(pad.dataset.pad)?.id;
      pointers.delete(pad.dataset.pad);
      if (id != null && pad.hasPointerCapture(id)) pad.releasePointerCapture(id);
    }
    keys.clear();
    if (local()) releaseInputs(sim);
  }
  window.addEventListener('blur',release,{signal});
  return {update,release};
}
