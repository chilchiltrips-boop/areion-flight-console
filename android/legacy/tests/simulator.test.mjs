// Run against the prepared simulator asset directory, using the same DOM events as the WebView.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import vm from 'node:vm';

const bundle = process.env.SIMULATOR_ASSETS;
if (!bundle) throw new Error('Set SIMULATOR_ASSETS to the prepared simulator directory');
const asset = name => readFileSync(join(bundle, name), 'utf8');
const index = asset('index.html');

test('resource and network surface is limited to PC pairing', () => {
  for (const [, file] of index.matchAll(/(?:src|href)="([^"]+)"/g)) {
    assert.doesNotThrow(() => asset(file), file);
  }
  const scripts = [...index.matchAll(/<script src="([^"]+)"/g)].map(([,name]) => name);
  for (const filename of scripts.filter(name => !name.startsWith('vendor/'))) {
    assert.doesNotMatch(asset(filename), /\bZebjusNetwork\b|ZJUDP|NET_REQUEST|NET_RESPONSE|192\.168\.4\.1|\/api\/(?:led|wifi|status)|\/areion\b/i, filename);
  }
  assert.match(index, /connect-src 'self' https:\/\/0\.peerjs\.com wss:\/\/0\.peerjs\.com;/);
});

class Control extends EventTarget {
  constructor() {
    super();
    this.style = {};
    this.dataset = {};
    this.classList = {add() {}, remove() {}};
    this.value = '';
  }
  setAttribute() {}
  getBoundingClientRect() { return {left: 0, top: 0, width: 150, height: 150}; }
  setPointerCapture(id) { this.capture = id; }
  hasPointerCapture(id) { return this.capture === id; }
  releasePointerCapture() { this.capture = null; }
  sendPointer(name, id, x, y) {
    const e = Object.assign(new Event(name, {cancelable: true}), {pointerId:id, pointerType:'touch',clientX:x,clientY:y});
    this.dispatchEvent(e);
  }
}

