// Own the calibration evidence for one controller connection and one set of offsets.
import {SensorCheck} from './calibration.js';
import {equal} from './config-commands.js';

export class CalibrationSession {
  constructor() {
    this.sensor = new SensorCheck();
    this.reset();
  }
  reset() {
    this.sensor.clear();
    this.owner = null;
    this.saved = false;
    this.writing = false;
    this.writeAttempted = false;
  }
  gate(ctx, controls, now = performance.now()) {
    if (!ctx || ctx.replay || ctx.state !== 'connected' || !ctx.link?.session || !ctx.link.fcSession)
      return 'Connect the kit over USB or AP Wi-Fi.';
    if (!controls.confirmed) return 'Confirm that all propellers are removed.';
    const status = ctx.model.get(120, now, 500), setup = ctx.model.get(130, now, 500);
    if (!status || !setup?.[15]) return 'Waiting for current controller status.';
    if (status[0] !== false) return 'Disarm the kit before calibration.';
    if (!controls.entered || !setup[0] || setup[1] || setup[2] < 1)
      return 'Begin kit setup to lock arming.';
    if (setup[8] || [1, 2].includes(setup[3])) return 'Finish the ESC or motor test first.';
    if (!status[7]) return 'Controller storage is unavailable.';
    if (!status[2] || !status[5] || !ctx.model.get(21, now, 500)) return 'Waiting for live accelerometer and gyro readings.';
    if (!ctx.model.get(6, now, Infinity)) return 'Waiting for controller offsets.';
    return '';
  }
  start(ctx, baseline, kit, now) {
    this.reset();
    if (!this.sensor.start(now,baseline)) throw Error('Invalid controller offsets.');
    this.owner = {link:ctx.link, host:ctx.link.session, boot:ctx.link.fcSession, kit};
  }
  sameOwner(ctx, now) {
    const owner = this.owner;
    return owner && ctx?.link === owner.link && ctx.link.session === owner.host &&
      ctx.link.fcSession === owner.boot && ctx.model.get(130, now, 500)?.[15] === owner.kit;
  }
  stop(note) {
    if (this.sensor.active) this.sensor.stop(note);
  }
  invalidate(reason) {
    this.reset();
    this.sensor.end('stopped',reason);
  }
  sync(ctx, controls, now = performance.now()) {
    if (!this.owner) return;
    const offsets = ctx.model.get(6, now, Infinity);
    if (!this.sameOwner(ctx, now) || ctx.replay || ctx.state !== 'connected') {
      this.invalidate('Connection changed. Start calibration again.');
      return;
    }
    const candidateActive = this.writeAttempted && equal(offsets, this.sensor.offsets);
    if (!equal(offsets, this.sensor.baseline) && !candidateActive) {
      this.invalidate('Controller offsets changed. Start calibration again.');
      return;
    }
    // A group 6 SET temporarily invalidates the MCU's attitude. The save procedure
    // verifies fresh IMU status explicitly before it confirms the sensor.
    if (this.writing) return;
    if (this.saved && !ctx.model.get(130,now,500)?.[5]) {
      this.invalidate('Controller sensor verification changed.');
      return;
    }
    if (!this.saved && this.sensor.ready) {
      const status=ctx.model.get(120,now,500),setup=ctx.model.get(130,now,500);
      if (!controls.confirmed || !controls.entered || !setup?.[0] || setup[1] || setup[8] || [1,2].includes(setup[3]) || status?.[0]!==false) {
        this.invalidate('Setup conditions changed. Repeat the calibration.');
        return;
      }
    }
    if (this.sensor.active) {
      const reason = this.gate(ctx,controls,now);
      if (reason) this.stop(reason);
    }
  }
  onPacket(packet,ctx,controls) {
    if (!this.sensor.active) return;
    this.sync(ctx,controls,packet.at);
    if (this.sensor.active && packet.group===21 && packet.event===true)
      this.sensor.sample(packet.values,packet.at);
  }
  ready(ctx, controls, now = performance.now()) {
    return !this.saved && this.sensor.ready && this.sameOwner(ctx,now) &&
      !this.gate(ctx,controls,now) && (equal(ctx.model.get(6,now,Infinity),this.sensor.baseline) ||
      this.writeAttempted && equal(ctx.model.get(6,now,Infinity),this.sensor.offsets));
  }
  async save(op, ctx, controls) {
    if (!this.ready(ctx,controls)) throw Error('Complete the six-position calibration on this kit.');
    const owner = this.owner, offsets = [...this.sensor.offsets], baseline = [...this.sensor.baseline];
    const retry = this.writeAttempted;
    this.writing = true;
    try {
      await op.saveSensor(owner.kit, offsets, baseline, retry, () => { this.writeAttempted = true; });
      if (owner !== this.owner) throw Error('Calibration session changed during save.');
      this.saved = true;
    } finally {
      this.writing = false;
    }
  }
}
