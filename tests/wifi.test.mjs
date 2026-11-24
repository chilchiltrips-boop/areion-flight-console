import test from 'node:test';
import {crc32} from 'node:zlib';
import {ApSessionPort} from '../web/ap-session-port.js';
import {UsbTelemetry} from '../web/usb.js';
import assert from 'node:assert/strict';
import {WifiPort, apUrl, DEFAULT_AP_URL, findApGateway} from '../web/wifi.js';

class Socket extends EventTarget {
  static OPEN=1; static CONNECTING=0;
  constructor(url,protocol) {
    super();
    this.url=url;this.protocol=protocol;this.readyState=0;this.bufferedAmount=0;this.frames=[];
    Socket.instance=this;
  }
  up(){this.readyState=1;this.onopen();}
  send(frame){this.frames.push(frame);}
  reply(id,credit,body=[]) {
    const payload=new Uint8Array(9+body.length),view=new DataView(payload.buffer);
    payload[0]=65;view.setUint32(1,id);view.setUint32(5,credit);payload.set(body,9);
    this.onmessage({data:payload.buffer});
  }
  close(){this.readyState=3;this.dispatchEvent(new Event('close'));}
}

test('blocked worker bootstrap opens the gateway once in the window and keeps binary telemetry usable',async t=>{
  const previous={Worker:globalThis.Worker,WebSocket:globalThis.WebSocket,document:globalThis.document};
  globalThis.document={getElementById:()=>null};
  globalThis.Worker=class{postMessage(){queueMicrotask(()=>this.onerror?.({preventDefault(){}}));}terminate(){}};
  globalThis.WebSocket=Socket;
  t.after(()=>{for(const [key,value] of Object.entries(previous)){if(value===undefined)delete globalThis[key];else globalThis[key]=value;}});
  Socket.instance=null;
  const port=new ApSessionPort();const opened=port.open();t.after(()=>port.close());
  for(let i=0;i<100&&!Socket.instance;i++)await new Promise(ok=>setTimeout(ok,5));
  const socket=Socket.instance;assert.ok(socket);socket.up();socket.reply(1,77,[36,10]);await opened;
  const reader=port.readable.getReader(),sample=await reader.read();reader.releaseLock();
  assert.deepEqual([...sample.value.bytes],[36,10]);assert.ok(Math.abs(performance.now()-sample.value.at)<200);
  await port.close();assert.equal(socket.readyState,3);
});

test('default targets the on-kit websocket and normalizes local addresses',()=>{
  assert.equal(apUrl('192.168.4.1'),DEFAULT_AP_URL);
  assert.equal(apUrl('ws://areion.local'), 'ws://areion.local:8081/areion');
  assert.equal(apUrl('wss://example.test/kit'), 'wss://example.test/kit');
  for(const url of ['udp://192.168.4.1','ws://example.test','ws://user:pw@192.168.4.1','ws://192.168.4.1#pw'])
    assert.throws(()=>apUrl(url));
});

test('AP adapter opens only on live reply, streams original bytes and never queues under congestion',async t=>{
  const previous=globalThis.WebSocket;globalThis.WebSocket=Socket;
  t.after(()=>{globalThis.WebSocket=previous;});
  const port=new WifiPort();const opened=port.open();
  const ws=Socket.instance;ws.up();
  assert.equal(ws.frames[0][0],80);
  const id=new DataView(ws.frames[0].buffer).getUint32(1);
  ws.reply(id,0x65432102,[36,10]);await opened;
  const reader=port.readable.getReader(),writer=port.writable.getWriter();
  assert.deepEqual((await reader.read()).value,new Uint8Array([36,10]));
  await writer.write(Uint8Array.from([36,42,10]));
  assert.deepEqual([...ws.frames.at(-1)],[70,0x65,0x43,0x21,2,36,42,10]);
  ws.bufferedAmount=1800;await assert.rejects(writer.write(Uint8Array.from([36,10])),/refused/);
  await port.close();assert.equal(ws.readyState,3);assert.ok((await reader.read()).done);
});

