import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {Instruments} from '../web/instruments.js';
import {healthReadout} from '../web/flight-extra.js';
test('desktop airframe mesh retains the original geometry and materials',()=>{
  const asset=x=>readFileSync(new URL('../web/assets/airframes/'+x,import.meta.url),'utf8');
  const mesh=asset('areion450.obj').split('\n');
  const vertices=mesh.filter(l=>l.startsWith('v ')), faces=mesh.filter(l=>l.startsWith('f '));
  assert.ok(vertices.length>100 && faces.length>100);
  for(const f of faces) assert.ok(f.slice(2).trim().split(/\s+/).every(v=>+v>=1 && +v<=vertices.length));
  for(const use of new Set(mesh.filter(l=>l.startsWith('usemtl ')))) assert.ok(asset('areion.mtl').includes(use.replace('usemtl','newmtl')));
});
test('cockpit health distinguishes offline, missing input, and an explicit output fault',()=>{
 const m=new Instruments();let now=100;
 const group=(g,age=Infinity)=>m.get(g,now,age);
 const s=()=>healthReadout(m.snapshot(now),group,true);
 assert.equal(healthReadout(m.snapshot(now),group,false).TELEMETRY.level,'bad');
 m.push({group:120,values:[false,true,true,0,.004,20,32,true,false,false],at:now});
 m.push({group:122,values:[0,0,false,false,false,0,0,0,false],at:now});
 assert.equal(s().PPM.level,'warn');assert.equal(s().AP.level,'idle');
 m.push({group:136,values:[true,2,1,'NVS_WRITE_FAILED'],at:now});
 assert.deepEqual(s().CONFIG,{label:'Save error',level:'bad'});
 const setup=Array(16).fill(0);setup[14]='MOTOR_OUTPUT_FAILED';
 m.push({group:130,values:setup,at:now});assert.equal(s().OUTPUT.level,'bad');
 now=601;assert.equal(s().TELEMETRY.level,'warn');
});
