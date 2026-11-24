import test from 'node:test';
import assert from 'node:assert/strict';
import {SensorCheck, StationaryCheck, poses} from '../web/calibration.js';
import {CalibrationSession} from '../web/calibration-session.js';
import {encodeCommand,matchesAck,validGroup} from '../web/protocol.js';
import {SetupProgress} from '../web/setup-progress.js';

const previous=[-.10,.03,.12], bias=[.08,-.03,-.09], flat=[0,0,1];
const reported=pose=>pose.map((v,i)=>v+bias[i]+previous[i]);
function hold(start,accept,acc,rates=[.11,-.13,.09]){
  for(let i=0;i<=30;i++)accept([...rates,...acc],start+100*i);
}
function almost(actual,expected){
  assert.ok(actual.every((v,i)=>Math.abs(v-expected[i])<1e-8),JSON.stringify(actual));
}

test('flat capture uses additive FC offsets once, requires top up and rejects a moving frame',()=>{
  const sensor=new SensorCheck();assert.ok(sensor.start(0,previous,'level'));
  const receive=(v,t)=>sensor.sample(v,t);
  hold(0,receive,reported([1,0,0]));assert.equal(sensor.ready,false);
  hold(3100,receive,reported(flat),[0,6,0]);assert.equal(sensor.faces.size,0);
  hold(6200,receive,reported(flat));assert.equal(sensor.ready,true);assert.equal(sensor.faces.size,1);
  almost(sensor.offsets,bias.map(v=>-v));assert.ok(sensor.levelError>0);
});

test('a paused six-face session keeps finished positions and can recapture one face',()=>{
  const session=new CalibrationSession(),setup=[true,false,1,0,0,false,false,false,false,0,0,0,0,2,'','A1'];
  const rows={6:previous,21:[0,0,0,...reported(flat)],120:[false,true,true,8,.004,2000,0,true],130:setup};
  const ctx={state:'connected',link:{session:1,fcSession:2},model:{get:g=>rows[g]}},controls={confirmed:true,entered:true};
  session.start(ctx,previous,'A1',0);
  const receive=(values,at)=>session.onPacket({group:21,event:true,values,at},ctx,controls);
  hold(0,receive,reported(flat));
  session.stop();assert.equal(session.sensor.resumable,true);
  session.resume(ctx,controls,3200);
  let now=3200;
  for(const [,axis,sign] of poses.slice(1)){
    hold(now,receive,reported(flat.map((_,i)=>i===axis?sign:0)));now+=3100;
  }
  assert.equal(session.sensor.ready,true);
  const kept=session.sensor.faces.get(0);
  session.repeatFace(3,ctx,controls,now);assert.equal(session.sensor.faces.size,5);
  hold(now,receive,reported(flat));assert.equal(session.sensor.faces.size,5);
  hold(now+3100,receive,reported([0,-1,0]));assert.equal(session.sensor.ready,true);
  assert.equal(session.sensor.faces.get(0),kept);almost(session.sensor.offsets,bias.map(v=>-v));
  session.repeatFace(2,ctx,controls,now+6200);session.stop();ctx.link.fcSession++;
  assert.throws(()=>session.resume(ctx,controls,now+6300));assert.equal(session.sensor.faces.size,0);
});

test('read-only level and drift checks use distinct live stationary frames and can report a failed check',()=>{
  const ctx={link:{session:1,fcSession:2},state:'connected'};
  for(const [type,acc,rates,expected] of [
    ['level',flat,[0,0,0],'verified'],['level',[.12,0,.993],[0,0,0],'failed'],
    ['gyro',[0,1,0],[.1,-.2,.3],'verified'],['gyro',flat,[1.2,0,0],'failed']
  ]){
    const check=new StationaryCheck(type);check.start(ctx,0);
    hold(0,(values,at)=>check.sample({group:21,event:false,at,values}),acc,rates);
    assert.equal(check.window.count,0);
    hold(0,(values,at)=>check.sample({group:21,event:true,at,values}),acc,rates);
    assert.equal(check.phase,expected);
    assert.equal(check.same({...ctx,link:{session:1,fcSession:2}}),false);
  }
  const check=new StationaryCheck();check.start(ctx,0);
  check.sample({group:21,event:true,at:501,values:[0,0,0,...flat]});assert.equal(check.phase,'stopped');
});

test('wizard ticks use the connected kit, saved readback and reboot-specific verification',async()=>{
  const p=new SetupProgress(),setup=[true,false,1,0,0,false,false,false,false,0,0,0,0,3,'','A1'];
  const rows={134:[1,1],4:[2],7:[3],112:[4]},flash={...rows,134:[0,1]};
  const ctx={state:'connected',link:{fcSession:8,session:3,readGroup:async id=>flash[id]},group:g=>rows[g]};
  for(let i=0;i<4;i++){p.observe(ctx,setup,false);await new Promise(resolve=>setImmediate(resolve));}
  let states=p.steps(ctx,setup,true,true,false);
  assert.deepEqual(states,['Confirmed','','Input saved','','Not used','','','Settings saved','','']);
  setup[5]=true;assert.equal(p.steps(ctx,setup,true,true,false)[3],'ACC verified');
  assert.equal(p.steps(ctx,setup,true,true,true)[3],'');
  setup[1]=true;setup[0]=false;p.verifiedRestart(3);
  assert.equal(p.steps(ctx,setup,true,false,false)[9],'Restart verified');
  assert.ok(p.steps({...ctx,state:'offline'},setup,true,false,false).every(v=>!v));
  ctx.link.fcSession++;p.observe(ctx,setup,true);assert.equal(p.steps(ctx,setup,true,false,false)[9],'');
});

test('manual gyro uses protocol v2 actions and accepts only matching acknowledgements',()=>{
  for(const [command,confirm,ack] of [['GYRO_ZERO',1,'GYRO_STARTED'],['GYRO_CANCEL',0,'GYRO_STOPPED']]){
    const values=[command,confirm,0,0,0];
    assert.ok(encodeCommand('ACTION',135,11,1,values).length>0);
    assert.ok(matchesAck({type:'ACTION',group:135,values},{type:'ACK',data:[ack]}));
    assert.ok(!matchesAck({type:'ACTION',group:135,values},{type:'ACK',data:['SETUP_UPDATED']}));
  }
  assert.ok(validGroup(142,1,[2,750,750,1,'Verified for this boot',-.5,0,.25]));
});
