import test from 'node:test';
import assert from 'node:assert/strict';
import {defaults} from '../web/config-commands.js';
import {ConfigPanel} from '../web/config-panel.js';
import {Instruments} from '../web/instruments.js';
import {parseCsv,serialize} from '../web/records.js';
import {packGains,unpackGains} from '../web/tripod/gains.js';
import {bindSticks, SimulatorInput} from '../web/tripod/inputs.js';
import {TripodRecording,tripodSession,tripodTelemetry} from '../web/tripod/telemetry.js';
import {DEFAULT_PID,STEP,controlSettings,createSimulator,motorMix,setFlightMode,setPID,setSimulatorGains,
  startSimulator,stepSimulator} from '../web/tripod/tripod-physics.js';
import {simulateResponse} from '../web/tripod/tripod-experiments.js';

import {Euler,Vector3} from '../web/assembly/three.module.min.js';
import {setPilotAttitude} from '../web/tripod/scene.js';
import {stickPoint} from '../web/stick-geometry.js';

const row=(group,values,at)=>({group,values,at});
const status=[false,true,true,8,.004,2000,3600,true,false,false];
const setup=[false,true,7,4,15,true,true,false,false,1000,1000,1000,1000,1,'','A1-kit'];
const rx=[0,1,true,false,true,8,70,0,false];
const channels=[1600,1450,1000,1550,1000,1000,1500,1500];
const imu=[1,2,3,0,0,1,4,5,6,7];
const outputs=[10,20,30,1120,1240,1360,1480,11,12,13,14,15];
function context() {
  const model=new Instruments();
  for(const [id,val] of [[2,defaults[2]],[3,defaults[3]],[7,defaults[7]],[112,[250,250]],
    [120,status],[130,setup],[122,rx],[22,channels],[21,imu],[23,outputs]])model.push(row(id,val,1000));
  return {path:'USB',state:'connected',replay:false,link:{session:15,fcSession:42},model,
    clock:1010,snapshot:model.snapshot(1010)};
}

test('virtual PID banks round-trip A1 term-major groups and share their limits and defaults',()=>{
  assert.deepEqual(packGains(DEFAULT_PID,2),defaults[2]);
  assert.deepEqual(packGains(DEFAULT_PID,3),defaults[3]);
  const rate=[1,2,3,200,300,400,.11,.12,.13],angle=[4,5,123,321,1,2];
  const gains=unpackGains(rate,angle);
  assert.deepEqual(gains.ratePitch,{p:2,i:300,d:.12});
  assert.deepEqual(gains.anglePitch,{p:5,i:321,d:2});
  assert.deepEqual(packGains(gains,2),rate);
  assert.deepEqual(packGains(gains,3),angle);
  assert.equal(unpackGains(rate.slice(1),angle),null);
  assert.equal(unpackGains(rate,[4,5,123,321,1,21]),null);
  assert.equal(packGains(gains,137),null);
});

test('A1 throttle cutoff, motor order, pulse limits and stick scales drive the virtual plant',()=>{
  assert.deepEqual(motorMix(1500,20,30,40),[1530,1410,1550,1510]);
  const sim=createSimulator();
  sim.environment.gyroNoise=0;
  assert.ok(startSimulator(sim));
  sim.throttle=1049;
  stepSimulator(sim);
  assert.deepEqual(sim.motorCommands,[0,0,0,0]);
  sim.throttle=1050;
  stepSimulator(sim);
  assert.deepEqual(sim.motorCommands,[18,18,18,18]);
  sim.throttle=2000;
  stepSimulator(sim);
  assert.deepEqual(sim.motorCommands,[80,80,80,80]);
  sim.cmdRoll=1;sim.cmdPitch=-.5;sim.cmdYaw=.5;
  stepSimulator(sim);
  assert.equal(sim.targetRoll,50);assert.equal(sim.targetPitch,-25);assert.equal(sim.targetYawRate,37.5);
  setFlightMode(sim,'acro');stepSimulator(sim);
  assert.equal(sim.targetRollRate,75);assert.equal(sim.targetPitchRate,-37.5);
  sim.settings=controlSettings([5,.2,.25,.5,0,1],[1200],[0,0,1,2,3,4,5,1100,1150,1200,1250]);
  stepSimulator(sim);
  assert.equal(sim.targetRollRate,125);assert.equal(sim.targetYawRate,125);
  assert.ok(Math.abs(sim.time-6*STEP)<1e-12);
});

test('A/B uses the same deterministic virtual experiment on each selected axis',()=>{
  for(const [axis,bank] of [['roll','angleRoll'],['pitch','ratePitch'],['yaw','rateYaw']]){
    const opts={axis,bank,values:[.6,1.6],duration:2};
    const [a,b]=simulateResponse(opts).results;
    assert.ok(a.samples.some(s=>s.target>1));
    assert.ok(a.samples.every(s=>Number.isFinite(s.actual)));
    assert.notEqual(a.metrics.rms,b.metrics.rms);
    assert.deepEqual(simulateResponse(opts).results[0],a);
  }
  assert.throws(()=>simulateResponse({gain:'d',values:[1,30]}));
});