test('unexpected poll replies and stale handshakes cannot admit a kit session',async t=>{
  const previous=globalThis.WebSocket;globalThis.WebSocket=Socket;
  t.after(()=>{globalThis.WebSocket=previous;});
  const port=new WifiPort();const opened=port.open(),ws=Socket.instance;
  ws.up();ws.reply(99,10);
  await assert.rejects(opened,/Unexpected/);assert.equal(ws.readyState,3);
  const retry=new WifiPort();const connecting=retry.open();Socket.instance.up();
  retry.pending.at-=300;Socket.instance.reply(retry.pending.id,10);
  assert.equal(retry.credit,null);assert.equal(retry.timing.late_polls,1);
  assert.throws(()=>retry.write(Uint8Array.from([36,10])),{code:'AP_FRAME_DROPPED'});
  Socket.instance.reply(retry.pending.id,11);await connecting;await retry.close();
});

test('Find kit polls one Areion gateway, falls back to the factory address, and releases the socket without a Link frame',async t=>{
  const sockets=[];
  class Discovery extends Socket {
    constructor(url, protocol) {
      super(url, protocol);sockets.push(this);
      queueMicrotask(()=>url===DEFAULT_AP_URL ? this.up() : this.onerror());
    }
    send(frame) {
      super.send(frame);
      queueMicrotask(()=>this.reply(new DataView(frame.buffer).getUint32(1),941));
    }
  }
  const original=globalThis.WebSocket;globalThis.WebSocket=Discovery;
  t.after(()=>{globalThis.WebSocket=original;});
  assert.equal(await findApGateway('areion.local'),DEFAULT_AP_URL);
  assert.deepEqual(sockets.map(s=>s.url),['ws://areion.local:8081/areion',DEFAULT_AP_URL]);
  assert(sockets.every(s=>s.readyState===3));
  assert.deepEqual(sockets.flatMap(s=>s.frames.map(f=>[f[0],f.length])),[[80,5]]);
});
test('cancelling AP discovery closes the pending socket and never tries another kit',async t=>{
  const original=globalThis.WebSocket;globalThis.WebSocket=Socket;
  t.after(()=>{globalThis.WebSocket=original;});
  const abort=new AbortController();
  const pending=findApGateway('areion.local',{signal:abort.signal});
  const socket=Socket.instance;abort.abort();
  await assert.rejects(pending,{name:'AbortError'});
  assert.equal(socket.readyState,3);assert.equal(Socket.instance,socket);assert.deepEqual(socket.frames,[]);
});