test('two independent touches drive four virtual channels and STOP accepts a third pointer', () => {
  const ids = new Map([...index.matchAll(/id="([^"]+)"/g)].map(([,id]) => [id, new Control()]));
  let frame;
  let tick;
  let send;
  let clock = 100;
  const settings = {connected:true, paired:true, simulatorReady:true, controller:'mobile', sessionId:'browser_fixture'};
  const document = new EventTarget();
  Object.assign(document, {readyState:'complete', hidden:false, documentElement:new Control(), getElementById:id=> {
    assert.ok(ids.has(id), id);
    return ids.get(id);
  }});
  const context = vm.createContext({
    console, document, performance:{now:()=>clock}, localStorage:{getItem:()=>null, setItem() {}},
    matchMedia:()=>({matches:true}), setTimeout, clearTimeout,
    requestAnimationFrame:callback=>{tick=callback;return 1;}, cancelAnimationFrame() {},
    setInterval:callback=>{send=callback;return 1;}, clearInterval() {}, addEventListener() {},
  });
  context.window = context;
  vm.runInContext(asset('flight-input.js'), context);
  vm.runInContext(asset('companion-flight.js'), context);
  const deck = context.ZebjusFlightApp;
  deck.connect({status:()=>settings, sendSimulatorControl:input=>{frame=input; return true;}});
  deck.onStatus(settings);
  function ack() {
    deck.onAck({ackSeq:frame.seq,sessionId:settings.sessionId,accepted:true,applied:{...frame,source:'mobile'}});
  }
  ack();
  assert.equal(ids.get('flightArm').disabled,false);
  ids.get('flightArm').onclick(); ack();
  const left = ids.get('flightLeftZone');
  const right = ids.get('flightRightZone');
  left.sendPointer('pointerdown',1,60,80);
  right.sendPointer('pointerdown',2,65,75);
  left.sendPointer('pointermove',1,89,47);
  right.sendPointer('pointermove',2,94,42);
  clock += 60; tick(clock); send(); ack();
  assert.equal(frame.armed,true);
  assert.ok(frame.throttle>1000 && frame.axes.roll>0 && frame.axes.pitch>0 && frame.axes.yaw<0);
  const held = frame.throttle;
  right.sendPointer('pointerup',2,94,42);
  left.sendPointer('pointerup',1,89,47);
  clock += 60; tick(clock); send(); ack();
  assert.ok(Object.values(frame.axes).every(value => value === 0));
  assert.equal(frame.throttle,held);
  ids.get('flightMode').onchange({target:{value:'acro'}}); ack();
  assert.equal(frame.mode,'acro');
  left.sendPointer('pointerdown',1,60,80);
  right.sendPointer('pointerdown',2,65,75);
  ids.get('flightStop').sendPointer('pointerdown',3,0,0);
  assert.equal(frame.armed,false);
  assert.equal(frame.throttle,1000);
  assert.ok(Object.values(frame.axes).every(value => value === 0));
  assert.equal(left.capture,null);
  assert.equal(right.capture,null);
});

// Exercise the actual QR serialization, pairing/approval, mirror negotiation and session logic.
// Only the RTCPeerConnection/DataChannel carrier is substituted for a CI test without radios.
test('QR pairing with the desktop gates input and accepts preview mirror frames only', async () => {
  const instances = [];
  const captured = [];
  class DataChannel {
    constructor(label) { Object.assign(this,{label,readyState:'connecting',bufferedAmount:0}); }
    send(text) {
      const recipient = this.other;
      if (this.readyState !== 'open') throw Error('Channel closed');
      captured.push(JSON.parse(text));
      queueMicrotask(() => recipient.onmessage?.({data:text}));
    }
    close() { this.readyState = 'closed'; }
  }
  class RTC {
    constructor() {
      this.id = instances.push(this) - 1;
      this.channels = [];
      this.iceGatheringState = 'complete';
    }
    createDataChannel(label) { const dc=new DataChannel(label); this.channels.push(dc); return dc; }
    async createOffer() { return {type:'offer',sdp:'v=0\r\no=fixture '+this.id}; }
    async createAnswer() { return {type:'answer',sdp:'v=0\r\no=fixture '+this.id}; }
    async setLocalDescription(desc) {
      this.localDescription=desc;
      this.signalingState=desc.type==='offer'?'have-local-offer':'stable';
    }
    async setRemoteDescription(desc) {
      const other=instances[Number(desc.sdp.split(' ').at(-1))];
      if(desc.type==='offer'){
        for(const dc of other.channels) {
          const incoming=this.createDataChannel(dc.label);
          dc.other=incoming;
          incoming.other=dc;
          this.ondatachannel?.({channel:incoming});
        }
      } else {
        for(const peer of [other,this]) {
          for(const dc of peer.channels) dc.readyState='open';
          for(const dc of peer.channels) dc.onopen?.();
        }
      }
    }
    close() { for(const dc of this.channels) dc.close(); }
  }
  function library(source) {
    const ctx=vm.createContext({crypto,RTCPeerConnection:RTC,TextEncoder,TextDecoder,btoa,atob,
      Blob,CompressionStream,DecompressionStream,Response,console,setTimeout,clearTimeout,setInterval,clearInterval});
    vm.runInContext(source,ctx);
    return ctx.ZebjusP2P;
  }
  const received=[];
  const desktopSource=process.env.DRONELAB_HOST_PAIRING_JS;
  const desktop=library(desktopSource?readFileSync(desktopSource,'utf8'):asset('pairing-core.js'))
    .session('host',{inputMirror:frame=>received.push(frame)},{inputMirrorOnly:true});
  const mobile=library(asset('pairing-core.js')).session('mobile');
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  try {
    const offer=await desktop.makeOffer();
    const answer=await mobile.makeAnswer(offer.qr);
    assert.equal(answer.pin,offer.pin);
    assert.equal(answer.sid,offer.sessionId);
    await desktop.receiveAnswer(answer.qr);
    function send(seq,overrides={}) {
      return mobile.sendInputMirror({mirrorVersion:1,sessionId:answer.sid,seq,kitId:'',kind:'android-preview',
        transport:'preview',inputAgeMs:0,channels:{throttle:1040,roll:1667,pitch:1250,yaw:1600},
        aux:{ch5:1200,ch6:1545},...overrides});
    }
    assert.equal(send(1),false);
    desktop.approvePairing();
    await flush();
    assert.equal(mobile.status().inputMirrorVersion,1);
    assert.equal(send(2,{transport:'ap',kind:'android-command'}),false);
    assert.equal(send(3),true);
    await flush();
    assert.deepEqual({...received[0].channels},{throttle:1040,roll:1667,pitch:1250,yaw:1600});
    assert.deepEqual({...received[0].aux},{ch5:1200,ch6:1545});
    assert.equal(desktop.grantMobileControl(),false);
    desktop.channel.send(JSON.stringify({type:'NET_REQUEST',v:1,sessionId:answer.sid,requestId:'fixture',method:'GET',path:'/api/status'}));
    await flush();
    assert.equal(captured.some(frame=>frame.type==='NET_RESPONSE'),false);
    assert.equal(mobile.status().paired,true);
  } finally {
    mobile.close(); desktop.close();
  }
});
