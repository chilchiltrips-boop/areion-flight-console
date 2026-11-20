import {test} from 'node:test';
import assert from 'node:assert/strict';
import {responseTraces} from '../web/pid-trace.js';
test('tracking excludes FC targets across setup-lock, mode or report gaps',()=>{
  const r=(group,at,values)=>({group,at,values});
  const imu=[1,2,3,0,0,1,0,0,4,5], output=[0,0,0,1000,1000,1000,1000,8,9,10,11,12];
  const status=[false,true,true,8,.004,2000];
  const rows=[r(120,1,status),r(130,2,[false]),r(21,10,imu),r(23,10,output),r(130,100,[true]),r(23,101,output),r(21,700,imu)];
  const rate=responseTraces(rows,700,0,false),angle=responseTraces(rows,700,1,true);
  assert.deepEqual(rate.measure,[[10,1],[700,null]]);assert.deepEqual(rate.target,[[10,8],[101,null]]);
  assert.deepEqual(angle.measure,[[10,5],[700,null]]);assert.deepEqual(angle.target,[[10,12],[101,null]]);
});
