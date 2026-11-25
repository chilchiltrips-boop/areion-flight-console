import assert from 'node:assert/strict';
import {setTimeout as delay} from 'node:timers/promises';
import test from 'node:test';
import {crc32} from 'node:zlib';
import {ApController} from '../android/controller/controller.js';
import {defaults} from '../web/config-commands.js';
import {NEUTRAL} from '../web/cockpit-controls.js';
import {schemaFor} from '../web/protocol.js';

async function until(check) {
  const end = performance.now() + 3500;
  while (!check()) {
    if (performance.now() > end) throw Error('Timed out waiting for ' + check);
    await delay(10);
  }
}

// A byte-stream FC test peer. The production session still performs its real handshake,
// validates frames, verifies addressed reads and streams its normal group 9 commands.
function flightController() {
  let input = 0, host, seq = 0, samples, rx, ready = false, armed = false, channels = [...NEUTRAL];
  const writes = [];
  const setup = [false,true,7,4,15,true,true,false,false,1100,1100,1100,1100,1,'','QA_A1'];
  const current = group => {
    switch (group) {
      case 22: return channels;
      case 110: return [input];
      case 120: return [armed,channels[4]<1500,true,ready?8:0,.004,2000,2048,true,true,true];
      case 122: return [input,ready?2:0,false,ready,ready,ready?8:0,ready?10:4294967295,host,false];
      case 130: return setup;
      case 134: return defaults[134].map((v,i)=>i===1?input:v);
      case 136: return [false,1,1,''];
      default: return defaults[group];
    }
  };
  function reply(fields) {
    const body = JSON.stringify({v:2,...fields});
    const bytes = Buffer.from(body);
    rx.enqueue(Buffer.from('$'+bytes.length+':'+body+'*'+crc32(bytes).toString(16).toUpperCase().padStart(8,'0')+'\n'));
  }
  return {
    writes,
    async open() {
      this.readable = new ReadableStream({start: target => { rx = target; }});
      this.writable = new WritableStream({write(bytes) {
        const wire = Buffer.from(bytes).toString();
        const msg = JSON.parse(wire.slice(wire.indexOf(':')+1,-10));
        writes.push(msg);
        const answer = (type,data) => reply({...msg,type,data});
        if (msg.type==='HELLO') {
          host = msg.session;
          answer('ACK',['HELLO',8711]);
          samples = setInterval(()=> {
            for (const group of [120,122,130,22,136]) {
              reply({type:'DATA',group,schema:schemaFor(group),session:8711,seq:++seq,data:current(group)});
            }
          },40);
        } else if (msg.type==='READ') {
          const data = current(msg.group);
          answer(data?'DATA':'ERROR',data??['UNAVAILABLE']);
        } else if (msg.type==='CONTROL') {
          assert.equal(msg.group,9);
          assert.equal(msg.session,host);
          ready = true;
          channels = [...msg.data];
        } else if (msg.type==='ACTION' && msg.data[0]==='INPUT_SAVE') {
          assert.deepEqual(msg.data,['INPUT_SAVE',1,0,0,0]);
          input = msg.data[1];
          answer('ACK',['INPUT_SAVED']);
        } else if (msg.type==='ACTION' && msg.group===123) {
          armed = msg.data[0]==='ARM';
          answer('ACK',[armed?'ARMED':'DISARMED']);
        } else if (msg.type==='PING') answer('ACK',['PONG']);
      }});
    },
    async close() { clearInterval(samples); }
  };
}

test('standalone Android AP controller selects the kit input, qualifies channels and disarms on background',async t=>{
  const kit=flightController(), phone=new EventTarget();
  const ap=new ApController({makePort:()=>kit,nativeAvailable:()=>true,window:phone});
  t.after(()=>ap.destroy());

  ap.controls.stick(false,.5,0,true);
  await ap.toggleSender();
  assert.equal(ap.snapshot().sending,false);
  assert.equal(kit.writes.length,0);

  await ap.connect();
  await until(()=>ap.snapshot().canChooseAp);
  assert.equal(ap.snapshot().canSend,false);
  await ap.chooseAp();
  await until(()=>ap.snapshot().canSend);
  assert.deepEqual(kit.writes.filter(m=>m.type==='ACTION').map(m=>m.data),[['INPUT_SAVE',1,0,0,0]]);
  assert.equal(kit.writes.some(m=>m.type==='CONTROL'),false);

  await ap.toggleSender();
  await until(()=>ap.snapshot().ready && ap.snapshot().canMode);
  assert.deepEqual(kit.writes.find(m=>m.type==='CONTROL').data,NEUTRAL);
  ap.setMode(1);
  ap.controls.stick(false,.5,0,true);
  await until(()=>ap.snapshot().received?.[0]===1750 && ap.snapshot().mode===1);
  assert.equal(ap.snapshot().canArm,false);
  phone.dispatchEvent(new Event('areion-app-pause'));
  await until(()=>kit.writes.some(m=>m.type==='ACTION' && m.data[0]==='DISARM') && !ap.stopPending);
  assert.equal(ap.snapshot().sending,false);
  assert.deepEqual(ap.controls.values,NEUTRAL);
  const sent=kit.writes.filter(m=>m.type==='CONTROL').length;
  await delay(85);
  assert.equal(kit.writes.filter(m=>m.type==='CONTROL').length,sent);
});
