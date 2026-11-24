import assert from 'node:assert/strict';
import test from 'node:test';
import {crc32} from 'node:zlib';
import {UsbTelemetry} from '../web/usb.js';
import {encodeCommand} from '../web/protocol.js';

const text=new TextDecoder(), bytes=new TextEncoder();
const nextTurn=()=>new Promise(resolve=>setTimeout(resolve,0));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const kit=731;
function response(request,type,data,overrides={}) {
  const body=JSON.stringify({...request,type,data,...overrides});
  const part=bytes.encode(body);
  return bytes.encode('$'+part.length+':'+body+'*'+crc32(part).toString(16).toUpperCase().padStart(8,'0')+'\n');
}
function peer() {
  const port={packets:[],async close(){this.closed=true;},
    async open(){this.readable=new ReadableStream({start:c=>this.incoming=c});
      this.writable=new WritableStream({write:chunk=>{
        const json=text.decode(chunk),request=JSON.parse(json.slice(json.indexOf(':')+1,-10));
        this.packets.push(request);
        if(request.type==='HELLO')this.reply(request,'ACK',['HELLO',kit]);
        if(this.block)return new Promise(r=>this.resume=()=>{this.block=false;r();});
      }});
    },
    reply(packet,type,data,overrides){this.incoming.enqueue(response(packet,type,data,overrides));},
    event(group,values,seq=1){this.reply(this.packets[0],'DATA',values,{group,schema:group===122?2:1,session:kit,seq});}
  };
  return port;
}
async function openAp(onData=()=>{}) {
  const p=peer(),link=new UsbTelemetry({onData});
  await link.connect(p,{source:1,label:'AP Wi-Fi'});
  await nextTurn();
  assert.equal(link.fcSession,kit);
  clearInterval(link.current.timer);
  return {p,link};
}
test('typed mutation frames preserve integer-valued floats and validate group, action and payload',()=>{
  const wire=(...args)=>text.decode(encodeCommand(...args));
  assert.match(wire('SET',7,1,2,[5,.1,1,1,0,1]),/"data":\[5,0.1,1.0,1.0,0,1\]/);
  assert.match(wire('ACTION',137,1,2,[2,false,1,1,3,15,15,15,.03,.03,0]),/false,1.0,1.0,3.0,15.0,15.0,15.0,0.03,0.03,0.0/);
  for(const params of [['SET',120,[]],['SAVE',110,[]],['ACTION',135,['MOTOR_START',{},0,0,0]],['CONTROL',9,Array(8).fill(2001)],
      ['ACTION',137,[3,false,0,0,0,0,0,0,0,0,1]],['READ',122,['saved']]])
    assert.throws(()=>encodeCommand(params[0],params[1],8,1,params[2]));
});
test('saved reads remain isolated, active reads feed instruments, exact ACK and FC errors settle one operation',async()=>{
  const data=[],{p,link}=await openAp(row=>data.push(row));
  try {
    const read=link.readGroup(2,{saved:true});await nextTurn();
    const rq=p.packets.at(-1), gains=[1,1,3,15,15,15,.03,.03,0];
    assert.deepEqual(rq.data,['saved']);
    p.reply(rq,'DATA',gains);assert.deepEqual(await read,gains);assert.deepEqual(data,[]);
    const active=link.readGroup(2);await nextTurn();
    p.reply(p.packets.at(-1),'DATA',gains);assert.deepEqual(await active,gains);assert.deepEqual(data[0].values,gains);
    const save=link.saveGroup(2);await nextTurn();
    const request=p.packets.at(-1);
    p.reply(request,'ACK',['APPLIED_UNSAVED']);p.reply(request,'ACK',['SAVED'],{seq:request.seq-1});
    await nextTurn();assert.equal(link.current.pending.seq,request.seq);
    p.reply(request,'ACK',['SAVED']);assert.deepEqual(await save,['SAVED']);
    const change=link.setGroup(110,[1]);await nextTurn();
    p.reply(p.packets.at(-1),'ERROR',['DISARM_FIRST']);await assert.rejects(change,{code:'DISARM_FIRST'});
    assert(link.stats.sent>=5 && link.stats.received>=5 && link.stats.lastRxAt>0);
  } finally {await link.disconnect();}
});
test('urgent stop supersedes a blocked request and neither stale completion nor reconnect repeats motion',async()=>{
  const {p,link}=await openAp();
  p.block=true;
  const pending=link.action(135,['MOTOR_SET',1,1234,0,0]);const cancelled=assert.rejects(pending,{code:'CANCELLED'});
  await nextTurn();
  const motor=p.packets.at(-1);
  const stop=link.action(135,['MOTOR_STOP',0,0,0,0]);await cancelled;
  p.reply(motor,'ACK',['MOTOR_TEST_UPDATED']);p.resume();await nextTurn();
  const last=p.packets.at(-1);
  assert.equal(last.data[0],'MOTOR_STOP');assert(last.seq>motor.seq);
  p.reply(last,'ACK',['STOPPED']);assert.deepEqual(await stop,['STOPPED']);
  const wait=link.readGroup(120);const rejected=assert.rejects(wait,{code:'OFFLINE'});
  await link.disconnect();await rejected;
  assert.equal(p.packets.at(-1).type,'RELEASE');assert.equal(link.session,null);
  const second=peer();await link.connect(second,{source:1});await nextTurn();
  assert(second.packets.every(r=>r.type==='HELLO'));
  await link.disconnect();
});
test('digital RC enforces owner, transport, setup lock and neutral bootstrap; busy frames do not backlog',async()=>{
  const {p,link}=await openAp(), neutral=[1500,1500,1000,1500,1000,1000,1000,1000],up=[...neutral];up[2]=1400;
  const status=[false,true,true,0,.004,2000,42,true,false,false];
  const setup=[false,true,0,4,15,true,true,false,false,1000,1000,1000,1000,42,'','A1'];
  const input=[1,0,false,false,false,0,80,link.session,false];
  const events=async(seq,rx=input,sc=setup)=>{
    p.event(120,status,seq);p.event(122,rx,seq);p.event(130,sc,seq);
    await nextTurn();
  };
  try {
    assert.throws(()=>link.sendControl(neutral),/Waiting/);
    await events(1,[2,3,false,false,true,8,10,link.session,true]);assert.throws(()=>link.sendControl(neutral),/selected/);
    await events(2,input,[true,...setup.slice(1)]);assert.throws(()=>link.sendControl(neutral),/locked/);
    await events(3);assert.throws(()=>link.sendControl(up),/neutral/);
    await assert.rejects(link.action(123,['ARM']),/neutral/);
    await events(4,[1,2,false,true,true,8,10,link.session,false]);
    p.block=true;assert.equal(link.sendControl(neutral),true);await nextTurn();
    assert.equal(link.sendControl(up),false);
    p.resume();await nextTurn();
    assert.deepEqual(p.packets.filter(r=>r.type==='CONTROL').map(r=>r.data),[neutral]);
    const stop=link.action(123,['DISARM']);await nextTurn();p.reply(p.packets.at(-1),'ACK',['DISARMED']);await stop;
    assert.equal(link.current.neutralSince,null);
  } finally {await link.disconnect();}
});
test('AbortSignal and expired motion intent cannot send an action after the writer recovers',async()=>{
  const {p,link}=await openAp();
  const abort=new AbortController();p.block=true;
  const read=link.readGroup(2,{signal:abort.signal});const readError=assert.rejects(read,{code:'CANCELLED'});await nextTurn();
  abort.abort();await readError;
  const cmd=link.action(135,['MOTOR_START',1,1,0,0]);const expired=assert.rejects(cmd,{code:'EXPIRED'});
  await sleep(170);p.resume();await expired;
  assert(!p.packets.some(r=>r.type==='ACTION'));
  await link.disconnect();
});

