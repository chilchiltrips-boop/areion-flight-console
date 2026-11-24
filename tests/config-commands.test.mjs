import test from 'node:test';
import assert from 'node:assert/strict';
import {CockpitSender,Controls,NEUTRAL} from '../web/cockpit-controls.js';
import {SetupKit,saveFlightInput,receiverValues,defaults} from '../web/config-commands.js';

function kit(){
  const active=structuredClone(defaults), flash=structuredClone(defaults);
  active[120]=[false,true,true,8,.004,2000,2,true];active[110]=[0];active[136]=[false,1,1,''];
  active[130]=[false,true,0,4,15,true,true,false,false,1000,1000,1000,1000,2,'','A1'];
  const actions=[];
  const link={session:3,fcSession:9,
    readGroup:async(g,{saved}={})=>{const v=(saved?flash:active)[g];if(!v)throw Error('NOT_SAVED');return [...v];},
    setGroup:async(g,v)=>{active[g]=[...v];if(g===134)active[110]=[v[1]];},
    saveGroup:async g=>{flash[g]=[...active[g]];},
    action:async(g,v)=>{
      actions.push([g,...v]);const [name,num]=v,s=active[130];
      if(g===137){active[name]=v.slice(2,2+defaults[name].length).map(Math.fround);active[136]=[active[120][0],2,active[120][0]?1:2,''];if(!active[120][0])flash[name]=[...active[name]];return [active[120][0]?'PID_APPLIED_PENDING_SAVE':'PID_SAVED'];}
      if(name==='BEGIN'){s[0]=true;s[1]=false;s[2]=1;return ['SETUP_LOCKED'];}
      if(name==='FINALIZE'){s[0]=false;s[1]=true;s[2]=0;s[13]++;return ['SETUP_SAVED_ARM_AVAILABLE'];}
      if(name==='INPUT_SAVE'){active[134][1]=num;flash[134]=[...active[134]];active[110]=[num];return ['INPUT_SAVED'];}
      throw Error('unexpected command '+name);
    }
  };
  return {active,flash,link,actions};
}
test('source writes isolated selection, validates stored and active proof',async()=>{
 const {link,active,flash,actions}=kit(),original=structuredClone(active[130]);
 await saveFlightInput(link,2);assert.equal(active[134][1],2);assert.deepEqual(active[130],original);
 assert.deepEqual(actions,[[135,'INPUT_SAVE',2,0,0,0]]);
 const read=link.readGroup;link.readGroup=(g,opts)=>g===134&&opts.saved?Promise.resolve([...flash[134]].fill(0)):read(g,opts);
 await assert.rejects(saveFlightInput(link,1),/readback/);
});
test('first PPM selection inside setup and setup completion survive reconnect without replaying actions',async()=>{
 const {link,active,flash,actions}=kit(),op=new SetupKit(link);
 await op.begin();active[130][6]=false;active[110]=[2];
 await saveFlightInput(link,0,{wizard:true});assert.deepEqual(active[110],[0]);
 active[130][6]=true;active[130][3]=1;
 await op.begin();assert.equal(actions.filter(a=>a[1]==='BEGIN').length,1);
 active[130][3]=4;delete flash[4];
 const receipt=await op.finalize();assert.equal(receipt.setup[1],true);
 await assert.rejects(op.verifyRestart(receipt),/Restart/);
 link.fcSession=10;await new SetupKit(link).verifyRestart(receipt);
 flash[7][0]=8;await assert.rejects(new SetupKit(link).verifyRestart(receipt),/group 7/);
});
test('PID validates float32 gains, bench consent, storage and deferred status',async()=>{
 const {link,active,flash,actions}=kit(),op=new SetupKit(link),v=[...defaults[2]];v[6]=.0034578;
 assert.match(await op.pid(2,v,false),/saved and verified/);assert.equal(flash[2][6],Math.fround(v[6]));
 active[120][0]=true;await assert.rejects(op.pid(2,v,false),/Disarm/);
 assert.match(await op.pid(3,defaults[3],true),/save after disarm/);
 assert.deepEqual(actions.at(-1),[137,3,true,...defaults[3],0,0,0]);
});
test('lost lock or session, mismatched/unsaved readback never finalizes or reports success',async()=>{
 const {link,active,actions,flash}=kit(),op=new SetupKit(link);
 await assert.rejects(op.store(4,defaults[4]),/lock/);await op.begin();
 flash[7][0]=8;await assert.rejects(op.finalize(),/unsaved/);assert.equal(actions.some(a=>a[1]==='FINALIZE'),false);
 const original=link.setGroup;link.setGroup=async(g,v)=>{await original(g,v);link.session++;};
 const v=[...defaults[6]];v[0]=.22;await assert.rejects(op.store(6,v),/connection changed/);assert.notDeepEqual(active[6],flash[6]);
});
test('PPM sweep measures only real channels, requires low throttle and centered axes',()=>{
 const capture={samples:12,first:100,last:2400,count:4,min:[1000,1000,1000,1000],max:[2000,2000,2000,2000]};
 const raw=[1480,1520,1007,1490,0,0,0,0,4,true,5],map=[1,2,3,4];
 const v=receiverValues(capture,raw,defaults[132],map);
 assert.deepEqual(v.slice(0,12),[1000,1480,2000,0,1000,1520,2000,0,1000,1500,2000,0]);
 raw[2]=1900;assert.throws(()=>receiverValues(capture,raw,defaults[132],map),/throttle/i);
});
test('a reset acknowledgement without factory readbacks is rejected',async()=>{
 const {link,active,flash,actions}=kit(),op=new SetupKit(link);await op.begin();
 link.action=async(g,v)=>{actions.push([g,...v]);Object.assign(active[130],{3:0,4:0,5:false,6:false,7:false,8:false});return ['RESET_DEFAULTS_SAVED'];};
 flash[4][4]=14;
 await assert.rejects(op.reset(),/could not be verified for group 4/);assert.equal(active[130][0],true);
});
test('cancelling before store cannot issue SET or SAVE after a delayed status reply',async()=>{
 const {link}=kit();let cancelled=false;
 const op=new SetupKit(link,()=>{if(cancelled)throw Error('Cancelled');});await op.begin();
 const old=link.readGroup;link.readGroup=async(g,o)=>{const v=await old(g,o);if(g===130)cancelled=true;return v;};
 link.setGroup=async()=>assert.fail('cancelled operation issued SET');link.saveGroup=async()=>assert.fail('cancelled operation issued SAVE');
 await assert.rejects(op.store(6,[.04,.02,.01]),/Cancelled/);
});
test('suspending a motor test releases its lease, with emergency DISARM taking precedence',async()=>{
 const {ConfigPanel}=await import('../web/config-panel.js'),calls=[];
 const node={addEventListener(){},querySelector(){return null;}},local={clearCaptures(){},state(){return {};}};
 const p=new ConfigPanel(node,local),l={session:5,action:async(g,v)=>{calls.push([g,...v]);return ['STOPPED'];}};
 p.motor={link:l,session:5,timer:0};p.pulse=1150;p.suspend();
 assert.deepEqual(calls,[[135,'MOTOR_STOP',0,0,0,0]]);assert.equal(p.motor,null);assert.equal(p.pulse,1000);
 p.motor={link:l,session:5,timer:0};p.suspend({emergency:true});assert.equal(calls.length,1);
 p.motor={link:l,session:2,timer:0};p.suspend();assert.equal(calls.length,1);
});
test('disconnect can wait for the same motor stop after a focus change',async()=>{
 const {ConfigPanel}=await import('../web/config-panel.js');
 const root={addEventListener(){},querySelector(){return null;}};
 const panel=new ConfigPanel(root,{clearCaptures(){}});
 let confirm;
 const link={session:7,action:()=>new Promise(resolve=>{confirm=resolve;})};
 panel.motor={link,session:7,timer:0};
 const first=panel.suspend();
 assert.ok(first instanceof Promise);
 assert.equal(panel.suspend(),first);
 confirm(['STOPPED']);
 await first;
 assert.equal(panel.suspend(),null);
});

