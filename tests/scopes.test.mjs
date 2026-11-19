import test from 'node:test';
import assert from 'node:assert/strict';
import {accepted,scopeHistory,spectrum,trace} from '../web/scope-data.js';

const ppm=[0,1,true,false,true,8,5,40,false], usb=[2,3,false,false,true,8,5,27,true];
test('accepted traces require a fresh FC signal and break on changes of owner or source',()=>{
  const pulses=[1050,1500,1000,1500,2000,1000,1500,1500];
  const rows=[[0,22,pulses],[5,122,ppm],[10,22,pulses],[50,122,usb],[55,22,pulses]].map(([at,group,values])=>({at,group,values}));
  const samples=scopeHistory(rows,55,5,null).get(22);
  assert.equal(samples[0].count,0);
  assert.deepEqual(trace(samples,0),[[[10,1050]],[[55,1050]]]);
  assert.equal(accepted([2,3,false,false,true,8,5,0,true]),0);
  assert.equal(accepted([0,1,true,false,true,8,251,25,false]),0);
  assert.equal(accepted([0,1,true,false,true,8,251,25,false],[500,250]),8);
});

test('Hann spectrum keeps received units and uses telemetry sample frequency',()=>{
  const n=128,fs=12.8;
  const samples=Array.from({length:n},(_,i)=>({at:1000*i/fs,count:10,values:[2*Math.sin(2*Math.PI*1.6*i/fs),0,0,0,0,1,0,0,0,0]}));
  const all=spectrum(samples,samples.at(-1).at,'3.2.0');
  const peak=all.bins[0].reduce((a,b)=>a[1]>b[1]?a:b);
  assert.equal(all.n,n);assert.ok(Math.abs(peak[0]-1.6)<1e-6);assert.ok(Math.abs(peak[1]-2)<1e-6);
  assert.match(spectrum(samples.slice(0,6),samples[5].at).message,/Collecting/);
  assert.match(spectrum(samples,samples.at(-1).at+600).message,/Waiting/);
  assert.match(spectrum(samples.map(s=>({...s,at:s.at/1000})),samples.at(-1).at/1000,'3.2.0').message,/Irregular/);
});

test('faults, missing IMU status and dropped frames leave gaps in the plot',()=>{
  const imu=Array(10).fill(1), ok=[false,false,true,0,.004,1000], failed=[false,false,false,0,.004,1000];
  const rows=[[0,21,imu],[3,120,ok],[5,21,imu],[20,120,failed],[22,21,imu],[25,120,ok],[30,21,imu],[551,21,imu]].map(([at,group,values])=>({at,group,values}));
  const samples=scopeHistory(rows,600,5).get(21);
  assert.deepEqual(trace(samples,0),[[[5,1]],[[30,1]]]);
});
