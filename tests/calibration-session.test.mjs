import test from 'node:test';
import assert from 'node:assert/strict';
import {CalibrationSession} from '../web/calibration-session.js';
import {SetupKit} from '../web/config-commands.js';
import {poses} from '../web/calibration.js';

function kit(){
  const offsets=[-.1,.03,.12];
  const rows={
    6:[...offsets],21:[0,0,0,0,0,1,0,0,0,0],120:[false,true,true,8,.004,2000,1000,true],
    130:[true,false,1,0,0,true,false,false,false,1000,1000,1000,1000,3,'','A1']
  };
  const actions=[], flash={6:[...offsets]};
  const link={session:4,fcSession:9,
    readGroup:async(g,opt)=>[...(opt?.saved?flash:rows)[g]],
    setGroup:async(g,v)=>{rows[g]=v.map(Math.fround);rows[130][5]=false;},
    saveGroup:async g=>{flash[g]=[...rows[g]];},
    action:async(g,v)=>{actions.push([g,...v]);rows[130][5]=true;return ['SETUP_UPDATED'];}
  };
  const ctx={link,state:'connected',replay:false,model:{get:g=>rows[g]}};
  return {rows,actions,flash,link,ctx,controls:{entered:true,confirmed:true},op:new SetupKit(link)};
}
function simulate(session,fixture){
  let at=0;
  session.start(fixture.ctx,fixture.rows[6],fixture.rows[130][15],at);
  for (const [,axis,sign] of poses){
    const acc=fixture.rows[6].map((off,i)=>off+[.03,-.02,.01][i]+(axis===i?sign:0));
    for(let i=0;i<=30;i++)session.onPacket({at:at++*100,group:21,event:true,values:[.2,0,-.1,...acc]},fixture.ctx,fixture.controls);
  }
  assert.equal(session.sensor.ready,true);
}
test('calibration uses live event packets from its locked kit and rejects recording, reads, motor tests and replay',()=>{
  const session=new CalibrationSession(),f=kit();
  session.start(f.ctx,f.rows[6],'A1',0);
  for(let i=0;i<35;i++)session.onPacket({group:21,at:i*100,event:false,values:f.rows[21]},f.ctx,f.controls);
  assert.equal(session.sensor.faces.size,0);assert.equal(session.sensor.active.last,null);
  f.ctx.replay=true;session.onPacket({group:21,at:3600,event:true,values:f.rows[21]},f.ctx,f.controls);
  assert.equal(session.owner,null);
  f.ctx.replay=false;f.rows[130][8]=true;assert.match(session.gate(f.ctx,f.controls),/motor/i);
  f.rows[130][8]=false;f.rows[120][0]=true;assert.match(session.gate(f.ctx,f.controls),/Disarm/);
});
test('a stored sensor flag alone cannot save; completed capture is bound to boot, lock and baseline',async()=>{
  for(const change of [f=>f.link.fcSession++,f=>f.rows[130][15]='B',f=>f.rows[130][0]=false,f=>f.rows[6][0]+=.001]){
    const session=new CalibrationSession(),f=kit();
    await assert.rejects(session.save(f.op,f.ctx,f.controls),/six-position/);
    simulate(session,f);
    change(f);session.sync(f.ctx,f.controls);assert.equal(session.sensor.ready,false);
    await assert.rejects(session.save(f.op,f.ctx,f.controls),/six-position/);
    assert.equal(f.actions.length,0);
  }
});
test('accelerometer save accepts the MCU temporary IMU rebase and verifies persisted offsets and its exact sensor ACK',async()=>{
  const session=new CalibrationSession(),f=kit();
  simulate(session,f);
  const realRead=f.link.readGroup,realSet=f.link.setGroup;
  let recoveryReads=0;
  f.link.setGroup=async(...args)=>{await realSet(...args);f.rows[120][2]=false;};
  f.link.readGroup=async(g,opts)=>{
    if(g===120&&!f.rows[120][2]&&++recoveryReads===2)f.rows[120][2]=true;
    session.sync(f.ctx,f.controls);return realRead(g,opts);
  };
  await session.save(f.op,f.ctx,f.controls);
  assert.equal(recoveryReads,2);assert.equal(session.saved,true);assert.equal(f.rows[130][5],true);
  assert.deepEqual(f.actions,[[135,'SENSOR_OK',1,0,0,0]]);
  assert.deepEqual(f.flash[6],[-.03,.02,-.01].map(Math.fround));
});
test('after partial storage failure the same kit can retry, and a stale positive status cannot substitute for the acknowledgement',async()=>{
  const session=new CalibrationSession(),f=kit();simulate(session,f);
  const realSave=f.link.saveGroup;
  f.link.saveGroup=async()=>{throw Error('Storage busy');};
  await assert.rejects(session.save(f.op,f.ctx,f.controls),/Storage busy/);assert.equal(session.saved,false);
  assert.deepEqual(f.actions,[]);
  f.link.saveGroup=realSave;
  f.link.action=async()=>{f.rows[130][5]=true;return ['WRONG_ACK'];};
  await assert.rejects(session.save(f.op,f.ctx,f.controls),/not acknowledged/);assert.equal(session.saved,false);
  f.link.action=async()=>['SETUP_UPDATED'];
  await session.save(f.op,f.ctx,f.controls);assert.equal(session.saved,true);
});
test('the shared panel requires consent and a lock, then captures and saves from either sensor entry', async()=>{
  const {ConfigPanel}=await import('../web/config-panel.js');
  const oldDocument=globalThis.document;
  try {
    globalThis.document={hidden:false};
    for(const [page,step] of [['imu',0],['wizard',3]]){
      const session=new CalibrationSession(),f=kit(),consent={confirmed:false,entered:false};
      f.ctx.group=id=>f.rows[id];f.ctx.snapshot={imu:{roll:0,pitch:0,yaw:0}};
      const root={hidden:false,addEventListener(){},querySelector(){return null;},querySelectorAll(){return [];}};
      const panel=new ConfigPanel(root,{
        state:()=>({page,step,confirmed:consent.confirmed}),
        sensorVisible:()=>true,sensorControls:()=>consent,calibration:session
      });
      panel.refresh(f.ctx);
      assert.equal(!!panel.allowed('start-sensor'),false);
      consent.confirmed=true;consent.entered=panel.entered=true;
      assert.equal(!!panel.allowed('start-sensor'),true);
      await panel.run('start-sensor');
      assert.ok(session.sensor.active);
      assert.equal(!!panel.allowed('imu'),false);
      let at=session.sensor.active.started;
      for(const [,axis,sign] of poses){
        const acc=f.rows[6].map((off,i)=>off+(axis===i?sign:0));
        for(let i=0;i<=33;i++){
          session.onPacket({at,group:21,event:true,values:[0,0,0,...acc]},f.ctx,consent);at+=100;
        }
      }
      assert.equal(!!panel.allowed('imu'),true);
      await panel.run('imu');
      assert.equal(session.saved,true);
      assert.equal(!!panel.allowed('imu'),false);
      assert.equal(f.actions.length,1);
    }
  } finally {
    if(oldDocument===undefined)delete globalThis.document;
    else globalThis.document=oldDocument;
  }
});
