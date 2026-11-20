// Areion Link v2 setup operations. Only addressed controller readbacks confirm a save.
import {schemaFor,validGroup} from './protocol.js';

export const defaults={
  2:[.9,.9,3,15,15,15,.03,.03,0],3:[3,3,0,0,0,0],4:[1050,1900,1100,20,5,1,15],
  6:[-.10,.03,.12],7:[5,.1,.15,.15,0,1],112:[250,250],
  132:Array.from({length:8},()=>[1000,1500,2000,0]).flat(),134:[0,0,1,2,3,4,5,1180,1180,1180,1180]
};
const ids=[134,132,2,3,4,6,7,112];
function requireThat(ok,reason){if(!ok)throw new Error(reason);}
export const equal=(a,b)=>Array.isArray(a)&&Array.isArray(b)&&a.length===b.length&&a.every((v,i)=>
  typeof v==='number'&&typeof b[i]==='number'?Math.abs(v-b[i])<=Math.max(1e-6,Math.abs(v)*1e-6):v===b[i]);
const checkValue=(g,v)=>requireThat(validGroup(g,schemaFor(g),v),'Invalid values for group '+g+'.');
const checkedLock=s=>s[0]&&!s[1]&&s[2]>0;

export class SetupKit {
  constructor(link,guard=()=>{}){
    this.link=link;this.guard=guard;this.session=link?.session;this.boot=link?.fcSession;
  }
  check(){
    this.guard();
    requireThat(this.session && this.session===this.link.session && this.boot===this.link.fcSession,'Kit connection changed. Read the kit again.');
  }
  async call(method,...args){
    this.check();const value=await this.link[method](...args);this.check();return value;
  }
  read(group,saved=false){return this.call('readGroup',group,{saved});}
  async saved(group){
    try{return await this.read(group,true);}catch(error){
      this.check();if(error.code==='NOT_SAVED'||/\bNOT_SAVED\b/.test(error.message))return null;throw error;
    }
  }
  async disarmed(){const s=await this.read(120);requireThat(s[0]===false,'Disarm the controller first.');requireThat(s[7],'Kit storage unavailable.');}
  async locked(){
    await this.disarmed();const s=await this.read(130);requireThat(checkedLock(s),'Begin setup and confirm the kit’s arming lock first.');return s;
  }
  async begin(){
    await this.disarmed();const state=await this.read(130);
    requireThat(!/STORAGE|NVS|PERSIST/i.test(state[14]),'The controller reports a storage fault.');
    if(checkedLock(state))return state; // Resume an already scheduled ESC calibration without cancelling it.
    await this.call('action',135,['BEGIN',1,0,0,0]);
    const active=await this.read(130);await this.disarmed();
    requireThat(checkedLock(active),'The controller did not confirm its arming lock.');return active;
  }
  async store(group,desired,expected=null){
    requireThat(ids.includes(group),'Unsupported setup group.');checkValue(group,desired);
    await this.locked();const active=await this.read(group);
    if(expected)requireThat(equal(active,expected),'Settings changed on the kit. Read the current settings and retry.');
    if(!equal(active,desired)){
      await this.call('setGroup',group,desired);
      requireThat(equal(await this.read(group),desired),'Active readback differs for group '+group+'.');
    }
    const before=await this.saved(group);
    if(!equal(before,desired)){await this.call('saveGroup',group);}
    requireThat(equal(await this.read(group,true),desired)&&equal(await this.read(group),desired),'Saved readback differs for group '+group+'.');
  }
  async checkedAction(name,args,verify){
    await this.locked();await this.call('action',135,[name,...args]);
    const readback=await this.read(130);requireThat(verify(readback),'Controller did not confirm '+name+'.');return readback;
  }
  async sensorState(kit){
    const setup=await this.locked();
    requireThat(setup[15] && (!kit || setup[15]===kit),'Controller identity changed.');
    requireThat(!setup[8] && ![1,2].includes(setup[3]),'Finish the motor or ESC calibration first.');
    return setup;
  }
  async saveSensor(kit,offsets,baseline,retry,onWrite){
    await this.sensorState(kit);
    const active=await this.read(6);
    requireThat(equal(active,baseline) || retry && equal(active,offsets),'Controller offsets changed. Repeat calibration.');
    onWrite();
    await this.store(6,offsets,active);
    // Applying offsets resets MCU attitude until the next valid sensor sample.
    const deadline=performance.now()+1500;
    let status;
    do {
      status=await this.read(120);
      requireThat(status[0]===false && status[7],'Disarm the kit and check storage.');
      if(status[2] && status[5]>0)break;
      if(performance.now()>=deadline)throw Error('Offsets stored. The IMU is still unavailable. Retry verification once healthy.');
      await new Promise(resolve=>setTimeout(resolve,50));
    } while(true);
    await this.sensorState(kit);
    const ack=await this.call('action',135,['SENSOR_OK',1,0,0,0]);
    requireThat(ack?.[0]==='SETUP_UPDATED','Sensor verification was not acknowledged.');
    const after=await this.sensorState(kit);
    requireThat(after[5]===true && equal(await this.read(6,true),offsets) && equal(await this.read(6),offsets),
      'Controller could not verify the saved sensor calibration.');
  }
  async reset(){
    await this.checkedAction('RESET_ALL',[1,0,0,0],s=>checkedLock(s)&&!s[3]&&!s[4]&&!s.slice(5,9).some(Boolean));
    for(const g of ids)requireThat(equal(await this.read(g),defaults[g])&&equal(await this.read(g,true),defaults[g]),'Factory reset could not be verified for group '+g+'.');
  }
  async pid(group,values,bench){
    requireThat(group===2||group===3,'Unknown PID group.');checkValue(group,values);
    const s=await this.read(120);
    requireThat(s[7],'Storage unavailable.');requireThat(!s[0]||bench,'Confirm the secured tuning bench first.');
    const ack=await this.call('action',137,[group,Boolean(bench),...values,...(group===3?[0,0,0]:[])]);
    requireThat(['PID_SAVED','PID_APPLIED_PENDING_SAVE'].includes(ack[0]),'PID apply was not acknowledged.');
    const active=await this.read(group),receipt=await this.read(136);
    const samePid=(a,b)=>a.length===b.length&&a.every((x,i)=>Math.fround(x)===Math.fround(b[i]));
    requireThat(samePid(active,values),'PID active readback differs.');requireThat(!receipt[3],receipt[3]||'PID storage failed.');
    if(receipt[0])return 'Applied to RAM. The kit will save after disarm.';
    requireThat(receipt[1]===receipt[2]&&samePid(await this.read(group,true),values),'Stored PID readback differs.');
    return 'PID saved and verified on the kit.';
  }
  async finalize(){
    const s=await this.locked(),cfg=await this.read(134);
    requireThat(s[5]&&(cfg[1]!==0||s[6])&&[4,5].includes(s[3])&&s[4]===15&&!s[8],'Complete the sensor, receiver (PPM), ESC and four motor checks.');
    const settings={};
    for(const group of ids){
      const active=await this.read(group),saved=await this.saved(group);
      if(saved===null){await this.store(group,active,active);}
      else requireThat(equal(active,saved),'Group '+group+' has unsaved changes. Save it before finishing.');
      settings[group]=active;
    }
    const after=await this.checkedAction('FINALIZE',[0,0,0,0],v=>!v[0]&&v[1]&&!v[8]&&v[15]===s[15]);
    return {kit:after[15],boot:this.boot,settings,setup:after};
  }
  async verifyRestart(receipt){
    requireThat(receipt?.kit,'Save setup to create the restart verification record.');
    const s=await this.read(130);requireThat(s[15]===receipt.kit,'Reconnect the same kit.');
    requireThat(this.boot>0&&receipt.boot>0&&this.boot!==receipt.boot,'Restart the kit, then reconnect.');
    await this.disarmed();
    for(const g of ids)requireThat(equal(await this.read(g),receipt.settings[g])&&equal(await this.read(g,true),receipt.settings[g]),'Stored settings changed since setup in group '+g+'.');
    requireThat((await this.read(110))[0]===receipt.settings[134][1],'Flight input differs from the saved source.');
    const after=await this.read(130);
    requireThat(equal(s,after)&&[0,1,3,4,5,6,7,13].every(i=>after[i]===receipt.setup[i]),'Setup status differs from the saved record.');
  }
}
export async function saveFlightInput(link,source,{wizard=false,guard=()=>{}}={}){
  requireThat([0,1,2].includes(source),'Choose PPM, AP or USB.');
  const op=new SetupKit(link,guard);
  await op.disarmed();const state=await op.read(130);
  if(wizard)requireThat(checkedLock(state),'Begin kit setup before changing the input.');
  const before=await op.read(134),target=[...before];target[1]=source;
  if(state[0]){
    const stored=await op.saved(134);
    if(stored)requireThat(stored.every((v,i)=>i===1||v===target[i]),'Save the other kit settings before changing input.');
  }
  const learn=wizard&&source===0&&!state[6];
  if(learn){
    requireThat(!state[8]&&![1,2].includes(state[3]),'Finish calibration before selecting the receiver.');
    if(equal(target,before)&&(await op.read(110))[0]!==source)await op.call('setGroup',134,target);
    await op.store(134,target,before);
  }else{
    const ack=await op.call('action',135,['INPUT_SAVE',source,0,0,0]);requireThat(ack[0]==='INPUT_SAVED','Input save was not acknowledged.');
  }
  requireThat((await op.read(110))[0]===source&&equal(await op.read(134),target)&&equal(await op.read(134,true),target),'Input save readback differs.');
  const after=await op.read(130);
  requireThat(equal(state.slice(0,2),after.slice(0,2))&&equal(state.slice(3,learn?7:8),after.slice(3,learn?7:8)),'Setup verification changed while saving input.');
  return source;
}

export function receiverValues(capture,raw,baseline,map){
  requireThat(capture&&capture.samples>=10&&capture.last-capture.first>=2000,'Capture at least ten frames over two seconds.');
  requireThat(raw?.[9]&&raw[8]===capture.count&&map.every(c=>c>=1&&c<=raw[8])&&new Set(map).size===4,'Check the receiver and the four channel assignments.');
  const values=baseline.slice(),throttle=map[2]-1;
  for(let i=0;i<capture.count;i++){
    const low=capture.min[i],high=capture.max[i],width=high-low;
    if(width<400){requireThat(!map.includes(i+1),'Move CH'+(i+1)+' fully in both directions.');continue;}
    let center=Math.round((low+high)/2);
    if(i===throttle){
      requireThat(values[4*i+3]?raw[i]>=high-.1*width:raw[i]<=low+.1*width,'Lower the throttle before finishing.');
    }else if(map.includes(i+1)){center=raw[i];}
    requireThat(center-low>=100&&high-center>=100,'Center CH'+(i+1)+' before finishing.');
    values.splice(i*4,3,low,center,high);
  }
  checkValue(132,values);return values;
}
