import {pulseForAxis} from './stick-geometry.js';
// Channels use the accepted FC order from the Python transmitter.
export const NEUTRAL = Object.freeze([1500,1500,1000,1500,1000,1000,1000,1000]);
export const DEFAULT_KEYS = Object.freeze(['Left','Right','Down','Up','S','W','A','D','1','2','3','4','5','6','7','8']);
export const KEY_OPTIONS = ['Left','Right','Down','Up',...'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'];
export const SOURCES = ['PPM','AP','USB'];
export const MODE_NAMES = ['ANGLE','RATE / ACRO'];
export const clamp = (n,low,high)=>Math.max(low,Math.min(high,n));

export function validKeys(keys) {
  return Array.isArray(keys) && keys.length===16 && new Set(keys).size===16 && keys.every(k=>KEY_OPTIONS.includes(k));
}
export function switchPulse(settings,mode) {
  if(!settings || settings[0]<5 || settings[0]>8 || settings[4]===settings[5])return null;
  if(settings[4]===mode)return 1000;
  if(settings[5]===mode)return 2000;
  return null;
}
export function currentGuard(ctx,now) {
  if(!ctx || ctx.replay || ctx.state!=='connected' || !ctx.link?.session)return {};
  const read=(id,age)=>ctx.model.get(id,now,age);
  const setup=read(130,500), status=read(120,500), input=read(122,500);
  const source=ctx.path==='AP'?1:ctx.path==='USB'?2:null;
  const route=source!==null && input?.[0]===source && input[7]===ctx.link.session;
  const timeout=read(112,Infinity)?.[1]??250;
  const ready=Boolean(route&&input[1]===source+1&&input[source===1?3:8]&&input[4]&&input[5]===8&&input[6]<timeout);
  const lockClear=setup?.[1]===true&&setup[0]===false&&!setup[8];
  const receipt=read(136,500);
  const pidSaved=receipt?.[0]===false && Number.isInteger(receipt[1]) && receipt[1]===receipt[2] && receipt[3]==='';
  return {setup,status,input,source,route,ready,timeout,lockClear,pidSaved,canStart:Boolean(route&&lockClear&&status?.[0]===false)};
}
// The receiver selection and the transport used to view telemetry are independent.
export function transmitterView(ctx,guard,selected) {
  if(ctx?.replay)return 'replay';
  if(ctx?.state!=='connected')return 'preview';
  if(selected===0)return 'ppm';
  if(!guard.input||![1,2].includes(selected))return 'waiting';
  return guard.route?'local':'monitor';
}
export class CockpitSender {
  constructor(controls,getContext,onStop) {
    this.controls=controls;this.getContext=getContext;this.onStop=onStop;
    this.running=false;this.ready=false;this.arming=false;this.timer=null;this.abort=null;
  }
  start(now=performance.now()) {
    const ctx=this.getContext(),guard=currentGuard(ctx,now);
    if(this.running||!guard.canStart)throw Error('Select this link as flight input and complete setup on the disarmed kit.');
    this.controls.reset();
    this.abort=new AbortController();this.running=true;this.ready=false;this.everArmed=false;
    this.link=ctx.link;this.owner=ctx.link.session;this.model=ctx.model;this.started=now;this.previous=now;
    this.firstSent=this.lastSent=null;
    this.rateSince=now;this.sent=0;this.rate=0;
    this.timer=setInterval(()=>this.tick(performance.now()),20);
    this.tick(now);
  }
  tick(now) {
    if(!this.running)return;
    const c=this.getContext(),g=currentGuard(c,now);
    try {
      if(c?.link!==this.link||c?.link.session!==this.owner||c?.model!==this.model||!g.route||!g.lockClear||!g.status)
        throw Error('Control link or setup state changed.');
      if(this.everArmed&&!g.status[0])throw Error('FC disarmed.');
      this.everArmed||=g.status[0];
      const ap=g.source===1, timeout=ap?g.timeout:150;
      const gap=now-this.previous>=timeout || now-(this.lastSent??this.started)>=timeout;
      this.previous=now;
      if(ap&&!this.everArmed&&!this.arming){
        // A disarmed FC accepts neutral frames to qualify the selected input again.
        if(this.ready&&(gap||!g.ready)){
          this.controls.reset();this.ready=false;this.started=now;this.firstSent=this.lastSent=null;
        }
      }else if(gap)throw Error('Channel sender timed out.');
      if(!this.ready){
        if(!ap&&now-this.started>1000)throw Error('FC did not confirm neutral input.');
        const row=c.model.frames.get(122);
        if(this.firstSent!==null && row?.at>this.firstSent && now-row.at<(ap?timeout:250)
           && (ap||now-this.started>=250) && g.ready)this.ready=true;
      }else if(!g.ready)throw Error('Receiver no longer ready.');
      const signal=this.abort.signal;
      this.link.sendControl(this.ready?this.controls.values:NEUTRAL,()=>{
        if(signal.aborted||now<this.started)return;
        this.firstSent??=now;this.lastSent=now;this.sent++;
      });
      if(now-this.rateSince>=1000){this.rate=this.sent*1000/(now-this.rateSince);this.sent=0;this.rateSince=now;}
    }catch(e){this.stop();this.onStop(e.message);}
  }
  canArm(now) {
    if(!this.running||!this.ready||this.arming)return false;
    const c=this.getContext(),g=currentGuard(c,now),v=this.controls.values;
    return c?.link===this.link&&c?.link.session===this.owner&&g.canStart&&g.ready&&g.pidSaved&&g.status[7]===true&&
      c.model.get(122,now,250)&&v[2]<(c.model.get(4,now,Infinity)?.[0]??1050)&&[0,1,3].every(i=>v[i]>=1400&&v[i]<=1600);
  }
  async arm() {
    if(!this.canArm(performance.now()))throw Error('ARM requires verified setup, saved PID, low throttle and centered sticks.');
    const link=this.link,signal=this.abort.signal;
    this.arming=true;
    try{
      const setup=await link.readGroup(130);
      this.arming=false;
      if(signal.aborted||!this.canArm(performance.now())||setup[0]||!setup[1])throw Error('ARM cancelled.');
      this.arming=true;
      const ack=await link.action(123,['ARM'],{signal});
      if(signal.aborted)return;
      if(ack?.[0]!=='ARMED'||(await link.readGroup(120))[0]!==true)throw Error('FC did not confirm ARMED.');
    }finally{if(!signal.aborted)this.arming=false;}
  }
  stop(){
    const active=this.running;this.abort?.abort();clearInterval(this.timer);this.timer=null;
    this.running=false;this.arming=false;this.ready=false;this.controls.reset();return active;
  }
}
export class Controls {
  constructor(keys=DEFAULT_KEYS){this.keys=validKeys(keys)?[...keys]:[...DEFAULT_KEYS];this.reset();}
  reset(){this.values=[...NEUTRAL];this.held=[false,false];this.pressed=new Set();}
  stick(left,x,y,held){
    this.held[left?0:1]=held;
    if(left){this.values[3]=held?pulseForAxis(x):1500;if(held)this.values[2]=pulseForAxis(y);}
    else {this.values[0]=held?pulseForAxis(x):1500;this.values[1]=held?pulseForAxis(y):1500;}
  }
  key(key,down){
    const index=this.keys.indexOf(key);
    if(index<0)return false;
    if(!down){this.pressed.delete(key);return true;}
    this.pressed.add(key);
    if(index>=8)this.values[Math.floor(index/2)]=index%2?2000:1000;
    return true;
  }
  step(dt){
    for(let ch=0;ch<4;ch++){
      if(this.held[ch<2?1:0])continue;
      const dir=Number(this.pressed.has(this.keys[ch*2+1]))-Number(this.pressed.has(this.keys[ch*2]));
      if(ch===2)this.values[ch]=clamp(Math.round(this.values[ch]+500*Math.min(dt,.05)*dir),1000,2000);
      else this.values[ch]=1500+500*dir;
    }
  }
}
