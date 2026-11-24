// Reported acceleration already includes the three additive offsets in group 6.
// Group 21's gyroscope rates include the controller's boot calibration.
export const poses = [
  ['Flat / level', 2, 1, [0, 0, 0]],
  ['Nose up', 0, -1, [0, 90, 0]],
  ['Nose down', 0, 1, [0, -90, 0]],
  ['Left side down', 1, -1, [-90, 0, 0]],
  ['Right side down', 1, 1, [90, 0, 0]],
  ['Upside down', 2, -1, [180, 0, 0]]
];

const HOLD_MS = 3000, SAMPLES = 20, MAX_GAP_MS = 500;
const GYRO_RESIDUAL_LIMIT = 1;
export const FIT_ERROR_LIMIT = .12;
const AXES = [0, 1, 2];
const maximumAbs = vector => Math.max(...vector.map(Math.abs));

function classify(acc) {
  const norm = Math.hypot(...acc);
  if (norm < .60 || norm > 1.55) return -1;
  return poses.findIndex(([, axis, sign]) => {
    const along = sign * acc[axis];
    return along >= .55 && along <= 1.50 && acc.every((v, i) => i === axis || Math.abs(v) <= .35);
  });
}

function detectPose(reported, raw) {
  const current = classify(reported), uncorrected = classify(raw);
  if (current >= 0 && uncorrected >= 0 && current !== uncorrected) return -1;
  return current >= 0 ? current : uncorrected;
}

// Welford's recurrence keeps both the storage and per-packet cost bounded.
class StationaryWindow {
  constructor(face, at) {
    this.face = face;
    this.started = at;
    this.last = null;
    this.count = 0;
    this.mean = Array(6).fill(0);
    this.m2 = Array(6).fill(0);
    this.low = Array(6).fill(Infinity);
    this.high = Array(6).fill(-Infinity);
  }
  add(sample, at) {
    // Multiple complete frames can arrive in one browser read after a stall.
    if (this.last !== null && at - this.last < 20) return;
    this.count++;
    this.last = at;
    sample.forEach((value, i) => {
      const delta = value - this.mean[i];
      this.mean[i] += delta / this.count;
      this.m2[i] += delta * (value - this.mean[i]);
      this.low[i] = Math.min(this.low[i], value);
      this.high[i] = Math.max(this.high[i], value);
    });
  }
  get progress() {
    return this.last === null ? 0 : Math.min(1, (this.last - this.started) / HOLD_MS, this.count / SAMPLES);
  }
  get varied() {
    return this.mean.some((_, i) =>
      (i >= 3 && this.high[i] - this.low[i] > .10) ||
      Math.sqrt(this.m2[i] / this.count) > (i < 3 ? .8 : .025));
  }
}

export class SensorCheck {
  constructor() { this.clear(); }

  clear() {
    this.phase = 'idle';
    this.active = null;
    this.detected = null;
    this.window = null;
    this.faces = new Map();
    this.gyroMeans = new Map();
    this.baseline = null;
    this.offsets = null;
    this.gyro = null;
    this.quality = null;
    this.note = '';
  }
  get nextPose() {
    const index = poses.findIndex((_, i) => !this.faces.has(i));
    return index < 0 ? null : index;
  }
  get progress() { return this.window?.progress ?? 0; }
  get ready() { return this.phase === 'complete'; }
  get needsRetry() { return this.phase === 'review'; }

  retryFaces(now) {
    if (!this.needsRetry || !Number.isFinite(now)) return false;
    for (const face of this.quality.failed) {
      this.faces.delete(face);
      this.gyroMeans.delete(face);
    }
    this.active = {started:now, last:null};
    this.detecting('Hold each highlighted face square and still.');
    return true;
  }

