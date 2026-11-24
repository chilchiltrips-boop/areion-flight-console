import test from 'node:test';
import assert from 'node:assert/strict';

import {mountNotifications} from '../web/header-notifications.js';
import {armCaption, TrafficMeter} from '../web/header.js';
import {GrantedPorts, usbKey, usbLabel} from '../web/ports.js';

const adapter = (product = 4097) => ({
  getInfo() { return {usbVendorId: 0x303a, usbProductId: product}; }
});

function fixture(ports) {
  const listeners = new Map(), db = new Map();
  const serial = {
    ports, prompts: 0,
    async getPorts() { return this.ports; },
    async requestPort() { this.prompts++; return this.ports.at(-1); },
    addEventListener(type, fn) { listeners.set(type,fn); },
    removeEventListener(type) { listeners.delete(type); }
  };
  const storage = {
    getItem(key) { return db.get(key); },
    setItem(key, value) { db.set(key,value); },
    removeItem(key) { db.delete(key); }
  };
  return {serial, storage, db, listeners, model: new GrantedPorts(serial, storage)};
}

test('USB discovery enumerates granted ports without prompting or opening; confirmation restores an unambiguous preference', async () => {
  const a = adapter(), b = adapter(7), f = fixture([a,b]);
  await f.model.scan();
  assert.equal(f.serial.prompts, 0);
  assert.equal(f.model.selected, null);
  assert.equal(usbLabel(a),'USB 1001');
  assert.equal(usbLabel({}),'Serial port');
  assert.equal(usbKey(b),'303A:0007');
  f.model.select(a);
  assert.equal(f.db.size,0);
  f.model.remember(a);
  const next = new GrantedPorts(f.serial, f.storage);
  await next.scan();
  assert.equal(next.selected,a);
  assert.equal(next.choices()[0].remembered,true);
  assert.equal(f.serial.prompts,0);
  await next.choose();
  assert.equal(f.serial.prompts,1);
  assert.equal(next.selected,b);
  assert.deepEqual([...f.db.values()],['303A:1001']);
});

test('USB hotplug and ambiguous devices cannot silently pick a different identical board', async () => {
  const a=adapter(), twin=adapter(), f=fixture([a]);
  await f.model.scan();
  f.model.remember(a);
  f.serial.ports.push(twin);
  const next=new GrantedPorts(f.serial,f.storage);
  await next.scan();
  assert.equal(next.selected,null);
  assert.notEqual(next.choices()[0].label,next.choices()[1].label);
  next.remember(twin);
  assert.equal(f.db.size,0);
  const event=f.listeners.get('disconnect');
  event({type:'disconnect',target:twin});
  await next.scan();
  assert.equal(next.selected,null);
  assert.equal(next.choices().length,1);
  assert.equal(f.serial.prompts,0);
  next.destroy();
});

test('short labels distinguish matching product numbers and preserve the confirmed vendor identity', async () => {
  const board=adapter(), bridge={getInfo:()=>({usbVendorId:0x1234,usbProductId:0x1001})};
  const f=fixture([board,bridge]);
  await f.model.scan(); f.model.remember(bridge);
  const next=new GrantedPorts(f.serial,f.storage);
  await next.scan();
  assert.equal(next.selected,bridge);
  assert.deepEqual(next.choices().map(({label,key,remembered})=>[label,key,remembered]), [
    ['USB 1001 #1','303A:1001',false], ['USB 1001 #2','1234:1001',true]
  ]);
});

test('replugging a sole matching adapter restores the choice without a new permission prompt', async () => {
  const old=adapter(), replacement=adapter(), f=fixture([old]);
  await f.model.scan();f.model.remember(old);
  f.serial.ports=[];await f.model.scan();
  assert.equal(f.model.selected,null);
  f.serial.ports=[replacement];await f.model.scan();
  assert.equal(f.model.selected,replacement);
  assert.equal(f.serial.prompts,0);
});

