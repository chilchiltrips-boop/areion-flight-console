import test from 'node:test';
import assert from 'node:assert/strict';
import {Worker} from 'node:worker_threads';
import {setTimeout as delay} from 'node:timers/promises';
import {ApSessionPort} from '../web/ap-session-port.js';
import {UsbTelemetry} from '../web/usb.js';

function fixture() {
  const history=[];
  const native=new Worker(new URL('./fixtures/ap-worker-kit.mjs',import.meta.url));
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

test('explicit AP disconnect releases ownership and stops polling without reconnecting',async t=>{
  const {port,native,history}=fixture();t.after(()=>native.terminate());
  const link=new UsbTelemetry();await link.connect(port,{source:1});
  await until(()=>link.state==='connected');await link.disconnect();
  assert.equal(history.filter(e=>e.audit==='request').at(-1).command,'RELEASE');
  assert.equal(port.worker,null);assert.equal(link.state,'offline');
});

test('cancelling while the gateway is opening also settles the connect operation',async t=>{
  const {port,native}=fixture();t.after(()=>native.terminate());
  const link=new UsbTelemetry();
  const opening=link.connect(port,{source:1});
  await link.disconnect();await opening;
  assert.equal(port.worker,null);assert.equal(link.session,null);assert.equal(link.state,'offline');
});
