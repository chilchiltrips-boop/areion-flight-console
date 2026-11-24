import assert from 'node:assert/strict';
import test from 'node:test';
import {createHash} from 'node:crypto';
import {flashAp} from '../web/firmware-ota.js';
import {encodeCommand,matchesAck} from '../web/protocol.js';
import {defaults,receiverValues,throttleWindow} from '../web/config-commands.js';

function kit(size=1279) {
  const data=Uint8Array.from({length:size},(_,i)=>i%251),sha256=createHash('sha256').update(data).digest('hex');
  const chunks=[],commands=[];
  const link={session:42,fcSession:17,current:{},state:'connected',async action(group,values){
    assert.equal(group,140);commands.push(values[0]);const wire=encodeCommand('ACTION',group,42,commands.length,values);
    assert.ok(wire.byteLength<=1552);
    let reply;
    if(values[0]==='BEGIN'){assert.deepEqual(values.slice(1),[size,sha256]);reply='OTA_READY';}
    if(values[0]==='DATA'){
      const bytes=Buffer.from(values.slice(2).join(''),'hex');
      assert.equal(Buffer.concat(chunks).length,values[1]);chunks.push(bytes);reply='OTA_OFFSET_'+Buffer.concat(chunks).length;
    }
    if(values[0]==='FINISH'){assert.deepEqual(Buffer.concat(chunks),Buffer.from(data));reply='OTA_RESTART';}
    if(values[0]==='ABORT')reply='OTA_ABORTED';
    assert.ok(matchesAck({type:'ACTION',group,values},{type:'ACK',data:[reply]}));
    return [reply];
  }};
  return {link,commands,release:{version:'3.4.0',images:{application:{data,sha256}}}};
}
test('AP uploads the application in bounded offset-acknowledged chunks, including the tail',async()=>{
  for(const size of [512,1024,1279]){
    const {link,release,commands}=kit(size),progress=[];
    assert.deepEqual(await flashAp(link,release,p=>progress.push(p)),{reset:true,version:'3.4.0'});
    assert.equal(commands.filter(c=>c==='DATA').length,Math.ceil(size/512));assert.equal(commands.at(-1),'FINISH');
    assert.equal(progress.at(-1),99);
  }
});
test('AP stops at the first refused or unacknowledged chunk and never finalizes on another boot',async()=>{
  for(const fault of ['offset','deny','boot']){
    const {link,release,commands}=kit(),action=link.action;
    link.action=async(group,values)=>{
      const reply=await action(group,values);
      if(fault==='deny'&&values[0]==='BEGIN')throw Object.assign(Error('OTA_HOLD_BOOT'),{code:'OTA_HOLD_BOOT'});
      if(values[0]==='DATA'){if(fault==='boot')link.fcSession++;else return ['OTA_OFFSET_1'];}
      return reply;
    };
    await assert.rejects(flashAp(link,release),fault==='deny'?/Hold BOOT/:/confirm/);
    assert.ok(!commands.includes('FINISH'));assert.equal(commands.includes('ABORT'),fault==='offset');
  }
});
test('AP rejects malformed upload controls, oversized chunks and wrong ACK offsets',()=>{
  for(const values of [['BEGIN',40,'wrong'],['BEGIN',2000000,'0'.repeat(64)],['DATA',3,'aa'.repeat(65)],['DATA',0,'aa','z'],['DATA',0],['FINISH',1]]){
    assert.throws(()=>encodeCommand('ACTION',140,1,1,values));
  }
  assert.ok(!matchesAck({type:'ACTION',group:140,values:['DATA',10,'00']},{type:'ACK',data:['OTA_OFFSET_12']}));
});
test('PPM save and its live target agree at the exact FC limit for measured and reversed throttle',()=>{
  const capture={count:4,samples:20,first:0,last:2400,min:[1008,1008,1008,1008],max:[1993,1993,1993,1993]};
  const raw=[1500,1500,1169,1500,0,0,0,0,4,true,0],map=[1,2,3,4],cal=[...defaults[132]];
  for(const pulse of [1169,1155,1058]){raw[2]=pulse;assert.throws(()=>receiverValues(capture,raw,cal,map,1050),/target ≤ 1057/);}
  raw[2]=1057;assert.ok(receiverValues(capture,raw,cal,map,1050));
  raw[2]=1008;assert.ok(throttleWindow(capture,raw,cal,3,1050).ready);
  const swapped=[1,3,2,4];cal[7]=1;raw[2]=1500;raw[1]=1894;
  assert.throws(()=>receiverValues(capture,raw,cal,swapped,1100),/CH2.*target ≥ 1895/);
  raw[1]=1895;assert.ok(receiverValues(capture,raw,cal,swapped,1100));
  raw[9]=false;assert.equal(throttleWindow(capture,raw,cal,2,1100),null);
});
