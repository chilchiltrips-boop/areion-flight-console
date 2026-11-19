import test from 'node:test';
import assert from 'node:assert/strict';
import {observeTx,TxCheck,classifyTx,spareChannels} from '../web/tx-evidence.js';
function receiver(){
  const ctx={state:'connected',replay:false,clock:0,model:{frames:new Map()},rows:[]};
  const put=(at,group,values)=>{const row={at,group,values};ctx.rows.push(row);ctx.model.frames.set(group,row);ctx.clock=at;};
  put(0,130,[...Array(15).fill(0),'A1']);
  put(0,7,[5]);put(0,134,[0,0,1,2,3,4]);
  function frame(at,ch,count=8){
    const on=ch!==null;
    put(at,120,[false,true,true,on?count:0,.004,2000]);
    put(at,122,[0,on?1:0,on,false,on,on?count:0,on?9:65535,13,false]);
    if(on)put(at,22,[1500,1500,1000,1500,2000,ch,1500,1500]);
    return observeTx(ctx);
  }
  function samples(at,ch,count=8){frame(at-300,ch,count);frame(at-150,ch,count);return frame(at,ch,count);}
  return {ctx,put,frame,samples};
}
test('radio check requires three independent ON/OFF/restored groups and a distinct loss value',()=>{
  const {ctx,frame,samples,put}=receiver(), check=new TxCheck(6);
  const initial=samples(600,2000);
  assert.equal(classifyTx(initial).code,'unverified');assert.deepEqual(spareChannels(initial),[6,7,8]);
  assert.equal(check.capture(initial),null);assert.throws(()=>check.capture(initial),/one second/);
  assert.throws(()=>check.capture(samples(1100,2000)),/still present/);
  check.capture(samples(1700,1000));
  assert.throws(()=>check.capture(samples(2200,1000)),/Restore/);
  const p=check.capture(samples(2700,2000));
  assert.equal(classifyTx(observeTx(ctx),p).level,'good');
  assert.equal(classifyTx(frame(2850,1000),p).label,'CHECKING');
  assert.equal(classifyTx(frame(3000,1000),p).label,'TX OFF');
  put(3030,110,[2]);assert.equal(classifyTx(observeTx(ctx),p).code,'inactive');
  put(3050,110,[0]);assert.equal(classifyTx(observeTx(ctx),p).code,'waiting');
  ctx.replay=true;assert.equal(classifyTx(observeTx(ctx),p).code,'inactive');
});
test('pulse-cut four-channel receiver, armed or stale captures and kit/session mismatch',()=>{
  const {ctx,samples,put}=receiver(), check=new TxCheck();
  check.capture(samples(600,1800,4));check.capture(samples(1100,null,4));
  const p=check.capture(samples(1600,1800,4));assert.equal(p.kind,'pulse');
  assert.equal(classifyTx(observeTx(ctx),p).code,'on');
  assert.equal(classifyTx(observeTx(ctx,2200),p).code,'waiting');
  assert.equal(classifyTx(samples(2400,null,4),p).label,'NO PPM');
  const o=samples(3000,1700,4);
  assert.equal(classifyTx({...o,kit:'A2'},p).code,'unverified');
  const more=new TxCheck();more.capture(o);
  assert.throws(()=>more.capture({...samples(3600,null,4),session:{}}),/changed/);
  put(3800,120,[true,true,true,0]);assert.throws(()=>new TxCheck().capture(observeTx(ctx)),/disarmed/);
});
test('new FC gate loss clears held AUX samples; reconnect/no telemetry does not claim radio ON',()=>{
  const {ctx,samples,put}=receiver(),check=new TxCheck(6);
  check.capture(samples(600,2000));check.capture(samples(1100,1000));const p=check.capture(samples(1600,2000));
  put(1650,120,[false,true,true,0]);assert.equal(classifyTx(observeTx(ctx),p).code,'waiting');
  ctx.state='stale';assert.equal(classifyTx(observeTx(ctx),p).code,'inactive');
});
