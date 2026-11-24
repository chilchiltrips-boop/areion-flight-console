import test from 'node:test';
import assert from 'node:assert/strict';
import {escInstruction,markEsc,resumeEsc} from '../web/esc-progress.js';
import {SetupKit} from '../web/config-commands.js';
import {ConfigPanel} from '../web/config-panel.js';
import {ControllerDiagnostics,diagnosticFile} from '../web/diagnostic-report.js';
import {DiagnosticHistory} from '../web/diagnostic-history.js';

const setup=(phase,kit='A1-one')=>[true,false,1,phase,0,true,true,false,false,1000,1000,1000,1000,1,'',kit];
const store=()=>{const items=new Map();return {getItem:k=>items.get(k),setItem:(k,v)=>items.set(k,v),removeItem:k=>items.delete(k)};};
test('controller ESC phases resume after reboot without a browser checkpoint; completed or reset kits start normally',()=>{
  const storage=store();
  for(const phase of [1,2,3,6])assert.equal(resumeEsc(setup(phase),storage),true);
  markEsc('A1-one',true,storage);
  assert.equal(resumeEsc(setup(4),storage),true);
  assert.equal(resumeEsc(setup(4,'A1-two'),storage),false);
  const complete=setup(4);complete[0]=false;complete[1]=true;
  assert.equal(resumeEsc(complete,storage),false);
  const reset=setup(0);reset[5]=false;
  assert.equal(resumeEsc(reset,storage),false);
  markEsc('A1-one',false,storage);assert.equal(resumeEsc(setup(4),storage),false);
});
test('ESC controls distinguish schedule, in progress, verify, explicit redo and outstanding prerequisites',()=>{
  const panel=Object.create(ConfigPanel.prototype),s=setup(0),cfg=[0,0];
  panel.ctx={state:'connected',link:{session:7},group:()=>cfg};
  panel.fresh=id=>id===130?s:id===120?[false,true,true]:[1];
  panel.local={state:()=>({confirmed:true})};panel.entered=true;panel.confirm=new Set(['compatible','tones']);
  for(const phase of [0,1,2,3,4,5,6]){
    s[3]=phase;assert.equal(!!panel.allowed('schedule'),[0,6].includes(phase));
    assert.equal(!!panel.allowed('verify-esc'),phase===3);
  }
  s[3]=4;panel.confirm.add('redo');assert.ok(panel.allowed('schedule'));
  s[6]=false;assert.equal(!!panel.allowed('schedule'),false);
  cfg[1]=1;assert.ok(panel.allowed('schedule'));
  panel.ctx.group=()=>null;assert.equal(!!panel.allowed('schedule'),false);
  assert.match(escInstruction(setup(3),cfg,false),/IMU/);
  const bad=setup(6);bad[14]='ESC_INTERRUPTED_RESTART_REQUIRED';assert.match(escInstruction(bad,cfg,true),/ESC_INTERRUPTED_RESTART_REQUIRED/);
});
test('a fresh ESC readback prevents duplicate scheduling even if the button was enabled before the state changed',async()=>{
  const s=setup(3),sent=[];
  const link={session:12,fcSession:34,
    readGroup:async g=>g===120?[false,0,true,0,0,2000,0,true]:g===130?s.slice():[0,0],
    action:async(g,cmd)=>{sent.push(cmd[0]);s[3]=cmd[0]==='ESC_VERIFY'?4:1;return ['SETUP_UPDATED'];}};
  const op=new SetupKit(link);
  await op.begin();assert.deepEqual(sent,[]);
  await assert.rejects(op.escAction('ESC_SCHEDULE'),/state changed/);
  await op.escAction('ESC_VERIFY');assert.deepEqual(sent,['ESC_VERIFY']);
  await assert.rejects(op.escAction('ESC_SCHEDULE'),/state changed/);
  await op.escAction('ESC_SCHEDULE',true);assert.deepEqual(sent,['ESC_VERIFY','ESC_SCHEDULE']);
});
test('setup phase and fault transitions are named once while every telemetry record is retained',()=>{
  const log=[],diagnostics=new ControllerDiagnostics(),packet=v=>diagnostics.packet({group:130,at:1,values:v},row=>log.push(row));
  packet(setup(1));packet(setup(1));packet(setup(2));
  const interrupted=setup(6);interrupted[14]='ESC_INTERRUPTED_RESTART_REQUIRED';packet(interrupted);
  assert.equal(log.filter(r=>r.kind==='telemetry').length,4);
  assert.equal(log.filter(r=>r.kind==='setup').length,3);
  assert.equal(log.at(-1).status,'error');assert.equal(log.at(-1).detail,interrupted[14]);
});
test('copy and CSV include over 5000 records from multiple sessions, protect Wi-Fi credentials, report storage failure and clear locally',async()=>{
  const history=new DiagnosticHistory(async()=>{throw Error('Storage denied');});
  for(let i=0;i<5401;i++)history.add({source:i<2000?'usb':'ap',host_session:i<2000?1:2,kind:'telemetry',group:22,values:[i]});
  history.add({kind:'operation',name:'ESC check',detail:'two, "tones"',status:'error',step:'ESC calibration'});
  history.add({kind:'reply',group:138,status:'ok',name:'private-name',detail:'private-name',values:['password-test-only']});
  history.add({kind:'reply',group:139,status:'error',values:['password-test-only']});
  const snapshot={app:'Areion',events:[],source:'ap',state:'offline'};
  const text=await (await diagnosticFile(history,snapshot,'json')).text(),report=JSON.parse(text);
  assert.equal(report.app,'Areion');assert.equal(report.history.records,5404);assert.equal(report.records.length,5404);
  assert.equal(report.records[0].host_session,1);assert.equal(report.records[5400].values[0],5400);
  assert.match(report.history.storage,/denied/);assert.doesNotMatch(text,/private-name|password-test-only/);
  const csv=await (await diagnosticFile(history,snapshot,'csv')).text();
  assert.match(csv,/timestamp_utc,source/);assert.match(csv,/"two, ""tones"""/);assert.doesNotMatch(csv,/password-test-only/);
  assert.equal(csv.split('\r\n').length,5407);
  await history.clear();const empty=JSON.parse(await (await diagnosticFile(history,snapshot,'json')).text());
  assert.equal(empty.history.records,0);
  const stale={...snapshot,events:[{time:1,message:'Cleared session'}],last_connection:{ended_at:new Date(1).toISOString()}};
  const after=JSON.parse(await (await diagnosticFile(history,stale,'json')).text());
  assert.deepEqual(after.events,[]);assert.equal(after.last_connection,undefined);
});
