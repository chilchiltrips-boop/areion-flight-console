import {test} from 'node:test';
import assert from 'node:assert/strict';
import {poses,SensorCheck} from '../web/calibration.js';

test('verifies all six real orientations and estimates additive raw offsets',()=>{
  const check=new SensorCheck();
  const baseline=[.1,0,.02],bias=[.05,-.04,.03];
  for(let j=0;j<poses.length;j++) {
    const t=4000*j, [,axis,sign]=poses[j];
    assert.ok(check.begin(j,t,baseline));
    const g=bias.map((b,i)=>(i===axis?sign:0)+b+baseline[i]);
    for(let k=0;k<=32;k++)check.sample([0,0,0,...g,0,0,0,0],t+k*100);
    assert.equal(check.faces.size,j+1);
  }
  bias.forEach((v,i)=>assert.ok(Math.abs(v+check.offsets[i])<1e-8));
});
test('rejects wrong orientation, moving kit, and duplicate-timestamp capture',()=>{
  const check=new SensorCheck();
  check.begin(0,0,[0,0,0]);check.sample([0,0,0,1,0,0],0);
  assert.match(check.note,/Orientation/);assert.equal(check.faces.size,0);
  check.begin('gyro',0,[0,0,0]);for(let i=0;i<40;i++)check.sample([.1,.2,.3,0,0,1],0);
  assert.equal(check.progress,0);
  check.sample([6,0,0,0,0,1],1);assert.equal(check.active,null);
  assert.match(check.note,/Movement/);
});
test('gyro residual needs a fresh stationary capture over three seconds',()=>{
  const check=new SensorCheck();check.begin('gyro',0,[0,0,0]);
  for(let i=0;i<=30;i++)check.sample([.2,.1,0,0,0,1],i*100);
  assert.ok(Math.abs(check.gyro[0]-.2)<1e-6);
  check.begin(0,4000,[0,0,0]);check.sample([0,0,0,0,0,1],4000);check.sample([0,0,0,0,0,1],5500);
  assert.match(check.note,/interrupted/);
});
