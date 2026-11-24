import {escStates} from './esc-progress.js';
import {schemaFor} from './protocol.js';
import {fields} from './telemetry-fields.js';

export class ControllerDiagnostics {
  constructor(){this.reset();}
  reset(){this.setupKey=null;this.pidError='';this.health=null;}
  packet(row,record){
    const v=row.values;
    record({kind:'telemetry',name:fields.get(row.group)?.[0]??'DATA',group:row.group,status:'received',values:v,
      schema:schemaFor(row.group),sample_time:Math.round(performance.timeOrigin+row.at)});
    if(row.group===130){
      const signature=JSON.stringify([v[15],v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[8],v[14]]);
      if(signature===this.setupKey)return;
      this.setupKey=signature;
      const detail=v[14]||escStates[v[3]]||'Unknown ESC state';
      record({kind:'setup',group:130,name:'ESC · '+(escStates[v[3]]??'Unknown'),status:v[14]||v[3]===6?'error':'observed',detail,
        values:{kit_stage:v[2],esc_state:v[3],sensor_verified:v[5],receiver_verified:v[6],motor_mask:v[4],locked:v[0],complete:v[1],revision:v[13]}});
    }else if(row.group===136 && v[3]!==this.pidError){
      this.pidError=v[3];
      record({kind:'setup',group:136,name:'PID storage',status:v[3]?'error':'ok',detail:v[3]||'Recovered'});
    }else if(row.group===120){
      const key=Number(v[7])*2+Number(v[2]);
      if(key!==this.health){
        if(v[7]===false)record({kind:'health',group:120,name:'Controller storage',status:'error',detail:'Controller reports storage unavailable.'});
        if(v[2]===false)record({kind:'health',group:120,name:'IMU',status:'warning',detail:'Waiting for valid IMU readings.'});
        if(key===3&&this.health!==null)record({kind:'health',group:120,name:'Controller status',status:'ok',detail:'Storage and IMU ready.'});
      }
      this.health=key;
    }
  }
}

const columns=['timestamp_utc','source','host_session','fc_session','kit','page','step','kind','status','group','schema','name','detail','sample_time_utc','values_json'];
const iso=t=>Number.isFinite(t)?new Date(t).toISOString():'';
function csvCell(value){
  let text=String(value??'');
  if(/^[\s]*[=+@-]/.test(text))text="'"+text;
  return '"'+text.replaceAll('"','""')+'"';
}
function csvRow(row){
  return [iso(row.time),row.source,row.host_session,row.fc_session,row.kit,row.page,row.step,row.kind,row.status,row.group,row.schema,row.name,row.detail,iso(row.sample_time),JSON.stringify(row.values)].map(csvCell).join(',')+'\r\n';
}
export async function diagnosticFile(history,snapshot,format){
  const csv=format==='csv', parts=[csv?columns.join(',')+'\r\n':''];
  let count=0;
  const summary=await history.visit(rows=>{
    if(!rows.length)return;
    if(csv)parts.push(rows.map(csvRow).join(''));
    else parts.push((count?',':'')+rows.map(row=>JSON.stringify(row)).join(','));
    count+=rows.length;
  });
  const current={...snapshot};
  if(summary.cleared){
    if(current.events)current.events=current.events.filter(event=>event.time>summary.cleared);
    if(Date.parse(current.last_connection?.ended_at)<=summary.cleared)delete current.last_connection;
  }
  const capture={records:count,storage:summary.storage||'browser',discarded_records:summary.lost};
  if(csv){
    parts.push(csvRow({time:Date.now(),kind:'snapshot',name:'Current console',source:snapshot.source,status:snapshot.state,
      values:{...current,history:capture}}));
  }else{
    parts[0]=JSON.stringify(current).slice(0,-1)+(Object.keys(current).length?',':'')+'"records":[';
    parts.push('],"history":'+JSON.stringify(capture)+'}');
  }
  return new Blob(parts,{type:csv?'text/csv;charset=utf-8':'text/plain'});
}