test('a saved kit accepts an explicit Flight Data test over its selected USB or AP path',async()=>{
  for(const [path,source] of [['USB',2],['AP',1]]){
    const {active,flash,link}=kit(),op=new SetupKit(link);
    const gains=[...defaults[2]];gains[0]=1.8;
    assert.match(await op.pid(2,gains,false),/saved and verified/);
    await saveFlightInput(link,source);
    let armedCommands=0;const calls=[],controls=new Controls();
    const configAction=link.action;
    link.action=async(group,values)=>{
      if(group!==123)return configAction(group,values);
      assert.deepEqual(values,['ARM']);armedCommands++;active[120][0]=true;return ['ARMED'];
    };
    link.sendControl=(v,sent)=>{calls.push([...v]);sent();return true;};
    const start=performance.now()-270,rows=new Map();
    const ctx={state:'connected',path,link,replay:false,model:{frames:rows,
      get(id,now,age){const r=rows.get(id);return r&&now>=r.at&&now-r.at<age?r.values:null;}}};
    function telemetry(at,ready){
      for(const g of [120,130,136])rows.set(g,{at,values:active[g]});
      rows.set(122,{at,values:[source,ready?source+1:0,false,ready&&source===1,ready,ready?8:0,2,link.session,ready&&source===2]});
    }
    const tx=new CockpitSender(controls,()=>ctx,assert.fail);
    try{
      telemetry(start,false);tx.start(start);
      for(const offset of [100,200,260]){telemetry(start+offset,true);tx.tick(start+offset);}
      assert.ok(tx.ready);assert.equal(armedCommands,0);
      assert.ok(calls.every(v=>v.every((x,i)=>x===NEUTRAL[i])));
      await tx.arm();assert.equal(armedCommands,1);
      controls.stick(false,.5,-.25,true);const now=performance.now();telemetry(now,true);tx.tick(now);
      assert.deepEqual(calls.at(-1).slice(0,4),[1750,1375,1000,1500]);
      assert.equal(flash[2][0],Math.fround(1.8));assert.equal(active[130][1],true);
    }finally{tx.stop();}
  }
});
