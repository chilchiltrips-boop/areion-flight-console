import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {WifiPort, DEFAULT_AP_URL} from '../web/wifi.js';

const script = readFileSync(new URL('../android/controller/native-host.js',import.meta.url),'utf8');
const ws = {CONNECTING:0, OPEN:1, CLOSING:2, CLOSED:3};
class Close extends Event {
  constructor(type, init) { super(type); Object.assign(this, init); }
}

function bridge(host) {
  const context = {AreionAndroid:host, WebSocket:ws, crypto, EventTarget, Event, MessageEvent,
    CloseEvent:Close, Uint32Array, Uint8Array, atob, btoa};
  context.window = context;
  runInNewContext(script,context);
  return context.AreionNativeSocket;
}

test('Android-local AP adapter negotiates a live ticket then delivers Link bytes without modifying the web protocol', async () => {
  let connected, closed, dataFrame;
  const Socket = bridge({
    openSocket(id, url) {
      assert.equal(url, DEFAULT_AP_URL);
      connected = id;
      queueMicrotask(()=>Socket.receive(id,'open','areion-link-v2'));
      return '';
    },
    queuedSocket: () => 0,
    sendSocket(id, encoded) {
      assert.equal(id, connected);
      const bytes=Buffer.from(encoded,'base64');
      if(bytes[0]===0x50) {
        const reply=Buffer.alloc(12);
        reply[0]=0x41;
        reply.writeUInt32BE(bytes.readUInt32BE(1),1);
        reply.writeUInt32BE(0x80abcdef,5);
        reply.set([36,65,10],9);
        queueMicrotask(()=>Socket.receive(id,'message',reply.toString('base64')));
      } else dataFrame=bytes;
      return true;
    },
    closeSocket(id) {
      closed=id;
      queueMicrotask(()=>Socket.receive(id,'close','1000'));
    }
  });
  const original=globalThis.WebSocket;
  globalThis.WebSocket=ws;
  globalThis.AreionNativeSocket=Socket;
  const port=new WifiPort();
  try {
    await port.open();
    const reader=port.readable.getReader();
    assert.deepEqual((await reader.read()).value,Uint8Array.from([36,65,10]));
    reader.releaseLock();
    port.write(Uint8Array.from([36,74,10]));
    assert.equal(dataFrame[0],0x46);
    assert.equal(dataFrame.readUInt32BE(1),0x80abcdef);
    assert.deepEqual([...dataFrame.subarray(5)],[36,74,10]);
    await port.close();
    assert.equal(closed,connected);
    Socket.receive(connected,'message','not-valid-base64'); // Late network callbacks cannot reopen a session.
    assert.equal(port.socket,null);
  } finally {
    await port.close();
    delete globalThis.AreionNativeSocket;
    globalThis.WebSocket=original;
  }
});

test('Android AP routing error is shown intact and never falls back to mobile data', async () => {
  globalThis.AreionNativeSocket=bridge({openSocket(){return 'Join the kit Wi-Fi first.';}});
  try { await assert.rejects(new WifiPort().open(),/Join the kit Wi-Fi first/); }
  finally { delete globalThis.AreionNativeSocket; }
});
