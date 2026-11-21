import test from 'node:test';
import assert from 'node:assert/strict';
import {CockpitSender,Controls,currentGuard,transmitterView,DEFAULT_KEYS,NEUTRAL,switchPulse,validKeys} from '../web/cockpit-controls.js';
import {signed,tilt,wrap} from '../web/cockpit-pfd.js';

test('mouse spring return preserves throttle; keyboard assignments act on their mapped channels',()=>{
  const c=new Controls();
  c.stick(true,1,-.5,true);c.stick(false,-.4,.5,true);
  assert.deepEqual(c.values.slice(0,4),[1300,1750,1250,2000]);
  c.stick(true,0,0,false);c.stick(false,0,0,false);
  assert.deepEqual(c.values.slice(0,4),[1500,1500,1250,1500]);
  c.key('Up',true);c.step(.02);assert.equal(c.values[1],2000);assert.equal(c.values[7],1000);
  c.key('Up',false);c.step(.02);assert.equal(c.values[1],1500);
  c.key('W',true);c.step(.02);assert.equal(c.values[2],1260);
  c.key('8',true);assert.equal(c.values[7],2000);
  assert.ok(validKeys(DEFAULT_KEYS));assert.equal(validKeys([...DEFAULT_KEYS.slice(1),'Right']),false);
});
test('flight modes use actual low/high mapping, yaw wraps and tilt includes inverted state',()=>{
  assert.equal(switchPulse([6,0,0,0,1,0],1),1000);assert.equal(switchPulse([6,0,0,0,1,0],0),2000);
  assert.equal(switchPulse([4,0,0,0,0,1],0),null);
  assert.equal(wrap(270),-90);assert.equal(signed(null),'—');assert.ok(Math.abs(tilt(180,0)-180)<1e-8);
});
function kit(){
  const rows=new Map(),packets=[],group=(id,now,age)=>{const r=rows.get(id);return r&&now>=r.at&&now-r.at<=age?r.values:null;};
  const ctx={state:'connected',path:'USB',replay:false,link:{session:55,sendControl(v){packets.push([...v]);return true;}},model:{frames:rows,get:group}};
  let ready=false;
  function put(at,source=2,owner=55,armed=false,lock=false){
    rows.set(122,{at,values:[source,ready?source+1:0,false,false,ready,ready?8:0,20,owner,ready]});
    rows.set(120,{at,values:[armed,true,true,8,.004,2000,20,true,false,false]});
    rows.set(130,{at,values:[lock,!lock]});
    rows.set(136,{at,values:[false,2,2,'']});
  }
  return {ctx,rows,packets,put,qualify:()=>{ready=true;}};
}
test('sender requires fresh completed setup, matching owner and source; neutral frames precede editable channels',()=>{
  const k=kit(),c=new Controls(),errors=[];
  const tx=new CockpitSender(c,()=>k.ctx,s=>errors.push(s));
  try{
    k.put(100,0);assert.equal(currentGuard(k.ctx,100).canStart,false);
    k.put(100,2,12);assert.equal(currentGuard(k.ctx,100).canStart,false);
    k.put(100,2,55,false,true);assert.throws(()=>tx.start(100),/setup/);
    k.put(100);tx.start(100);assert.deepEqual(k.packets[0],NEUTRAL);
    c.values[4]=2000;tx.tick(200);assert.deepEqual(k.packets[1],NEUTRAL);
    k.qualify();k.put(300);tx.tick(300);assert.equal(tx.ready,false);
    k.put(370);tx.tick(370);assert.equal(tx.ready,true);assert.equal(k.packets.at(-1)[4],2000);assert.ok(tx.canArm(370));
    c.values[2]=1700;assert.equal(tx.canArm(370),false);
    k.put(400,2,999);tx.tick(400);assert.equal(tx.running,false);assert.equal(errors.length,1);
    assert.equal(c.values[2],1000);
  } finally{tx.stop();}
});
test('sender refuses a replay and stops on a delayed UI tick instead of catching up',()=>{
  const k=kit(),c=new Controls();k.put(0);const tx=new CockpitSender(c,()=>k.ctx,()=>{});
  try{
    k.ctx.replay=true;assert.throws(()=>tx.start(0));k.ctx.replay=false;
    tx.start(0);tx.tick(180);assert.equal(tx.running,false);assert.equal(k.packets.length,1);
  }finally{tx.stop();}
});
test('cancelling the sender while ARM checks are pending sends no subsequent ARM request',async()=>{
  const k=kit(),c=new Controls(),tx=new CockpitSender(c,()=>k.ctx,()=>{});
  let openSetup,commands=0;
  const at=performance.now();
  // All starting observations use the same monotonic browser timebase.
  k.qualify();k.put(at);tx.start(at);tx.ready=true;
  k.ctx.link.readGroup=()=>new Promise(resolve=>{openSetup=resolve;});
  k.ctx.link.action=async()=>{commands++;return ['ARMED'];};
  try{
    assert.ok(tx.canArm(performance.now()));
    const request=tx.arm();assert.equal(typeof openSetup,'function');
    tx.stop();openSetup([false,true]);await assert.rejects(request,/cancelled/);
    assert.equal(commands,0);
  }finally{tx.stop();}
});

test('Flight Data enables the browser sticks for its USB or AP input and monitors the physical radio',()=>{
  const k=kit(),view=source=>transmitterView(k.ctx,currentGuard(k.ctx,100),source);
  for(const [path,source] of [['USB',2],['AP',1]]){
    k.ctx.path=path;k.put(100,source);assert.equal(view(source),'local');
    k.put(100,source,81);assert.equal(view(source),'monitor');
    k.put(100,3-source);assert.equal(view(3-source),'monitor');
    k.put(100,0);assert.equal(view(0),'ppm');
  }
  k.rows.delete(122);assert.equal(view(1),'waiting');
  k.ctx.state='disconnected';assert.equal(view(null),'preview');
  k.ctx.replay=true;assert.equal(view(0),'replay');
});

test('Flight Data ARM needs fresh saved gains; a pending save leaves the neutral sender available',()=>{
  const k=kit(),c=new Controls(),tx=new CockpitSender(c,()=>k.ctx,assert.fail);
  try{
    k.qualify();k.put(100);tx.start(100);tx.ready=true;
    for(const receipt of [[true,2,1,''],[false,2,1,''],[false,2,2,'SAVE_FAILED']]){
      k.rows.set(136,{at:100,values:receipt});assert.equal(tx.canArm(100),false);assert.ok(tx.running);
    }
    k.rows.delete(136);assert.equal(tx.canArm(100),false);
    k.put(100);assert.ok(tx.canArm(100));k.rows.get(136).at=-450;assert.equal(tx.canArm(100),false);
    k.put(100);k.rows.get(120).values[7]=false;assert.equal(tx.canArm(100),false);
  }finally{tx.stop();}
});
