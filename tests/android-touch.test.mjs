import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Controls,NEUTRAL} from '../web/cockpit-controls.js';
import {TouchInput,responses} from '../android/controller/touch-input.js';

test('floating thumbs are neutral on first contact and have separate ownership',()=>{
  const controls=new Controls(), input=new TouchInput(controls,'Fast');
  assert.equal(input.begin('left',7,70,35,60,0),true);
  assert.equal(input.begin('right',9,350,82,60,1),true);
  assert.deepEqual(controls.values,NEUTRAL);
  assert.equal(input.move('right',7,410,82,1),false);
  assert.equal(input.begin('right',11,0,0,60,2),false);
  input.move('right',9,410,82,20);
  assert.equal(controls.values[0],2000);
  input.move('left',7,10,35,60);
  assert.equal(controls.values[3],1000);
  input.end('right',9,80);
  assert.deepEqual(controls.values.slice(0,4),[1500,1500,1000,1000]);
  input.end('left',7,80);
  assert.deepEqual(controls.values,NEUTRAL);
});

test('throttle uses actual hold time, pulse resolution, per-preset rates and release hold',()=>{
  for(const [name,preset] of Object.entries(responses)){
    const controls=new Controls(), input=new TouchInput(controls,name);
    input.begin('left',1,80,90,40,0);
    input.move('left',1,80,50,0);
    for(let t=10;t<=1000;t+=10)input.tick(t);
    assert.equal(controls.values[2],1000+preset.slew);
    input.end('left',1,1000);
    assert.equal(controls.values[3],1500);
    input.tick(2000);
    assert.equal(controls.values[2],1000+preset.slew);
    input.begin('left',2,5,5,40,2010);
    assert.equal(controls.values[2],1000+preset.slew);
    input.move('left',2,5,45,2010);
    for(let t=2030;t<=3030;t+=20)input.tick(t);
    assert.equal(controls.values[2],1000);
  }
});

test('response scales, radial corners and central deadband use A1 channel directions',()=>{
  for(const [name,profile] of Object.entries(responses)){
    const controls=new Controls(),input=new TouchInput(controls,name);
    input.begin('right',3,100,100,100,0);
    input.move('right',3,102,102,0);
    assert.deepEqual(controls.values,NEUTRAL);
    input.move('right',3,100,0,0);
    assert.equal(controls.values[1],Math.round(1500+profile.scale*500));
    input.move('right',3,250,-50,0);
    assert.ok(controls.values[0]>1500 && controls.values[0]<1500+profile.scale*500);
    assert.equal(controls.values[0],controls.values[1]);
  }
});

test('neutralisation invalidates previously held fingers and does not replay throttle',()=>{
  const controls=new Controls(),input=new TouchInput(controls);
  input.begin('left',3,0,0,40,0);input.move('left',3,0,-40,0);input.tick(50);
  input.begin('right',5,100,0,40,50);input.move('right',5,140,0,50);
  assert.ok(controls.values[2]>1000);
  controls.reset(); // FC input requalification/session reset/explicit sender stop
  assert.equal(input.move('right',5,140,0,60),false);
  input.tick(200);
  assert.equal(input.end('left',3,201),false);
  assert.deepEqual(controls.values,NEUTRAL);
  assert.equal(input.pointers.size,0);
});

test('large event-loop stalls cannot integrate old motion for elapsed seconds',()=>{
  const controls=new Controls(),input=new TouchInput(controls,'Fast');
  input.begin('left',1,0,0,50,0);input.move('left',1,0,-50,0);
  input.tick(10_000);
  assert.equal(controls.values[2],1048);
  input.release();
  input.tick(20_000);assert.equal(controls.values[2],1048);
});
