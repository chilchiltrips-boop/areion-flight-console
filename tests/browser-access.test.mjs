import test from 'node:test';
import assert from 'node:assert/strict';
import {browserAccess} from '../web/browser-access.js';
import {monitorOffline} from '../web/offline.js';

const nextTurn = () => new Promise(resolve => setImmediate(resolve));
function browser(known, allowed, extra={}) {
  return {self:{}, top:{}, isSecureContext:true, origin:'https://console.test', WebSocket:class {},
    navigator:{serial:{requestPort(){}},serviceWorker:{}},
    document:{featurePolicy:{features:()=>known,allowsFeature:key=>allowed.includes(key)}}, ...extra};
}
test('embedded device access follows modern and earlier policy independently for USB and AP',()=>{
  const denied=browserAccess(browser(['serial','local-network','local-network-access'],['local-network-access','serial']));
  assert.equal(denied.usbIssue,'');assert.match(denied.apIssue,/host/);assert(denied.embedded);
  const older=browserAccess(browser(['serial','local-network-access'],['local-network-access']));
  assert.match(older.usbIssue,/serial/);assert.equal(older.serial,null);assert.equal(older.apIssue,'');
  const unknown=browserAccess(browser([],[]));assert(unknown.serial);assert.equal(unknown.apIssue,'');
  const opaque=browserAccess(browser([],[],{origin:'null'}));assert.equal(opaque.workers,null);assert.match(opaque.apIssue,/sandbox/);
  const insecure=browserAccess(browser([],[],{isSecureContext:false}));assert.match(insecure.usbIssue,/HTTPS/);
});
test('offline ready requires this frame’s controlling worker and complete matching release; missing files can be repaired',async()=>{
  const workers=new EventTarget(), registration=new EventTarget();
  const url='https://console.test/kit/offline-worker.js', statuses=[];
  workers.register=async()=>registration;registration.update=async()=>{};
  const other={scriptURL:'https://console.test/offline-worker.js'};workers.controller=other;
  let result={core:'kit',cached:9,total:10};
  const retry=monitorOffline({workers,workerURL:url,core:'kit',update:s=>statuses.push(s.state),
    ask:async(worker,core,repair)=>{
      assert.equal(worker.scriptURL,url);assert.equal(core,'kit');
      return repair?{core:'kit',cached:10,total:10}:result;
    }});
  await nextTurn();assert.deepEqual(statuses,['preparing']);
  workers.controller={scriptURL:url};workers.dispatchEvent(new Event('controllerchange'));await nextTurn();
  assert.equal(statuses.at(-1),'failed');
  await retry();await nextTurn();assert.equal(statuses.at(-1),'ready');
  result={core:'old',cached:10,total:10};
  workers.dispatchEvent(new Event('controllerchange'));await nextTurn();assert.equal(statuses.at(-1),'update');
});
test('an offline reload can use its verified controller when registration hits the disconnected network',async()=>{
  const workers=new EventTarget(), statuses=[];
  workers.controller={scriptURL:'worker'};workers.register=async()=>{throw Error('network unreachable');};
  monitorOffline({workers,workerURL:'worker',core:'release',update:s=>statuses.push(s.state),
    ask:async()=>({core:'release',cached:127,total:127})});
  await nextTurn();assert.equal(statuses.at(-1),'ready');
  monitorOffline({workers:null,core:'release',update:s=>statuses.push(s.state)});
  assert.equal(statuses.at(-1),'unavailable');
});
test('a host that refuses offline storage reports the permission problem', async()=>{
  const workers=new EventTarget(), statuses=[];
  workers.register=async()=>{ throw new DOMException('Storage denied','SecurityError'); };
  monitorOffline({workers,workerURL:'worker',core:'release',update:status=>statuses.push(status)});
  await nextTurn();
  assert.equal(statuses.at(-1).state,'unavailable');
  assert.match(statuses.at(-1).detail,/offline storage/);
});
