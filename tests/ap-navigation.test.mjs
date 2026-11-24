import test from 'node:test';
import assert from 'node:assert/strict';
import {Worker} from 'node:worker_threads';
import {setTimeout as delay} from 'node:timers/promises';
import {ApSessionPort} from '../web/ap-session-port.js';
import {UsbTelemetry} from '../web/usb.js';
import {CockpitSender,Controls} from '../web/cockpit-controls.js';
import {Instruments} from '../web/instruments.js';

function fixture(options) {
  const history=[];
  const native=new Worker(new URL('./fixtures/ap-worker-kit.mjs',import.meta.url),{workerData:options});
  const bridge={postMessage:msg=>native.postMessage(msg),terminate:()=>native.terminate()};
  native.on('message',msg=>msg.audit ? history.push(msg) : bridge.onmessage?.({data:msg}));
  native.on('error',error=>bridge.onerror?.(error));
  return {port:new ApSessionPort(undefined,()=>bridge),native,history};
}

async function until(check) {
  const start=performance.now();
  while(!check()){
    if(performance.now()-start>3500)throw Error('Timed out waiting for kit');
    await delay(10);
  }
}

test('AP keeps the same session through a stalled page, uses fresh timestamps and records a real disconnect',async t=>{
  const {port,native,history}=fixture();let page='welcome';
  const rows=[],states=[];
  const link=new UsbTelemetry({route:()=>page,onData:row=>rows.push(row),onStatus:s=>states.push(s.state)});
  t.after(async()=>{await link.disconnect();await native.terminate();});
  await link.connect(port,{source:1});
  await until(()=>link.state==='connected' && rows.some(r=>r.group===22));
  const host=link.session,fc=link.fcSession;
  for(const name of ['assembly','scopes']){
    page=name;
    const start=performance.now(), before=rows.length;
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,580);
    const end=performance.now();
    await until(()=>rows.length>before);
    assert.ok(history.filter(e=>e.audit==='poll' && e.time>=start && e.time<=end).length>=3);
    assert.ok(rows.slice(before).every(r=>end-r.at<=201),'stale pre-stall telemetry was discarded');
    assert.deepEqual(await link.readGroup(110),[1]);
    assert.equal(link.session,host);assert.equal(link.fcSession,fc);
  }
  assert.deepEqual(states,['opening','handshake','connected']);
  assert.equal(history.filter(e=>e.audit==='socket').length,1);
  assert.equal(history.filter(e=>e.command==='HELLO').length,1);
  assert.ok(!history.some(e=>['ACTION','CONTROL'].includes(e.command)));
  native.postMessage({test:'radio-loss'});
  await until(()=>link.state==='error');
  assert.match(link.message,/WebSocket closed \(code 1006\)/);
  assert.equal(link.lastConnection.page,'scopes');assert.equal(link.lastConnection.host_session,host);
  assert.equal(link.lastConnection.fc_session,fc);assert.ok(link.lastConnection.rx>0);
  assert.equal(link.fcSession,null);assert.equal(link.session,null);
});

test('a command delayed in transit to the AP worker expires even with a new gateway ticket',async t=>{
  const {port,native,history}=fixture();t.after(()=>native.terminate());
  await port.open();
  const writer=port.writable.getWriter();
  await assert.rejects(writer.write({bytes:new Uint8Array([36,10]),issuedAt:performance.timeOrigin+performance.now()-500}),/expired/);
  assert.ok(!history.some(e=>e.audit==='request'));await port.close();
});

test('a temporarily expired operator write rejects just that operation and allows fresh reads on the same session',async t=>{
  const {port,native,history}=fixture();const link=new UsbTelemetry();
  t.after(async()=>{await link.disconnect();await native.terminate();});
  await link.connect(port,{source:1});await until(()=>link.state==='connected');
  const host=link.session,fc=link.fcSession,writeFresh=port.writeFresh.bind(port);
  let expire=true;
  port.writeFresh=frame=>{
    if(expire){expire=false;return writeFresh({...frame,issuedAt:frame.issuedAt-500});}
    return writeFresh(frame);
  };
  await assert.rejects(link.action(135,['SENSOR_OK',1,0,0,0]),{code:'AP_FRAME_DROPPED'});
  assert.equal(link.session,host);assert.equal(link.fcSession,fc);
  assert.deepEqual(await link.readGroup(110),[1]);
  assert.ok(!history.some(row=>row.command==='ACTION'));assert.equal(history.filter(row=>row.audit==='socket').length,1);
  assert.ok(port.timing.dropped_writes>=1);
});