test('tripod telemetry uses accepted input and original FC IMU, control output and target groups',()=>{
  const ctx=context(),kit=tripodTelemetry(ctx);
  assert.equal(kit.session,'USB/15/42');
  assert.equal(kit.kit,'A1-kit');assert.equal(kit.input.source,'PPM');
  assert.deepEqual(kit.input.channels,channels.slice(0,4));assert.equal(kit.input.until,1180);
  assert.deepEqual(kit.rates,[1,2,3]);assert.deepEqual(kit.attitude,{roll:6,pitch:7,yaw:0});
  assert.deepEqual(kit.motors,outputs.slice(3,7));
  assert.deepEqual(kit.targets,{rate:[11,12,13],angle:[14,15]});
  assert.equal(tripodTelemetry(ctx,1180).input,null);
  ctx.model.push(row(130,[true,...setup.slice(1)],1181));
  assert.equal(tripodTelemetry(ctx,1181).targets,null);
  assert.equal(tripodTelemetry(ctx,1510).attitude,null);
  assert.equal(tripodTelemetry(ctx,1510).motors,null);
  for(const patch of [{replay:true},{state:'stale'},{link:{fcSession:42,session:0}}]){
    assert.equal(tripodSession({...ctx,...patch}),null);
    assert.equal(tripodTelemetry({...ctx,...patch}),null);
  }
});

test('live receiver mirroring needs fresh low throttle; signal and session changes stop simulation',()=>{
  const ctx=context(),kit=tripodTelemetry(ctx),sim=createSimulator(),input=new SimulatorInput(sim);
  input.source='receiver';
  assert.match(input.start({...kit,input:{...kit.input,channels:[1500,1500,1650,1500]}},1010),/Lower throttle/);
  assert.equal(input.start(kit,1010),'');input.sample(kit,1010);
  assert.deepEqual([sim.cmdRoll,sim.cmdPitch,sim.cmdYaw],[.2,-.1,.1]);
  setPID(sim,'rateRoll',{p:2,i:300,d:.04});
  assert.match(input.sample(kit,1181),/Receiver lost/);
  assert.equal(sim.running,false);assert.deepEqual(sim.motorRPM,[0,0,0,0]);
  assert.equal(sim.pid.rateRoll.i,300);
  assert.equal(input.start(kit,1010),'');
  assert.match(input.sample({...kit,input:{...kit.input,identity:'USB/15/88/PPM/0'}},1011),/changed/);
});

test('bench recordings preserve original packet times and stop at ten seconds or loss of session',()=>{
  const ctx=context(),kit=tripodTelemetry(ctx),capture=new TripodRecording();
  ctx.model.push(row(6,defaults[6],400));
  assert.equal(capture.start({clock:ctx.clock,frames:ctx.model.frames},kit),true);
  assert.equal(capture.rows.some(r=>r.group===6),false);
  capture.packet(row(23,outputs,1050),kit.session);
  capture.packet(row(21,imu,11010),kit.session);
  capture.packet(row(21,imu,11011),kit.session);
  assert.equal(capture.message,'Capture complete');assert.equal(capture.session,null);
  const parsed=parseCsv(serialize(capture.rows));
  assert.deepEqual(parsed.at(-1).values,imu);
  assert.equal(parsed.at(-1).at,10010);
  capture.start({clock:ctx.clock,frames:ctx.model.frames},kit);
  capture.update(1080,null);assert.equal(capture.message,'Telemetry interrupted');
  capture.start({clock:ctx.clock,frames:ctx.model.frames},kit);
  const count=capture.rows.length;
  capture.packet(row(21,imu,1050),'AP/99/8');
  assert.equal(capture.rows.length,count);assert.equal(capture.message,'Kit changed');
  assert.equal(capture.start(ctx,null),false);
});

