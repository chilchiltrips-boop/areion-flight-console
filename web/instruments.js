// All times are monotonic milliseconds within the current USB session or recording.
const FRESH = 500;
const SOURCES = ['PPM', 'AP', 'USB'];
const ageOK = (age) => age >= 0 && age <= FRESH;
const finite = (values) => values?.every(Number.isFinite);
const tone = (label, level = 'idle') => ({label, level});
export class Instruments {
  constructor() {
    this.frames = new Map();
    this.orientation = null;
    this.receiverGate = '';
    this.rxSince = Infinity;
  }

  get(group, now, maxAge = FRESH) {
    const row = this.frames.get(group);
    return row && now >= row.at && now - row.at <= maxAge ? row.values : null;
  }

  push(row) {
    this.frames.set(row.group, row);
    const v = row.values;
    if (row.group === 122) {
      const key = v[4] ? [v[0], v[1], v[5], v[0] === 0 ? 0 : v[7]].join('/') : '';
      if (key !== this.receiverGate) {
        this.rxSince = row.at;
        this.receiverGate = key;
      }
    }
    if (row.group === 120 && (!v[2] || v[5] === 0)) this.orientation = null;
    if (row.group !== 21) return;
    const status = this.get(120, row.at);
    if (!finite(v) || !status?.[2] || !status[5]) {
      this.orientation = null;
      return;
    }
    const prior = this.orientation;
    const [roll, pitch] = v.slice(8, 10);
    const rad = Math.PI / 180;
    const nearVertical = Math.abs(pitch) >= 80;
    const rate = nearVertical ? null : (v[1] * Math.sin(roll * rad) + v[2] * Math.cos(roll * rad)) / Math.cos(pitch * rad);
    const dt = prior ? row.at - prior.at : Infinity;
    let yaw = rate === null ? null : 0;
    if (prior?.rate != null && rate !== null && ageOK(dt)) {
      yaw = ((prior.yaw + (prior.rate + rate) * 0.5 * dt / 1000 + 180) % 360 + 360) % 360 - 180;
    }
    this.orientation = {at: row.at, roll, pitch, yaw, rate};
  }

  snapshot(now) {
    const status = this.get(120, now);
    const report = this.get(122, now);
    const setup = this.get(130, now);
    const device = this.get(125, now, Infinity);
    const timeouts = this.get(112, now, Infinity);
    const selected = report?.[0];
    const name = SOURCES[selected];
    let input = tone('Waiting');
    let channels = null;
    if (name) {
      const signal = report[[2, 3, 8][selected]];
      const count = report[5];
      const countValid = selected === 0 ? count >= 4 && count <= 8 : count === 8;
      const timeout = timeouts?.[selected === 0 ? 0 : 1] ?? 250;
      if (report[4] && (!signal || !countValid || report[1] !== selected + 1 || (selected !== 0 && !report[7])))
        input = tone('Invalid', 'bad');
      else if (!signal) input = tone('Signal lost', status?.[0] ? 'bad' : 'warn');
      else if (report[6] >= timeout) input = tone('Stale', 'warn');
      else if (!report[4] || !countValid) input = tone('Waiting', 'warn');
      else {
        input = tone(selected === 0 ? 'PPM pulses' : name + ' active', 'good');
        const receiver = this.frames.get(22);
        if (receiver && receiver.at >= this.rxSince && ageOK(now - receiver.at))
          channels = receiver.values.slice(0, count);
      }
    }

    const imu = status?.[2] && status[5] && this.orientation && ageOK(now - this.orientation.at) ? this.orientation : null;
    const imuHealth = setup?.[14] === 'IMU_STARTUP_FAILED' || (status && !status[2]) ? tone('Read fault','bad') :
      status && !status[5] ? tone('Calibrating','warn') : imu ? tone('Reading','good') : tone('Waiting');
    const motor = this.get(23, now)?.slice(3, 7);
    const validMotors = motor?.length === 4 && motor.every(value => Number.isFinite(value) && value >= 900 && value <= 2200);
    const rate = status?.[4] > 0 ? 1 / status[4] : null;
    const health = {
      telemetry: status ? tone('Receiving', 'good') : tone('Waiting'),
      input,
      sensor: imuHealth,
      output: validMotors ? tone('Reported', 'good') : motor ? tone('Invalid', 'bad') : tone('Waiting'),
      setup: setup ? setup[1] && !setup[0] ? tone('Verified', 'good') : tone('Setup open', 'warn') : tone('Waiting'),
      storage: status ? status[7] ? tone('Ready', 'good') : tone('Fault', 'bad') : tone('Waiting')
    };
    return {status, source: name, input, channels, imu, health, loop: rate, motor: validMotors ? motor : null, firmware: device?.[0]};
  }
}
