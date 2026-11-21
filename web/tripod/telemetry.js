import {unpackGains} from './gains.js';
import {defaults} from '../config-commands.js';

// A snapshot contains values only. The simulator never receives a transport or command callback.
export function tripodSession(ctx) {
  return ctx?.state === 'connected' && !ctx.replay && ctx.link?.session && ctx.link.fcSession ?
    [ctx.path, ctx.link.session, ctx.link.fcSession].join('/') : null;
}
// Group 131 may also carry a physical radio while another input owns the FC.
function rawPpmInput(model, clock, session, flight, setup, endpoints, timeout) {
  const frame=model.frames.get(131),raw=model.get(131,clock,500);
  if(!raw?.[9] || !Number.isInteger(raw[8]) || raw[8]<4 || raw[8]>8 ||
     !Number.isFinite(raw[10]) || raw[10]<0 || !setup || !endpoints) return null;
  const until=Math.min(frame.at+timeout-raw[10],frame.at+500);
  const mapping=setup.slice(2,6),deadband=setup[6];
  if(clock>=until || new Set(mapping).size!==4 || !Number.isFinite(deadband))return null;
  const channels=[];
  for(const [axis,channel] of mapping.entries()){
    if(!Number.isInteger(channel)||channel<1||channel>raw[8])return null;
    const value=raw[channel-1],i=(channel-1)*4;
    const [low,mid,high,reverse]=endpoints.slice(i,i+4);
    if(!Number.isFinite(value)||value<900||value>2100||!(low<mid&&mid<high)||![0,1].includes(reverse))return null;
    const throttle=axis===2;
    const pulse=throttle?1000+(value-low)*1000/(high-low):
      1500+(value-mid)*500/(value<mid?mid-low:high-mid);
    const bounded=Math.min(2000,Math.max(1000,pulse));
    channels.push(!throttle&&Math.abs(value-mid)<=deadband?1500:reverse?3000-bounded:bounded);
  }
  const switchChannel=flight?.[0],switchValue=raw[switchChannel-1];
  const choice=Number.isInteger(switchChannel)&&switchChannel>=1&&switchChannel<=raw[8]&&
    switchValue>=900&&switchValue<=2100?flight[switchValue<1500?4:5]:null;
  return {source:'PPM',channels,until,identity:session+'/PPM/0',mode:choice===0?'angle':choice===1?'acro':null};
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
  const source = snapshot.source, flight=group(7), config=group(134), ppmTimeout=group(112)?.[0]??250;
  const timeout = group(112)?.[source === 'PPM' ? 0 : 1] ?? 250;
  const channels = snapshot.channels?.slice(0, 4);
  const goodInput = snapshot.input?.level === 'good' && channels?.length === 4 &&
    channels.every(v => Number.isFinite(v) && v >= 900 && v <= 2100) && receiver && channelFrame;
  const inputUntil = goodInput ? Math.min(receiver.at + timeout - receiver.values[6], channelFrame.at + 500) : 0;
  return {
    session, path: ctx.path, kit: group(130)?.[15], armed: status?.[0], mode,
    flight: flight??defaults[7], arming: group(4)??defaults[4], setup: config??defaults[134],
    rawPpm: source==='PPM' && !receiver?.values[2] ? null : rawPpmInput(model,clock,session,flight,config,group(132),ppmTimeout),
    gains: unpackGains(group(2), group(3)), input: goodInput && clock < inputUntil ? {
      source, channels, mode, until: inputUntil, identity: [session,source,source==='PPM'?0:receiver.values[7]].join('/')
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