test('copying virtual gains stages only the selected FC axis without issuing a link command',()=>{
  const values=[1,2,3,4,5,6,.1,.2,.3];
  const panel={live:true,busy:false,motor:null,base:new Map(),draft:new Map(),confirm:new Set(),
    ctx:{group:id=>defaults[id]},info(){},refresh(){}};
  ConfigPanel.prototype.stagePid.call(panel,2,values,0);
  assert.deepEqual(panel.base.get(2),defaults[2]);
  assert.deepEqual([...panel.draft.values()],[1,4,.1]);
  const changedElsewhere=[...defaults[2]];changedElsewhere[2]=4;
  const merged=ConfigPanel.prototype.snapshot.call(panel,2,changedElsewhere);
  assert.equal(merged[2],4);assert.equal(merged[1],defaults[2][1]);assert.equal(merged[0],1);
  panel.confirm.add('axis-2');
  ConfigPanel.prototype.stagePid.call(panel,2,values,1);
  assert.equal(panel.draft.get('2:0'),2);assert.equal(panel.draft.get('2:1'),2);
  const conflict=[...defaults[2]];conflict[0]=7;
  assert.throws(()=>ConfigPanel.prototype.snapshot.call(panel,2,conflict),/changed/);
  assert.equal(panel.base.has(3),false);
  panel.busy=true;ConfigPanel.prototype.stagePid.call(panel,3,defaults[3],1);
  assert.equal(panel.base.has(3),false);
});

test('dual pointer gimbals keep independent endpoints, absolute throttle, and spring return',t=>{
  class Pad extends EventTarget {
    constructor(side,left){super();this.dataset={pad:side};this.left=left;}
    getBoundingClientRect(){return {left:this.left,top:0,width:100,height:100};}
    focus(){}
    setPointerCapture(id){this.capture=id;}
    hasPointerCapture(id){return id===this.capture;}
    releasePointerCapture(){this.capture=null;}
    send(type,id,x,y){this.dispatchEvent(Object.assign(new Event(type,{cancelable:true}),{pointerId:id,button:0,clientX:x,clientY:y}));}
  }
  const left=new Pad('left',0),right=new Pad('right',120);
  const root={isConnected:true,closest:()=>null,querySelectorAll:()=>[left,right]};
  const oldDoc=globalThis.document,oldWindow=globalThis.window;
  globalThis.window=new EventTarget();globalThis.document={hidden:false,querySelector:()=>null};
  t.after(()=>{if(oldWindow)globalThis.window=oldWindow;else delete globalThis.window;
    if(oldDoc)globalThis.document=oldDoc;else delete globalThis.document;});
  const sim=createSimulator(),abort=new AbortController();
  t.after(()=>abort.abort());
  let local=true,redraws=0;
  const controls=bindSticks(root,sim,()=>local,abort.signal,()=>{},()=>redraws++);
  left.send('pointerdown',10,90,90);right.send('pointerdown',12,210,10);
  assert.deepEqual([sim.throttle,sim.cmdYaw,sim.cmdRoll,sim.cmdPitch],[1000,1,1,1]);
  left.send('pointermove',10,10,30);right.send('pointermove',99,170,50);
  for(let i=0;i<200;i++)controls.update(.016);
  assert.deepEqual([sim.throttle,sim.cmdYaw,sim.cmdRoll,sim.cmdPitch],[1750,-1,1,1]);
  left.send('pointerup',10,10,30);
  assert.deepEqual([sim.throttle,sim.cmdYaw,sim.cmdRoll,sim.cmdPitch],[1750,0,1,1]);
  right.send('pointercancel',99,170,50);assert.equal(sim.cmdRoll,1);
  right.send('pointercancel',12,170,50);assert.equal(sim.cmdRoll,0);assert.equal(sim.cmdPitch,0);
  root.closest=()=>({hidden:true});
  right.send('pointerdown',15,210,10);assert.equal(sim.cmdRoll,0);
  root.closest=()=>null;local=false;left.send('pointerdown',16,90,10);assert.equal(sim.throttle,1750);
  assert.ok(redraws>=5);
  assert.deepEqual(stickPoint({left:0,top:0,width:200,height:100},132,18,.32),{x:1,y:1});
});

test('virtual Run supplies the labelled bench throttle and signed sticks move all three axes',()=>{
  for(const flight of ['angle','acro'])for(const sign of [-1,1]){
    const s=createSimulator(),input=new SimulatorInput(s);
    s.environment.gyroNoise=0;
    assert.equal(input.start(null,0),'');assert.equal(s.throttle,1500);setFlightMode(s,flight);
    s.cmdRoll=.30*sign;s.cmdPitch=-.20*sign;s.cmdYaw=.42*sign;
    for(let i=0;i<140;i++)stepSimulator(s);
    assert.ok(s.roll*sign>1 && -s.pitch*sign>1 && s.yaw*sign>1);
    assert.equal(s.targetYawRate,31.5*sign);
    if(flight==='angle'){assert.equal(s.targetRoll,15*sign);assert.equal(s.targetPitch,-10*sign);}
    else {assert.equal(s.targetRollRate,22.5*sign);assert.equal(s.targetPitchRate,-15*sign);}
    const before=Math.abs(s.roll);
    s.cmdRoll=s.cmdPitch=s.cmdYaw=0;
    for(let i=0;i<650;i++)stepSimulator(s);
    if(flight==='angle')assert.ok(Math.abs(s.roll)<before*.25);
    else assert.ok(Math.abs(s.roll)>before*.70 && Math.abs(s.rollRate)<2);
    s.throttle=1000;stepSimulator(s);assert.deepEqual(s.motorCommands,[0,0,0,0]);
  }
});

