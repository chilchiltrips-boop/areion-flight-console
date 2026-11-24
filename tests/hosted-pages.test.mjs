import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,readdir,access,mkdtemp,rm} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import {relative,dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {connectionReadout} from '../web/system.js';
import {diagnostics} from '../web/analysis-common.js';
import {receiverReadout} from '../web/scopes.js';
import {mount as mountFirmware} from '../web/firmware.js';
import {ConsoleShell} from '../web/shell.js';

function sample(overrides={}){
  const groups=new Map([
    [120,{at:970,values:[false,true,true,8,.004,20,65535,true,false,false]}],
    [121,{at:900,values:[true,'192.168.4.1',8080,5000]}],
    [122,{at:995,values:[0,1,true,false,true,8,0,13,false]}],
    [134,{at:200,values:[0,0,3,4,2,1]}],
    [7,{at:200,values:[5,.1,.2,.2,0,1]}]
  ]);
  return {clock:1000,state:'connected',path:'AP',packetCount:6501,portLabel:'Areion A1',
    link:{session:22,fcSession:33,stats:{sent:17,received:184}},rows:[...groups.values()],model:{frames:groups},events:[],
    snapshot:{source:'PPM',channels:[1500,1500,1000,1500,1600,1500,1500,1500]},
    group(id,age=Infinity){const f=groups.get(id);return f && this.clock>=f.at && this.clock-f.at<=age?f.values:null;},...overrides};
}

test('System connection and diagnostics show the active path and total received packet count',()=>{
  const ctx=sample(), details=Object.fromEntries(connectionReadout(ctx));
  assert.equal(details.Transport,'AP Wi-Fi');assert.equal(details.Endpoint,'Areion A1');
  assert.equal(details['Latest FC report'],'30 ms ago');assert.equal(details['USB baud'],'—');
  assert.equal(details['Received packets'],(6501).toLocaleString());
  assert.equal(details['FC access point'],'192.168.4.1:8080 · UDP');
  const report=diagnostics(ctx);
  assert.equal(report.received_packets,6501);assert.equal(report.retained_packets,5);
  assert.equal(report.source,'ap');assert.equal(report.host_session,22);assert.ok(report.connected);
  assert.equal(report.fc_session,33);assert.deepEqual(report.link_frames,{tx:17,rx:184});
  const playback={...ctx,replay:true,state:'replay'};
  assert.equal(Object.fromEntries(connectionReadout(playback)).Endpoint,'—');
  assert.equal(diagnostics(playback).port,null);assert.equal(diagnostics(playback).host_session,null);assert.equal(diagnostics(playback).link_frames,null);
});

test('copy includes packets newer than the last repaint, keeps replay at its playhead and separates past sessions',()=>{
  const ctx=sample(), sensorReport={state:'review',max_fit_error_g:.18};
  ctx.sensorReport=()=>sensorReport;
  for(const id of [21,120,130])ctx.model.frames.set(id,{at:1060,values:[id]});
  const live=diagnostics(ctx,1090);
  for(const id of [21,120,130])assert.equal(live.groups[id].age_s,.03);
  assert.deepEqual(live.imu_calibration,sensorReport);
  const replay=diagnostics({...ctx,replay:true},8000);
  assert.equal(replay.groups[21],undefined);assert.equal(replay.imu_calibration,undefined);
  ctx.link.lastConnection={page:'configuration/imu',reason:'Kit WebSocket closed (code 1006).'};
  const offline=diagnostics({...ctx,state:'error'},1100);
  assert.equal(offline.host_session,null);assert.equal(offline.last_connection.page,'configuration/imu');
  assert.equal(offline.imu_calibration,undefined);
});

test('Scopes distinguishes physical PPM assignments from accepted logical slots and hides invalid frames',()=>{
  const ctx=sample();
  const accepted=receiverReadout(ctx,false);
  assert.equal(accepted[0].role,'Roll · CH3');assert.equal(accepted[4].role,'Mode · Rate / Acro');
  const values=[1010,1500,1520,1503,1100,1700,0,0,6,true,2];
  ctx.model.frames.set(131,{at:999,values});
  const physical=receiverReadout(ctx,true);
  assert.equal(physical[0].role,'Yaw');assert.equal(physical[2].role,'Roll');
  assert.equal(physical[4].role,'Mode · Angle');assert.equal(physical[7].value,null);
  values[7]=1550;
  assert.ok(receiverReadout(ctx,true).every(row=>row.value===null));
  const offline={...ctx,state:'offline'};
  assert.ok(receiverReadout(offline,false).every(row=>row.value===null));
});

test('the Assembly deep link activates its workspace and suspends it on return to Flight Data',t=>{
  const nodes=new Map();
  const node=id=>{
    if(!nodes.has(id))nodes.set(id,{hidden:false,textContent:'',classList:{toggle(){}},setAttribute(){},removeAttribute(){}});
    return nodes.get(id);
  };
  const assemblyNav={dataset:{route:'assembly'},classList:{toggle(){}},setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];}};
  const doc={body:{dataset:{}},getElementById:node,querySelectorAll:()=>[assemblyNav]};
  const originalDoc=globalThis.document,originalWindow=globalThis.window;
  globalThis.document=doc;globalThis.window={scrollTo(){}};
  t.after(()=>{if(originalDoc===undefined)delete globalThis.document;else globalThis.document=originalDoc;
    if(originalWindow===undefined)delete globalThis.window;else globalThis.window=originalWindow;});
  const seen=[];
  const shell=new ConsoleShell({select:page=>seen.push(page)});
  shell.modules.set('assembly',{show(){seen.push('show');},suspend(){seen.push('suspend');}});
  shell.show('#assembly');
  assert.equal(doc.title,'Assembly · Areion Flight Console');
  assert.equal(assemblyNav['aria-current'],'page');
  assert.equal(node('assembly-page').hidden,false);
  assert.equal(node('workspace-heading').hidden,true);
  shell.show('#flight');
  assert.equal(node('assembly-page').hidden,true);
  assert.equal(node('flight-page').hidden,false);
  assert.equal(assemblyNav['aria-current'],undefined);
  assert.deepEqual(seen,['show','assembly','suspend','flight']);
});

