import test from 'node:test';
import assert from 'node:assert/strict';
import {WifiPort, apUrl, DEFAULT_AP_URL} from '../web/wifi.js';

class Socket {
  static OPEN=1; static CONNECTING=0;
  constructor(url,protocol) {
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
  close(){this.readyState=3;}
}

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
  await assert.rejects(connecting,/too late/);
});