test('a slow device scan cannot erase a port explicitly chosen meanwhile', async () => {
  const a=adapter(), f=fixture([a]);
  let finish;
  f.serial.getPorts=()=>new Promise(resolve=>{finish=resolve;});
  const old=f.model.scan();
  await f.model.choose();
  finish([]); await old;
  assert.equal(f.model.selected,a);
  assert.equal(f.model.ports.length,1);
});

test('transport frame meters derive independent rates, freshness and offline from actual I/O', () => {
  const traffic=new TrafficMeter();
  assert.deepEqual(traffic.sample(0,false),{tx:null,rx:null,fresh:false});
  traffic.sample(100,true);
  for(const t of [200,350,500])traffic.add({direction:'rx',at:t,bytes:300});
  traffic.add({direction:'tx',at:560,bytes:200});
  assert.deepEqual(traffic.sample(600,true),{tx:2,rx:6,fresh:true});
  assert.deepEqual(traffic.sample(1400,true),{tx:0,rx:0,fresh:false});
  assert.deepEqual(traffic.sample(1500,false),{tx:null,rx:null,fresh:false});
  traffic.reset();assert.deepEqual(traffic.count,{tx:0,rx:0});
});

test('arm badge uses fresh FC setup/armed state, and replay or lost link clears live status', () => {
  assert.equal(armCaption([true],[true,false],true),'ARMED · DISARM REQUIRED');
  assert.equal(armCaption([false],[true,false],true),'ARM LOCKED · SETUP');
  assert.equal(armCaption([false],null,true),'ARM UNAVAILABLE · SETUP');
  assert.equal(armCaption([false],[false,true],true),'DISARMED');
  assert.equal(armCaption([true],[false,true],true),'ARMED');
  assert.equal(armCaption([true],[false,true],false),'ARM UNKNOWN');
});

test('notifications remind until read, acknowledge a release across reloads, and rearm for a new release or connection issue', () => {
  const storage=fixture([]).storage;
  function header(release) {
    const nodes=new Map(), doc=new EventTarget();
    doc.defaultView=new EventTarget();
    const root=Object.assign(new EventTarget(),{ownerDocument:doc, querySelector(selector) {
      if (!nodes.has(selector)) {
        const node=Object.assign(new EventTarget(),{hidden:true,dataset:{},focus(){},
          setAttribute(key,value){this[key]=value;}});
        nodes.set(selector,node);
      }
      return nodes.get(selector);
    }});
    const panel=mountNotifications(root,{release,storage,retry(){}});
    return {panel,bell:nodes.get('.bell-button'),dot:nodes.get('.unread-dot'),close:nodes.get('.dismiss-notifications')};
  }
  const update={state:'update',detail:'Reopen the console online.'};
  let ui=header('current');
  ui.panel.setOffline({state:'ready',detail:'Ready for offline use.'});
  assert.ok(ui.dot.hidden);
  ui.panel.setOffline(update);ui.panel.setOffline(update);
  assert.equal(ui.dot.hidden,false);assert.match(ui.bell['aria-label'],/1 unread/);
  ui.bell.dispatchEvent(new Event('click'));assert.ok(ui.dot.hidden);
  ui.panel.setConnection('USB access blocked.',true,false);assert.ok(ui.dot.hidden);
  ui.close.dispatchEvent(new Event('click'));
  ui.panel.setOffline(update);ui.panel.setConnection('USB access blocked.',true,false);
  assert.ok(ui.dot.hidden);
  ui.panel.setConnection('',false,false);ui.panel.setConnection('USB access blocked.',true,false);
  assert.equal(ui.dot.hidden,false);ui.panel.destroy();
  ui=header('current');ui.panel.setOffline(update);assert.ok(ui.dot.hidden);ui.panel.destroy();
  ui=header('next');ui.panel.setOffline(update);assert.equal(ui.dot.hidden,false);ui.panel.destroy();
});