test('explicit AP disconnect releases ownership and stops polling without reconnecting',async t=>{
  const {port,native,history}=fixture();t.after(()=>native.terminate());
  const link=new UsbTelemetry();await link.connect(port,{source:1});
  await until(()=>link.state==='connected');await link.disconnect();
  assert.equal(history.filter(e=>e.audit==='request').at(-1).command,'RELEASE');
  assert.equal(port.worker,null);assert.equal(link.state,'offline');
});

test('Flight Data starts on AP, survives dropped joystick samples and receives the next stick position over Link v2',async t=>{
  const {port,native,history}=fixture({flight:true}),model=new Instruments(),states=[],results=[],stops=[];
  const link=new UsbTelemetry({onStatus:s=>states.push(s.state),onData:r=>model.push(r),onResult:r=>results.push(r)});
  const controls=new Controls(),ctx={path:'AP',model,link,get state(){return link.state;}};
  const sender=new CockpitSender(controls,()=>ctx,reason=>stops.push(reason));
  t.after(async()=>{sender.stop();await link.disconnect();await native.terminate();});
  await link.connect(port,{source:1});await until(()=>model.frames.has(122)&&model.frames.has(130));
  const owner=link.session,write=port.writeFresh.bind(port),decoder=new TextDecoder();
  let count=0,skipRoll=0;
  port.writeFresh=frame=>{
    if(decoder.decode(frame.bytes).includes('"type":"CONTROL"') && (count++<2 || skipRoll && controls.values[0]===skipRoll))
      return write({...frame,issuedAt:frame.issuedAt-500});
    return write(frame);
  };
  sender.start();await until(()=>sender.ready);
  skipRoll=1900;controls.stick(false,.8,0,true);
  await until(()=>results.some(r=>r.status==='dropped'&&r.values?.[0]===1900));
  controls.stick(false,.4,-.25,true);
  native.postMessage({test:'delay-poll',ms:187});
  await until(()=>port.timing?.max_rtt_ms>=175 || port.timing?.poll_retries>0);
  await until(()=>model.frames.get(22)?.values[0]===1700 && sender.rate>0);
  assert.deepEqual(model.frames.get(22).values.slice(0,4),[1700,1375,1000,1500]);
  assert.ok(sender.running&&sender.ready);assert.deepEqual(stops,[]);assert.equal(link.session,owner);
  assert.deepEqual(states,['opening','handshake','connected']);
  assert.ok(results.some(r=>r.kind==='control'&&r.status==='sent'&&r.values[0]===1700));
  assert.ok(!history.some(r=>r.command==='ACTION'||r.channels?.[0]===1900));
  assert.equal(history.filter(r=>r.command==='HELLO').length,1);
});

test('cancelling while the gateway is opening also settles the connect operation',async t=>{
  const {port,native}=fixture();t.after(()=>native.terminate());
  const link=new UsbTelemetry();
  const opening=link.connect(port,{source:1});
  await link.disconnect();await opening;
  assert.equal(port.worker,null);assert.equal(link.session,null);assert.equal(link.state,'offline');
});

test('recovering telemetry verifies the same FC boot and physical kit before exposing a new session',async t=>{
  const {port,native,history}=fixture(),states=[];
  const link=new UsbTelemetry({onStatus:s=>states.push(s.state)});t.after(async()=>{await link.disconnect();await native.terminate();});
  await link.connect(port,{source:1,expected:{boot:8451,kit:'A1_TEST'}});
  await until(()=>link.state==='connected');
  assert.equal(link.fcSession,8451);assert.deepEqual(states,['opening','handshake','connected']);
  assert.deepEqual(history.filter(x=>x.command).slice(0,2).map(x=>x.command),['HELLO','READ']);
  assert.ok(!history.some(x=>x.command==='ACTION'||x.command==='CONTROL'));
});
test('recovery fails closed for a different boot or kit without resending commands',async t=>{
  for(const expected of [{boot:99,kit:'A1_TEST'},{boot:8451,kit:'OTHER'}]){
    const {port,native,history}=fixture(),states=[];
    const link=new UsbTelemetry({onStatus:s=>states.push(s.state)});t.after(()=>native.terminate());
    await link.connect(port,{source:1,expected});await until(()=>link.state==='error');
    assert.ok(!states.includes('connected'));assert.equal(link.session,null);
    assert.match(link.message,/changed/);assert.ok(!history.some(x=>x.command==='ACTION'||x.command==='CONTROL'));
  }
});
