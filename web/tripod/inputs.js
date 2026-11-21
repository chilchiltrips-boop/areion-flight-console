import {clamp, startSimulator, stopSimulator, releaseInputs} from './tripod-physics.js';

export class SimulatorInput {
  constructor(sim) {
    this.sim = sim;
    this.source = 'local';
    this.identity = null;
  }
  stop() {
    // Preserve a virtual gain edit if input drops before the next 4 ms tick.
    Object.assign(this.sim.pid, this.sim.pendingPID);
    stopSimulator(this.sim);
    this.identity = null;
  }
  start(kit, now) {
    if (this.source === 'receiver') {
      if (!kit?.input || kit.input.until <= now) return 'Waiting for receiver input';
      this.sim.throttle = kit.input.channels[2];
    }
    if (!startSimulator(this.sim)) return 'Lower throttle to start';
    this.identity = this.source === 'receiver' ? kit.input.identity : null;
    return '';
  }
  sample(kit, now) {
    if (this.source !== 'receiver') return '';
    const input = kit?.input;
    if (!input || now >= input.until || (this.sim.running && input.identity !== this.identity)) {
      const wasRunning = this.sim.running;
      if (wasRunning || this.sim.throttle !== 1000 || this.sim.cmdRoll || this.sim.cmdPitch || this.sim.cmdYaw) this.stop();
      return wasRunning ? 'Receiver lost or changed · run again at low throttle' : '';
    }
    const [roll, pitch, throttle, yaw] = input.channels;
    this.sim.throttle = clamp(throttle,1000,2000);
    const axis = value => clamp((value - 1500) / 500, -1, 1);
    this.sim.cmdRoll = axis(roll); this.sim.cmdPitch = axis(pitch); this.sim.cmdYaw = axis(yaw);
    return '';
  }
}

export function bindSticks(root, sim, local, signal, toggleRun) {
  const keys = new Set(), pointers = new Map();
  const pads = [...root.querySelectorAll('[data-pad]')];
  const signed = (plus, minus) => Number(keys.has(plus)) - Number(keys.has(minus));
  const deadband = value => {
    const d = Math.abs(value);
    if (d <= .04) return 0;
    const t = (d - .04) / .96;
    return Math.sign(value) * (.8*t + .2*t**3);
  };
  function update(dt = 0) {
    if (!local()) return;
    const left = pointers.get('left'), right = pointers.get('right');
    sim.cmdRoll = clamp(deadband(right?.x ?? 0) + signed('ArrowRight','ArrowLeft'), -1, 1);
    sim.cmdPitch = clamp(deadband(right?.y ?? 0) + signed('ArrowUp','ArrowDown'), -1, 1);
    sim.cmdYaw = clamp(deadband(left?.x ?? 0) + signed('KeyD','KeyA'), -1, 1);
    if (sim.running && left) sim.throttle = clamp(sim.throttle + deadband(left.y)*400*dt, 1000, 2000);
  }
  for (const pad of pads) {
    const side = pad.dataset.pad;
    const move = event => {
      const point = pointers.get(side);
      if (point?.id !== event.pointerId) return;
      const rect = pad.getBoundingClientRect(), radius = Math.max(1, rect.width * .4);
      const x = (event.clientX - rect.left - rect.width/2)/radius;
      const y = (rect.top + rect.height/2 - event.clientY)/radius;
      const length = Math.max(1, Math.hypot(x,y));
      point.x = x/length; point.y = y/length;
      update();
    };
    pad.addEventListener('pointerdown', event => {
      if (!local() || event.button !== 0 || pointers.has(side)) return;
      event.preventDefault(); pad.focus({preventScroll:true}); pad.setPointerCapture(event.pointerId);
      pointers.set(side, {id:event.pointerId,x:0,y:0}); move(event);
    }, {signal});
    pad.addEventListener('pointermove',move,{signal});
    for (const event of ['pointerup','pointercancel','lostpointercapture']) {
      pad.addEventListener(event,e=>{
        if (pointers.get(side)?.id === e.pointerId) { pointers.delete(side); update(); }
      },{signal});
    }
  }
  const allowed = ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','KeyA','KeyD','KeyW','KeyS','KeyR'];
  window.addEventListener('keydown',event=>{
    if (!local() || document.hidden || event.ctrlKey || event.metaKey || event.altKey ||
        event.target.closest?.('input,textarea,select,[contenteditable=true],dialog') || document.querySelector('dialog[open]') ||
        !allowed.includes(event.code)) return;
    event.preventDefault();
    if (event.code === 'KeyR') { if (!event.repeat) toggleRun(); return; }
    if (event.code === 'KeyW' || event.code === 'KeyS') {
      sim.throttle = clamp(sim.throttle + (event.code === 'KeyW' ? 25 : -25),1000,2000);
    } else { keys.add(event.code); update(); }
  }, {signal});
  window.addEventListener('keyup',event=>{ if (keys.delete(event.code)) update(); }, {signal});
  return {update, release() {
    for (const pad of pads) {
      const id = pointers.get(pad.dataset.pad)?.id;
      if (id != null && pad.hasPointerCapture(id)) pad.releasePointerCapture(id);
    }
    pointers.clear(); keys.clear(); releaseInputs(sim);
  }};
}