test('a stale event stream permits DISARM and fresh status readback; motor cleanup cannot replace DISARM',async()=>{
  const {p,link}=await openAp();
  link.current.lastRx=performance.now()-1400;link.tick(link.current);
  assert.equal(link.state,'stale');
  const disarm=link.action(123,['DISARM']);
  await assert.rejects(link.action(135,['MOTOR_STOP',0,0,0,0]),{code:'STOP_PENDING'});
  await nextTurn();p.reply(p.packets.at(-1),'ACK',['DISARMED']);await disarm;
  const read=link.readGroup(120);await nextTurn();
  p.reply(p.packets.at(-1),'DATA',[false,true,true,8,.004,2000,123,true,false,false]);
  assert.equal((await read)[0],false);link.tick(link.current);assert.equal(link.state,'connected');
  await link.disconnect();
});

test('AP credential reads and writes are USB-only and private status never enters recorded telemetry',async()=>{
  const logged=[],{p,link}=await openAp(row=>logged.push(row));
  try {
    await assert.rejects(link.action(138,['RECOVER_AP','local-unit-test-key']),{code:'USB_REQUIRED'});
    await assert.rejects(link.readGroup(139),{code:'USB_REQUIRED'});
    assert.ok(!p.packets.some(packet=>packet.group===138 || packet.group===139));
    link.current.source=2;
    const operation=link.action(138,['SET_AP','Lab A','local-unit-test-key']);
    await nextTurn();p.reply(p.packets.at(-1),'ACK',['AP_SAVED']);await operation;
    const info=link.readGroup(139);await nextTurn();
    const status=['Previous lab','Lab A',true,true];p.reply(p.packets.at(-1),'DATA',status);
    assert.deepEqual(await info,status);p.event(139,status);await nextTurn();
    assert.ok(!logged.some(r=>r.group===139));
    link.firmwareMaintenance=true;
    await assert.rejects(link.action(138,['RECOVER_AP','local-unit-test-key']),{code:'FLASH_BUSY'});
    assert.throws(()=>link.sendControl([]),{code:'FLASH_BUSY'});
  } finally {await link.disconnect();}
});
