import {test} from 'node:test';
import assert from 'node:assert/strict';
import {poses, SensorCheck} from '../web/calibration.js';

const zero = [0, 0, 0];
function group21(face, bias = zero, base = zero, gyro = zero, gain = [1, 1, 1]) {
  const [, axis, sign] = poses[face];
  return [...gyro, ...bias.map((v, i) => v + base[i] + (i === axis ? sign * gain[i] : 0)), 0, 0, 0, 0];
}
function hold(check, at, sample, samples = 41, spacing = 75) {
  for (let k = 0; k < samples; k++) check.sample(sample, at + k * spacing);
  return at + samples * spacing;
}
test('automatically identifies six faces in any order and fits additive offsets and boot residual', () => {
  const check = new SensorCheck(), bias = [.06, -.04, .075], base = [-.1, .03, .12];
  const drift = [.23, -.12, .31], order = [2, 5, 0, 1, 4, 3];
  let at = 0;
  assert.ok(check.start(at, base));
  assert.ok(!check.start(at, base));
  order.forEach((face, i) => {
    const values = group21(face, bias, base, drift);
    at = hold(check, at, values);
    assert.equal(check.faces.size, i + 1);
    if (i < 5) {
      assert.equal(check.ready, false); assert.equal(check.offsets, null);
      assert.equal(check.nextPose, poses.findIndex((_, i) => !check.faces.has(i)));
      at = hold(check, at, values);
      assert.equal(check.detected, face);
      assert.equal(check.progress, 0, 'repeating the same face cannot advance');
    }
  });
  assert.ok(check.ready);
  assert.equal(check.active, null);
  assert.equal(check.nextPose, null);
  for (let i = 0; i < 3; i++) {
    assert.ok(Math.abs(check.offsets[i] + bias[i]) < 1e-9);
    assert.ok(Math.abs(check.gyro[i] - drift[i]) < 1e-9);
    assert.ok(check.quality.axisErrors[i] < 1e-9);
  }
  assert.ok(check.quality.maxError < 1e-9);
  assert.equal(check.quality.gyroPeak, .31);
});

test('holds need continuous quiet measurements; reorientation, vibration and angular motion reset the dwell', () => {
  const check = new SensorCheck(); check.start(10, zero);
  const flat = group21(0), nose = group21(1);
  let at = hold(check, 10, flat, 21);
  assert.equal(check.progress, .5);
  check.sample([0, 0, 0, .707, .707, 0], at); at += 75;
  assert.equal(check.progress, 0); assert.equal(check.detected, null);
  at = hold(check, at, nose, 20);
  assert.equal(check.detected, 1);
  check.sample([0, 0, 7, -1, 0, 0], at); at += 75;
  assert.equal(check.phase, 'detecting');
  at = hold(check, at, flat, 12);
  check.sample([0, 0, 0, .14, 0, 1], at); at += 75;
  assert.equal(check.progress, 0);
  at = hold(check, at, nose, 40);
  assert.equal(check.faces.size, 0);
  check.sample(nose, at);
  assert.equal(check.faces.size, 1);
  assert.equal(check.nextPose, 0);
});

test('rejects motion slower than the peak gate when the stationary gyro mean exceeds the limit', () => {
  const check = new SensorCheck(); check.start(0,zero);
  const at = hold(check,0,group21(1,zero,zero,[0,2,0]));
  assert.equal(check.faces.size,0); assert.match(check.note,/Gyro/);
  hold(check,at,group21(1)); assert.equal(check.faces.size,1);
});

test('rejects timestamp duplicates, buffered bursts, sparse frames and long gaps', () => {
  const check = new SensorCheck(), flat = group21(0); check.start(150, zero);
  for(let k=0;k<100;k++)check.sample(flat,150);
  check.sample(flat,20);
  assert.equal(check.window.count,1);
  for(let i=1;i<=8;i++){for(let j=0;j<10;j++)check.sample(flat,150+i*420+j/10);}
  assert.equal(check.faces.size,0);
  assert.equal(check.window.count,9);
  check.sample(flat,5500);
  assert.equal(check.phase,'stopped'); assert.equal(check.active,null);
  assert.equal(check.offsets,null);
  assert.ok(check.start(6500,zero)); assert.equal(check.faces.size,0);
  check.sample(flat,7100); assert.equal(check.phase,'stopped');
});

test('checks actual offset-only residual and rejects unsupported gain or inconsistent axes',()=>{
  for(const mismatch of ['gain','cross-axis','offset-range']){
    const check=new SensorCheck();const base=mismatch==='offset-range'?[-.4,0,0]:zero;
    check.start(0,base);
    let at=0;
    for(let i=0;i<6;i++){
      const gain=mismatch==='gain'?[1,1,1.16]:[1,1,1];
      const bias=mismatch==='offset-range'?[.52,0,0]:zero;
      const sample=group21(i,bias,base,zero,gain);
      if(mismatch==='cross-axis'&&i===2)sample[5]=.18;
      at=hold(check,at,sample);
    }
    assert.equal(check.faces.size,6);
    assert.equal(check.phase,mismatch==='offset-range'?'error':'review');assert.equal(check.ready,false);
    assert.equal(check.offsets,null);
    if(mismatch==='offset-range')assert.match(check.note,/range/);
    else {
      assert.ok(check.quality.maxError>.12);
      const flagged=mismatch==='gain'?[0,5]:[2];
      assert.deepEqual(check.quality.failed,flagged);
      assert.match(check.note,/0\.12 g/);
      const goodFace=check.faces.get(3);
      assert.ok(check.retryFaces(at));
      assert.equal(check.faces.get(3),goodFace);
      assert.equal(check.faces.size,6-flagged.length);
      if(mismatch==='cross-axis'){
        const tilted=group21(2);tilted[5]=.18;
        at=hold(check,at,tilted);assert.equal(check.faces.size,5);assert.match(check.note,/Off-axis/);
      }
      for(const f of flagged)at=hold(check,at,group21(f,zero,base,zero,mismatch==='gain'?[1,1,1.16]:[1,1,1]));
      if(mismatch==='gain'){assert.equal(check.needsRetry,true);assert.equal(check.offsets,null);assert.match(check.note,/Z measures/);}
      else {assert.equal(check.ready,true);assert.equal(check.faces.get(3),goodFace);}
    }
    assert.ok(check.start(at,zero));assert.equal(check.quality,null);
  }
});

test('requires valid active offsets, live finite sensor measurements and explicit restart after cancellation',()=>{
  const check=new SensorCheck();
  for(const offsets of [null,[0],[NaN,0,0],[0,0,1]])assert.equal(check.start(0,offsets),false);
  const baseline=[0,0,.1];check.start(0,baseline);baseline[2]=.4;assert.equal(check.baseline[2],.1);
  check.sample([0,Infinity,0,0,0,1],0);assert.equal(check.phase,'error');
  assert.equal(check.start(5000,zero),true);check.stop('Lock lost.');
  hold(check,5000,group21(0));assert.equal(check.faces.size,0);assert.equal(check.note,'Lock lost.');
  check.clear();assert.equal(check.phase,'idle');assert.equal(check.baseline,null);
});
