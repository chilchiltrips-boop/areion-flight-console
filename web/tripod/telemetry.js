import {unpackGains} from './gains.js';
import {defaults} from '../config-commands.js';

// A snapshot contains values only. The simulator never receives a transport or command callback.
export function tripodSession(ctx) {
  return ctx?.state === 'connected' && !ctx.replay && ctx.link?.session && ctx.link.fcSession ?
    [ctx.path, ctx.link.session, ctx.link.fcSession].join('/') : null;
}
export function tripodTelemetry(ctx, at) {
  const session = tripodSession(ctx);
  if (!session) return null;
  const model=ctx.model, clock=at??ctx.clock;
  const snapshot=at===undefined?ctx.snapshot:model.snapshot(clock);
  const group=(id,maxAge=Infinity)=>model.get(id,clock,maxAge);
  const status = group(120, 500), setup = group(130, 500);
  const imu = snapshot.imu, rates = imu && group(21, 500)?.slice(0, 3);
  const control = group(23, 500);
  const mode = status ? (status[1] ? 'angle' : 'acro') : null;
  const receiver = model.frames.get(122), channelFrame = model.frames.get(22);
  const source = snapshot.source;
  const timeout = group(112)?.[source === 'PPM' ? 0 : 1] ?? 250;
  const channels = snapshot.channels?.slice(0, 4);
  const goodInput = snapshot.input?.level === 'good' && channels?.length === 4 &&
    channels.every(v => Number.isFinite(v) && v >= 900 && v <= 2100) && receiver && channelFrame;
  const inputUntil = goodInput ? Math.min(receiver.at + timeout - receiver.values[6], channelFrame.at + 500) : 0;
  return {
    session, path: ctx.path, kit: group(130)?.[15], armed: status?.[0], mode,
    flight: group(7)??defaults[7], arming: group(4)??defaults[4], setup: group(134)??defaults[134],
    gains: unpackGains(group(2), group(3)), input: goodInput && clock < inputUntil ? {
      source, channels, until: inputUntil, identity: [session,source,source==='PPM'?0:receiver.values[7]].join('/')
    } : null,
    attitude: imu ? {roll: imu.roll, pitch: imu.pitch, yaw: imu.yaw} : null, rates,
    motors: snapshot.motor, inputName: source, setupLocked: setup?.[0],
    targets: imu && status?.[4] > 0 && setup?.[0] === false && control ? {
      rate: control.slice(7, 10), angle: mode === 'angle' ? control.slice(10, 12) : null
    } : null
  };
}

// Keep original packet timestamps and groups so a bench capture opens in the normal CSV player.
export class TripodRecording {
  rows = [];
  session = null;
  end = 0;
  message = '';
  start(ctx, kit) {
    if (!kit?.attitude || !kit.rates || !ctx || this.session) return false;
    this.session = kit.session;
    this.startAt = ctx.clock;
    this.end = this.startAt + 10000;
    this.rows = [...ctx.frames.values()]
      .filter(row => row.at <= ctx.clock && ctx.clock - row.at <= 500)
      .sort((a, b) => a.at - b.at);
    this.message = 'Recording';
    return true;
  }
  packet(row, session) {
    if (!this.session) return;
    if (session !== this.session) { this.stop('Kit changed'); return; }
    if (row.at > this.end) { this.stop('Capture complete'); return; }
    if (row.at >= this.startAt && row.at >= (this.rows.at(-1)?.at ?? 0)) this.rows.push(row);
  }
  update(clock, kit) {
    if (!this.session) return;
    if (kit?.session !== this.session || !kit.attitude) this.stop('Telemetry interrupted');
    else if (clock >= this.end) this.stop('Capture complete');
  }
  stop(reason = 'Capture stopped') {
    if (!this.session) return;
    this.session = null;
    this.message = reason;
  }
}
