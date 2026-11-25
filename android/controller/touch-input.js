// DroneLab response curves; pulses are written in the Areion A1 channel order.
export const responses = Object.freeze({
  Slow:   Object.freeze({deadband: .05, expo: .40, scale: .45, slew: 200}),
  Medium: Object.freeze({deadband: .04, expo: .20, scale: .72, slew: 400}),
  Fast:   Object.freeze({deadband: .03, expo: .05, scale: 1,   slew: 600})
});

const limit = (n, min, max) => Math.max(min, Math.min(n, max));
const sides = ['left', 'right'];

function shape(value, profile) {
  const travel = Math.max(0, (Math.abs(value) - profile.deadband) / (1 - profile.deadband));
  return Math.sign(value) * ((1 - profile.expo) * travel + profile.expo * travel ** 3);
}

export class TouchInput {
  constructor(controls, preset = 'Medium') {
    this.controls = controls;
    this.preset = Object.hasOwn(responses, preset) ? preset : 'Medium';
    this.pointers = new Map();
    this.lastValues = controls.values;
    this.throttle = controls.values[2];
    this.lastTime = null;
  }

  // The sender replaces this array whenever it neutralises or requalifies.
  // A thumb held over that boundary must make a new contact to command again.
  synchronize() {
    if (this.lastValues === this.controls.values) return;
    this.pointers.clear();
    this.lastValues = this.controls.values;
    this.throttle = this.controls.values[2];
    this.lastTime = null;
  }

  begin(side, id, x, y, radius, time) {
    this.synchronize();
    if (!sides.includes(side) || this.pointers.has(side) ||
        [...this.pointers.values()].some(p => p.id === id)) return false;
    const pointer = {id, originX: x, originY: y, radius: Math.max(1, radius), x: 0, y: 0};
    this.pointers.set(side, pointer);
    if (side === 'left') {
      this.throttle = this.controls.values[2];
      this.lastTime = time;
    }
    this.write(side, pointer);
    return true;
  }

  move(side, id, x, y, time) {
    this.synchronize();
    const pointer = this.pointers.get(side);
    if (!pointer || pointer.id !== id) return false;
    if (side === 'left') this.tick(time);
    const dx = (x - pointer.originX) / pointer.radius;
    const dy = (pointer.originY - y) / pointer.radius;
    const length = Math.max(1, Math.hypot(dx, dy));
    pointer.x = dx / length;
    pointer.y = dy / length;
    this.write(side, pointer);
    return true;
  }

  tick(time) {
    this.synchronize();
    const pointer = this.pointers.get('left');
    if (!pointer) return;
    const seconds = limit((time - this.lastTime) / 1000, 0, .08);
    const profile = responses[this.preset];
    this.lastTime = time;
    this.throttle = limit(this.throttle + shape(pointer.y, profile) * profile.slew * seconds, 1000, 2000);
    this.controls.values[2] = Math.round(this.throttle);
  }

  write(side, pointer) {
    const profile = responses[this.preset];
    const x = shape(pointer.x, profile) * profile.scale;
    if (side === 'left') {
      // Controls.stick uses absolute throttle. Map the integrated pulse back
      // onto that API, preserving A1 yaw-right = increasing CH4.
      this.controls.stick(true, x, (this.throttle - 1500) / 500, true);
    } else {
      this.controls.stick(false, x, shape(pointer.y, profile) * profile.scale, true);
    }
  }

  end(side, id, time) {
    this.synchronize();
    const pointer = this.pointers.get(side);
    if (!pointer || pointer.id !== id) return false;
    if (side === 'left') this.tick(time);
    this.pointers.delete(side);
    this.controls.stick(side === 'left', 0, 0, false);
    return true;
  }

  release() {
    this.synchronize();
    for (const side of this.pointers.keys()) this.controls.stick(side === 'left', 0, 0, false);
    this.pointers.clear();
    this.lastTime = null;
  }
}