test('Firmware read uses native group 125 and ignores a response from the previous connection',async t=>{
  class Element {
    constructor(){this.children=[];this.textContent='';this.dataset={};this.classList={add(){}};}
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=items;this.textContent='';}
  }
  const nodes=new Map();
  const root=new Element();
  root.querySelector=selector=>{
    if(!nodes.has(selector))nodes.set(selector,new Element());
    return nodes.get(selector);
  };
  const original=globalThis.document;
  globalThis.document={createElement:()=>new Element()};
  t.after(()=>{if(original===undefined)delete globalThis.document;else globalThis.document=original;});
  const pane=mountFirmware(root), read=nodes.get('[data-read]'), note=nodes.get('.ac-note');
  const next=sample();let complete;
  next.link.readGroup=group=>{assert.equal(group,125);return new Promise(resolve=>complete=resolve);};
  pane.update(next);assert.equal(read.disabled,false);
  const pending=read.onclick();assert.ok(read.disabled);
  pane.update({...next,state:'offline',link:null});complete(['old']);await pending;
  assert.equal(note.textContent,'');assert.equal(read.disabled,true);
  next.link.readGroup=async group=>{assert.equal(group,125);return ['3.2.0'];};
  pane.update(next);await read.onclick();
  assert.match(note.textContent,/Received firmware 3\.2\.0/);
  pane.update({...next,replay:true,state:'replay'});assert.equal(read.disabled,true);
});

test('published entry points and nested page modules resolve their dependencies in the built release',async t=>{
  const web=await mkdtemp(resolve(tmpdir(),'areion-assets-'));
  t.after(()=>rm(web,{recursive:true,force:true}));
  execFileSync(process.execPath,[fileURLToPath(new URL('../scripts/build-pages.mjs',import.meta.url)),web]);
  const files=(await readdir(web,{recursive:true})).filter(name=>/\.(js|css|html)$/.test(name) && !name.endsWith('.min.js'));
  const targets=new Set();
  for(const file of files){
    const text=await readFile(resolve(web,file),'utf8');
    assert.doesNotMatch(text,/127\.0\.0\.1:18765|Start Areion\.command|browser_console\.py/,file+' has a desktop launch dependency');
    const patterns=[
      /(?:\bfrom\s+|\bimport\(\s*|\bimport\s+|new URL\(\s*)['"](\.\/[^'"\n]+\.[\w]+)['"]/g,
      /(?:src|href)=["'](\.\/[^"'#]+\.[\w]+)["']/g,
      /url\(\s*['"]?(\.\/[^)'"]+\.[a-z0-9]+)['"]?\s*\)/g
    ];
    for(const pattern of patterns)for(const [,target] of text.matchAll(pattern))targets.add(resolve(web,dirname(file),target));
  }
  assert.ok(targets.size>=20);
  for(const target of targets){assert.ok(!relative(web,target).startsWith('..'));await access(target);}
});