  start(now, offsets) {
    if (this.active || !Number.isFinite(now) || !Array.isArray(offsets) || offsets.length !== 3 ||
        !offsets.every(v => Number.isFinite(v) && Math.abs(v) <= .5)) return false;
    this.clear();
    this.baseline = Object.freeze([...offsets]);
    this.active = {started: now, last: null};
    this.detecting('Rest the kit on any unfinished face.');
    return true;
  }
  detecting(note, detected = null) {
    this.window = null;
    this.detected = detected;
    this.phase = 'detecting';
    this.note = note;
  }
  stop(note = 'Calibration stopped.') {
    if (this.active) this.end('stopped', note);
  }
  end(phase, note) {
    this.active = null;
    this.window = null;
    this.detected = null;
    this.phase = phase;
    this.note = note;
  }
  sample(values, at) {
    if (!this.active) return;
    if (!Number.isFinite(at) || !Array.isArray(values) || values.length < 6 ||
        !values.slice(0, 6).every(Number.isFinite)) {
      this.end('error', 'Invalid IMU sample. Check the link and restart calibration.');
      return;
    }
    const {started, last} = this.active;
    if (at < started || (last !== null && at <= last)) return;
    if (at - (last ?? started) > MAX_GAP_MS) {
      this.end('stopped', 'IMU signal interrupted. Restart when readings are live.');
      return;
    }
    this.active.last = at;
    const rates = values.slice(0, 3), acc = values.slice(3, 6);
    const raw = acc.map((v, i) => v - this.baseline[i]);
    if (maximumAbs(rates) > 5) {
      this.detecting('Movement detected. Hold the kit still.');
      return;
    }
    const face = detectPose(acc, raw);
    if (face < 0) {
      this.detecting('Rest the kit squarely on one face.');
      return;
    }
    if (this.faces.has(face)) {
      this.detecting('Already captured. Move to an unfinished face.', face);
      return;
    }
    // The first fit provides a bias estimate for alignment guidance only.
    // On a retry, catch a tilted face before committing another three-second hold.
    if (this.quality?.failed.includes(face)) {
      const axis = poses[face][1];
      const cross = Math.hypot(...raw.map((v,i) => i === axis ? 0 : v + this.quality.biasCorrection[i]));
      if (cross > FIT_ERROR_LIMIT) {
        this.detecting('Square this face to gravity. Off-axis reading '+cross.toFixed(3)+' g.', face);
        return;
      }
    }
    if (this.window?.face !== face) this.window = new StationaryWindow(face, at);
    this.detected = face;
    this.phase = 'holding';
    this.note = 'Keep the kit still.';
    const window = this.window;
    window.add([...rates, ...raw], at);
    if (window.varied) {
      this.detecting('Readings varied. Steady the kit and hold again.', face);
      return;
    }
    if (window.progress < 1) return;
    const gyro = window.mean.slice(0, 3);
    if (maximumAbs(gyro) > GYRO_RESIDUAL_LIMIT) {
      this.detecting('Gyro movement is too high. Keep still. If it persists, restart the kit level.', face);
      return;
    }
    this.faces.set(face, Object.freeze(window.mean.slice(3)));
    this.gyroMeans.set(face, gyro);
    if (this.faces.size === poses.length) this.finish();
    else this.detecting('Face captured. Move to an unfinished face.', face);
  }
  finish() {
    const offsets = AXES.map(axis => {
      const raw = sign => this.faces.get(poses.findIndex(([, i, s]) => i === axis && s === sign))[axis];
      return -(raw(1) + raw(-1)) / 2;
    });
    // Validate the readings the kit can actually produce after saving. Its
    // schema does not store scale or alignment, so neither enters this fit.
    const residuals = poses.map(([, axis, sign], face) =>
      this.faces.get(face).map((raw, i) => raw + offsets[i] - (i === axis ? sign : 0)));
    const axisErrors = AXES.map(i => Math.max(...residuals.map(v => Math.abs(v[i]))));
    const faceErrors = residuals.map(v => Math.hypot(...v));
    const maxError = Math.max(...faceErrors);
    const failed = faceErrors.flatMap((error, face) => error > FIT_ERROR_LIMIT ? [face] : []);
    const gyros = [...this.gyroMeans.values()];
    const gyroPeak = Math.max(...gyros.map(maximumAbs));
    this.gyro = Object.freeze(AXES.map(i => gyros.reduce((sum, g) => sum + g[i], 0) / gyros.length));
    this.quality = Object.freeze({axisErrors:Object.freeze(axisErrors), maxError, gyroPeak,
      faceErrors:Object.freeze(faceErrors), failed:Object.freeze(failed), biasCorrection:Object.freeze(offsets)});
    if (maximumAbs(offsets) > .5) {
      this.end('error', 'Offset exceeds the kit range (±0.5 g). Check the sensor and repeat.');
      return;
    }
    if (failed.length) {
      const worst = faceErrors.indexOf(maxError);
      let note = poses[worst][0]+' measured '+maxError.toFixed(3)+' g error. Limit '+FIT_ERROR_LIMIT.toFixed(2)+' g.';
      for (const axis of AXES) {
        const plus = poses.findIndex(([,i,s]) => i === axis && s === 1);
        const minus = poses.findIndex(([,i,s]) => i === axis && s === -1);
        const gain = (this.faces.get(plus)[axis] - this.faces.get(minus)[axis]) / 2;
        if (Math.abs(gain-1) > FIT_ERROR_LIMIT) {
          note += ' '+['X','Y','Z'][axis]+' measures ±'+gain.toFixed(3)+' g across its two faces. Check the sensor scale if this repeats.';
          break;
        }
      }
      this.end('review', note);
      return;
    }
    this.offsets = Object.freeze(offsets);
    this.end('complete', 'Six faces captured and gyro checked. Ready to save.');
  }
}