test('explicit Connect sends native Link frames and receives telemetry through the gateway after discovery releases it',{timeout:6000},async t=>{
  const requests=[], events=[], fc=1221, ticket=734, enc=new TextEncoder();
  let source=0;
  class KitGateway extends Socket {
    constructor(url,protocol){super(url,protocol);this.replies=[];queueMicrotask(()=>this.up());}
    response(request,type,data,fields={}) {
      const body=JSON.stringify({...request,type,data,...fields});
      const bytes=enc.encode(body);
      this.replies.push(...enc.encode('$'+bytes.length+':'+body+'*'+crc32(bytes).toString(16).toUpperCase().padStart(8,'0')+'\n'));
    }
    send(frame){
      super.send(frame);
      const id=new DataView(frame.buffer,frame.byteOffset,frame.byteLength).getUint32(1);
      if(frame[0]===80){
        const values=this.replies.splice(0);
        queueMicrotask(()=>{if(this.readyState===1)this.reply(id,ticket,values);});
        return;
      }
      assert.equal(frame[0],70);assert.equal(id,ticket);
      const packet=new TextDecoder().decode(frame.subarray(5));
      const wire=JSON.parse(packet.slice(packet.indexOf(':')+1,-10));
      requests.push(wire);
      if(wire.type==='HELLO'){
        this.response(wire,'ACK',['HELLO',fc]);
        this.response(wire,'DATA',[1500,1400,1000,1500,1000,1000,1500,1500],{group:22,schema:1,session:fc,seq:1});
      } else if(wire.type==='SET' && wire.group===110){
        source=wire.data[0];this.response(wire,'ACK',['APPLIED_UNSAVED']);
      } else if(wire.type==='READ' && wire.group===110){
        this.response(wire,'DATA',[source]);
      }
    }
  }
  const original=globalThis.WebSocket;globalThis.WebSocket=KitGateway;t.after(()=>{globalThis.WebSocket=original;});
  const addr=await findApGateway(DEFAULT_AP_URL);assert.deepEqual(requests,[]);
  const handshake=Promise.withResolvers();
  const link=new UsbTelemetry({
    onStatus:status=>{
      if(status.state==='connected')handshake.resolve();
      if(status.state==='error')handshake.reject(Error(status.message));
    },
    onData:sample=>events.push(sample)
  });
  t.after(()=>link.disconnect());
  await link.connect(new WifiPort(addr),{source:1,label:'AP Wi-Fi'});
  await handshake.promise;
  assert.equal(link.fcSession,fc);assert.equal(events[0].group,22);
  assert.deepEqual(await link.setGroup(110,[1]),['APPLIED_UNSAVED']);
  assert.deepEqual(await link.readGroup(110),[1]);
  await link.disconnect();
  assert.equal(requests[0].type,'HELLO');assert.equal(requests.at(-1).type,'RELEASE');
  assert(!requests.some(request=>['ACTION','CONTROL'].includes(request.type)));
});

test('late poll data and stale writes are dropped while later fresh traffic uses the same WebSocket',async t=>{
  const original=globalThis.WebSocket;globalThis.WebSocket=Socket;t.after(()=>{globalThis.WebSocket=original;});
  const port=new WifiPort();const opening=port.open(),ws=Socket.instance;t.after(()=>port.close());
  ws.up();ws.reply(1,42);await opening;
  const reader=port.readable.getReader();
  while(!port.pending)await new Promise(resolve=>setTimeout(resolve,5));
  port.pending.at-=310;ws.reply(port.pending.id,43,[1,2,3]);
  assert.equal(ws.readyState,1);assert.equal(port.credit,null);
  assert.throws(()=>port.write(Uint8Array.from([36,10])),{code:'AP_FRAME_DROPPED'});
  ws.reply(port.pending.id,44,[4,5,6]);assert.deepEqual([...((await reader.read()).value)],[4,5,6]);
  port.write(Uint8Array.from([36,10]));assert.equal(ws.frames.at(-1)[4],44);
  assert.equal(port.timing.dropped_writes,1);assert.equal(port.timing.late_polls,1);reader.releaseLock();
});

test('one missing gateway reply is polled again on the same socket; its late data and ticket are ignored',async t=>{
  const original=globalThis.WebSocket;globalThis.WebSocket=Socket;t.after(()=>{globalThis.WebSocket=original;});
  const port=new WifiPort();const opening=port.open(),ws=Socket.instance;t.after(()=>port.close());
  ws.up();ws.reply(1,50);await opening;
  while(!port.pending)await new Promise(resolve=>setTimeout(resolve,5));
  const missed=port.pending.id;port.pending.at-=250;
  while(port.pending.id===missed)await new Promise(resolve=>setTimeout(resolve,5));
  const next=port.pending.id;
  ws.reply(next,52,[3,4]);ws.reply(missed,51,[9,9]);
  assert.equal(ws.readyState,1);assert.equal(port.credit.value,52);
  const reader=port.readable.getReader();
  assert.deepEqual([...(await reader.read()).value],[3,4]);
  while(!port.pending)await new Promise(resolve=>setTimeout(resolve,5));
  ws.reply(port.pending.id,53,[5,6]);assert.deepEqual([...(await reader.read()).value],[5,6]);
  assert.equal(port.timing.poll_retries,1);assert.ok(ws.frames.every(frame=>frame[0]===80));
  reader.releaseLock();
});
