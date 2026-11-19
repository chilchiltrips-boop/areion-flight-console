import test from 'node:test';
import assert from 'node:assert/strict';
import { Instruments } from '../web/instruments.js';

const status = [false,true,true,8,.004,2000,36000,true,false,false];
const sample = [0,0,20,0,0,1,0,0,0,0];
const rx = [0,1,true,false,true,8,10,0,false];
const packet = (group,values,at) => ({group,values,at});

test('orientation expires, resets with IMU faults and uses relative gyro yaw', () => {
  const m = new Instruments();
  m.push(packet(120,status,0));
  m.push(packet(21,sample,0)); m.push(packet(21,sample,100));
  assert.equal(m.snapshot(100).imu.yaw,2);
  m.push(packet(21,[...sample.slice(0,9),85],175));
  assert.equal(m.snapshot(176).imu.yaw,null);
  assert.equal(m.snapshot(800).imu,null);
  m.push(packet(120,[...status.slice(0,2),false,...status.slice(3)],900));
  m.push(packet(21,sample,900));
  assert.equal(m.snapshot(910).health.sensor.level,'bad');
  assert.equal(m.snapshot(910).imu,null);
});

test('gates receiver channels on actual input reports and separates USB transport', () => {
  const m = new Instruments();
  const channels=[1400,1500,1000,1500,2000,1000,1500,1500];
  m.push(packet(22,channels,10));m.push(packet(122,rx,20));
  assert.equal(m.snapshot(21).channels,null);
  m.push(packet(22,channels,30));
  assert.deepEqual(m.snapshot(60).channels,channels);
  assert.equal(m.snapshot(60).source,'PPM');
  assert.equal(m.snapshot(60).input.label,'PPM pulses');
  m.push(packet(122,[0,0,false,false,false,0,4294967295,0,false],100));
  assert.equal(m.snapshot(130).channels,null);
  assert.equal(m.snapshot(130).input.level,'warn');
  m.push(packet(120,[true,...status.slice(1)],131));
  assert.equal(m.snapshot(131).input.level,'bad');
  m.push(packet(122,[2,3,false,false,true,8,3,28,true],140));
  assert.equal(m.snapshot(140).channels,null);
  assert.equal(m.snapshot(900).status,null);
});