test('pilot view lowers the commanded wing and nose and yaws right with a right command',()=>{
  const rot=new Euler(),right=new Vector3(1,0,0),front=new Vector3(0,0,-1);
  setPilotAttitude(rot,{roll:20,pitch:0,yaw:0});assert.ok(right.clone().applyEuler(rot).y<0);
  setPilotAttitude(rot,{roll:0,pitch:20,yaw:0});assert.ok(front.clone().applyEuler(rot).y<0);
  setPilotAttitude(rot,{roll:0,pitch:0,yaw:20});assert.ok(front.clone().applyEuler(rot).x>0);
});

test('whole gain matrices validate before staging and become active together on the virtual control tick',()=>{
  const s=createSimulator();startSimulator(s);
  const all=structuredClone(DEFAULT_PID);
  all.rateRoll.p=1.23;all.ratePitch.i=30;all.rateYaw.d=.05;all.anglePitch.d=1.2;
  const bad=structuredClone(all);bad.anglePitch.d=21;
  assert.equal(setSimulatorGains(s,bad),false);assert.deepEqual(s.pendingPID,{});
  assert.ok(setSimulatorGains(s,all));assert.deepEqual(s.pid,DEFAULT_PID);
  stepSimulator(s);assert.deepEqual(s.pid,all);
  const response=simulateResponse({mode:'angle',readLoop:'rate',axis:'pitch',bank:'ratePitch',duration:2});
  assert.ok(response.results[0].samples.some(row=>Math.abs(row.target)>1));
  assert.ok(response.results[0].samples.every(row=>row.actual===row.measuredRate&&row.target===row.outerRate));
});

test('PPM and AP follow their own fresh TRPY data over either connection; a new AP owner needs new channels',()=>{
  for (const path of ['USB','AP']){
    const ctx=context();ctx.path=path;
    const sim=createSimulator(),ap=new SimulatorInput(sim,'AP'),ppm=new SimulatorInput(createSimulator(),'PPM');
    assert.match(ap.start(tripodTelemetry(ctx),1010),/Waiting/);
    const config=[...defaults[134]],endpoints=[...defaults[132]];
    config.splice(2,4,2,1,3,4);endpoints[7]=1;
    for(const [group,values] of [[134,config],[132,endpoints],[7,[6,.1,.15,.15,1,0]],
      [122,[1,2,true,true,true,8,6,86,false]],[22,[1750,1200,1000,1650,1000,1800,1500,1500]],
      [131,[1400,1800,1000,1504,1000,1900,1500,1500,8,true,10]]])ctx.model.push(row(group,values,1020));
    const kit=tripodTelemetry(ctx,1021);
    assert.equal(ap.start(kit,1021),'');
    assert.deepEqual([sim.cmdRoll,sim.cmdPitch,sim.cmdYaw],[.5,-.6,.3]);
    const radio=ppm.receiver(kit,1021);assert.deepEqual(radio.channels,[1200,1400,1000,1500]);
    assert.equal(radio.mode,'angle');assert.ok(radio.identity.endsWith('PPM/0'));
    ctx.model.push(row(131,[1400,1800,1000,1504,1000,1200,1500,1500,8,true,10],1040));
    assert.equal(ppm.receiver(tripodTelemetry(ctx,1042),1042).mode,'acro');
    ctx.model.push(row(122,[1,2,true,true,true,8,0,99,false],1050));
    assert.equal(tripodTelemetry(ctx,1051).input,null);
    assert.match(ap.sample(tripodTelemetry(ctx,1051),1051),/Receiver lost/);
    assert.equal(sim.running,false);
    ctx.model.push(row(22,[1900,1800,1500,1200,1500,1900,1500,1500],1060));
    assert.match(ap.start(tripodTelemetry(ctx,1061),1061),/Lower throttle/);
    assert.equal(ppm.receiver(tripodTelemetry(ctx,1280),1280),null);
  }
});

test('staging a complete FC group preserves separate axes and detects external conflicting edits',()=>{
  const panel={live:true,busy:false,base:new Map(),draft:new Map(),confirm:new Set(['axis-2']),
    ctx:{group:id=>defaults[id]},info(){},refresh(){}};
  const values=[1,2,3,4,5,6,.1,.2,.3];
  ConfigPanel.prototype.stagePid.call(panel,2,values);
  assert.deepEqual(ConfigPanel.prototype.snapshot.call(panel,2,defaults[2]),values);
  assert.equal(panel.confirm.has('axis-2'),false);
  const conflict=[...defaults[2]];conflict[3]=1;
  assert.throws(()=>ConfigPanel.prototype.snapshot.call(panel,2,conflict),/changed/);
});
