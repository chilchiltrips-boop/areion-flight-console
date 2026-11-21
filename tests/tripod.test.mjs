import test from 'node:test';
import assert from 'node:assert/strict';
import {defaults} from '../web/config-commands.js';
import {ConfigPanel} from '../web/config-panel.js';
import {Instruments} from '../web/instruments.js';
import {parseCsv,serialize} from '../web/records.js';
import {packGains,unpackGains} from '../web/tripod/gains.js';
import {SimulatorInput} from '../web/tripod/inputs.js';
import {TripodRecording,tripodSession,tripodTelemetry} from '../web/tripod/telemetry.js';
import {DEFAULT_PID,STEP,controlSettings,createSimulator,motorMix,setFlightMode,setPID,
  startSimulator,stepSimulator} from '../web/tripod/tripod-physics.js';
import {simulateResponse} from '../web/tripod/tripod-experiments.js';

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
