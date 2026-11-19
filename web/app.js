import { UsbTelemetry } from './usb.js';
import { Instruments } from './instruments.js';
import { mountFlightExtra } from './flight-extra.js';
import { ConsoleShell } from './shell.js';
import { MAX_CSV_BYTES, parseCsv, serialize } from './records.js';

const $ = id => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const clamp = (v, min, max) => Math.max(min, Math.min(max,v));
const elapsed = ms => Math.floor(ms/60000) + ':' + String(Math.floor(ms/1000) % 60).padStart(2,'0');
const angle = v => v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(1) + '°';
const EMPTY = new Instruments();
let live = new Instruments();
let recording = [];
let packetCount = 0;
let state = 'offline';
let statusMessage = '';
let replay = null;
let page = 'welcome';
let lastShellUpdate = -Infinity;
const flightExtra = mountFlightExtra($('flight-page'));
let nextPaint = 0;
let newConnection = false;

function svg(tag, attributes, parent) {
  const node = document.createElementNS(svgNS,tag);
  Object.entries(attributes).forEach(([key,value]) => node.setAttribute(key,value));
  parent.appendChild(node);
  return node;
}
for (let deg = -60; deg <= 60; deg += 5) {
  if (deg === 0) continue;
  const major = deg % 10 === 0;
  const y = 118 - deg * 3;
  const half = major ? 29 : 13;
  svg('path',{d:`M${320-half} ${y}h${half*2}`,stroke:'#f3f6ee','stroke-opacity':major ? '.85' : '.53','stroke-width':major ? 1.5 : 1},$('pitch-lines'));
  if (major) svg('text',{x:320+half+6,y:y+3,fill:'#f3f6ee','font-size':9},$('pitch-lines')).textContent=deg;
}
for (let deg=-60;deg<=60;deg+=10) {
  svg('path',{d:'M320 22v'+(deg%30===0?9:5),transform:'rotate('+deg+' 320 118)',stroke:'#eff5ef','stroke-width':1.4},$('bank-ticks'));
}
function makeRow(id,name,kind) {
  const row=document.createElement('div'); row.className=kind;
  const label=document.createElement('span');label.textContent=name;
  const bar=document.createElement('div');bar.className='bar';bar.append(document.createElement('i'));
  const value=document.createElement('b');value.textContent='—';
  row.append(label,bar,value);$(id).append(row);
  return {bar:bar.firstElementChild,value};
}
const channelEls=Array.from({length:8},(_,i)=>makeRow('channels','CH'+(i+1),'chan'));
const motorEls=Array.from({length:4},(_,i)=>makeRow('motors','M'+(i+1),'motor'));
function text(el,value){if(el.textContent!==value)el.textContent=value;}
function notice(message){$('notice').hidden=!message;text($('notice'),message||'');}
const shell = new ConsoleShell({
  select(next){
    page=next;
    lastShellUpdate=-Infinity;
    render();
  },
  toggleUsb:()=> $('connect').click(),
  disconnectUsb:async()=>{if(['opening','handshake','connected','stale'].includes(state))await link.disconnect();}
});
const view=route=>shell.navigate(route);
function dropReplay(){
  if(replay)shell.reset('usb');
  replay=null;$('replay').hidden=true;
}
const link=new UsbTelemetry({
  onStatus(s){
    state=s.state;statusMessage=s.message||'';
    shell.log(statusMessage || state);
    if(state==='opening')newConnection=true;
    if(['opening','offline','error','stale'].includes(state))flightExtra.transmitter.reset();
    if(state==='handshake'){live=new Instruments();shell.reset('usb');}
    if(state==='connected'&&newConnection){
      live=new Instruments();recording=[];packetCount=0;newConnection=false;
    }
    const stateName={offline:'Offline',opening:'Opening',handshake:'Connecting',connected:'Connected',stale:'Link stale',error:'USB error'};
    text($('link-state'),stateName[state]||state);
    $('link-state').dataset.tone=state==='connected'?'good':state==='error'?'bad':['handshake','stale'].includes(state)?'warn':'';
    $('link-state').title=statusMessage;
    text($('connect').lastElementChild,['opening','handshake','connected','stale'].includes(state)?'Disconnect':'Connect USB');
    notice(['error','stale'].includes(state)?statusMessage:'');render();
  },
  onData(row){
    live.push(row);packetCount++;recording.push(row);shell.onPacket(row,'usb');
    // Drop in chunks to keep constant memory without shifting on every frame.
    if(recording.length>5000)recording.splice(0,250);
  }
});
$('connect').onclick=async()=>{
  if(['opening','handshake','connected','stale'].includes(state)){
    try{await link.disconnect();}catch(e){notice(e.message);}return;
  }
  if(!UsbTelemetry.supported()){notice('For USB, open this page in desktop Chrome or Edge. You can also open a telemetry CSV in Recordings.');return;}
  dropReplay();notice('');
  try{await link.connect();}catch(e){notice(e.message||'USB connection failed.');}
};

function positionStick(id,x,y) {
  const el=$(id);const valid=Number.isFinite(x)&&Number.isFinite(y);
  el.classList.toggle('live',valid);
  if(valid){el.firstElementChild.style.left=clamp((x-1000)/10,5,95)+'%';el.firstElementChild.style.top=clamp((2000-y)/10,5,95)+'%';}
}
function bars(els,values){
  els.forEach(({bar,value},i)=>{
    const n=values?.[i];const valid=Number.isFinite(n);
    text(value,valid?String(Math.round(n)):'—');
    bar.style.width=(valid?clamp((n-1000)/10,0,100):0)+'%';
  });
}
function render(){
  const clock=replay?replay.position:performance.now();
  const model=replay?replay.model:state==='connected'?live:EMPTY;
  const s=model.snapshot(clock);
  text($('fw'),s.firmware||'—');
  text($('transport'),replay?'CSV replay':'USB serial');
  text($('frames'),(replay?replay.index:packetCount).toLocaleString()+' packets');
  $('export').disabled=!recording.length;
  text($('record-detail'),recording.length?`${recording.length.toLocaleString()} USB packets available to export.`:'No USB telemetry recorded.');
  $('import').disabled=['opening','handshake','connected','stale'].includes(state);
  $('import').title=$('import').disabled?'Disconnect USB to open a recording.':'Open desktop or web console telemetry';
  const now=performance.now();
  const updateShell=now-lastShellUpdate>=150;
  if(updateShell||page==='flight'){
    const ctx={model,clock,state:replay?'replay':state,replay:!!replay,snapshot:s,events:shell.events,
      get rows(){return replay?replay.rows.slice(0,replay.index):recording;},
      group:(id,maxAge=Infinity)=>model.get(id,clock,maxAge),
      fullConsole:()=>shell.fullConsole(), checkTransmitter:()=>flightExtra.transmitter.open(ctx),
      navigate:view,toggleUsb:()=>$('connect').click(),
      openRecording:()=>view('record')};
    if(updateShell){shell.update(ctx);lastShellUpdate=now;}
    if(page==='flight')flightExtra.update(ctx);
    else if(flightExtra.transmitter.isOpen())flightExtra.transmitter.update(ctx);
  }
  if(page!=='flight')return;
  text($('arm'),s.status?s.status[0]?'Armed':'Disarmed':'Unknown');
  text($('mode'),s.status?s.status[1]?'Angle':'Rate / Acro':'—');text($('source'),s.source||'—');text($('loop'),s.loop?Math.round(s.loop)+' Hz':'—');
  const imu=s.imu;$('instrument').dataset.valid=String(!!imu);$('instrument-cover').hidden=!!imu;
  $('instrument').setAttribute('aria-label',imu?`Roll ${angle(imu.roll)}, pitch ${angle(imu.pitch)}, relative yaw ${$('yaw').textContent}`:'Attitude indicator awaiting telemetry');
  text($('att-state'),imu?(replay?'RECORDED IMU':'LIVE IMU'):'NO DATA');text($('roll'),angle(imu?.roll));text($('pitch'),angle(imu?.pitch));
  $('att-plane').setAttribute('transform',imu?`rotate(${-imu.roll} 320 118) translate(0 ${imu.pitch*3})`:'');
  // Group 22 contains accepted, normalized roll, pitch, throttle, yaw and AUX.
  const ch=s.channels;positionStick('left',ch?.[3],ch?.[2]);positionStick('right',ch?.[0],ch?.[1]);bars(channelEls,ch);bars(motorEls,s.motor);
  text($('rx-state'),ch?(replay?'RECORDED · µs':'ACCEPTED · µs'):'NO DATA');
  text($('health-source'),replay?'REPLAY':'TELEMETRY');

}

function advance(target,seek=false){
  if(!replay)return;
  if(seek&&target<replay.position){replay.model=new Instruments();replay.index=0;shell.reset('replay');}
  while(replay.index<replay.rows.length&&replay.rows[replay.index].at<=target){
    const row=replay.rows[replay.index++];
    replay.model.push(row);shell.onPacket(row,'replay');
  }
  replay.position=target;
  $('seek').value=String(target);
  text($('play-time'),elapsed(target)+' / '+elapsed(replay.duration));
}
function pause(){
  if(!replay)return;replay.playing=false;text($('play'),'Play');
}
$('import').onclick=()=>$('file').click();
$('file').onchange=async()=>{
  const file=$('file').files[0];$('file').value='';if(!file)return;
  try{
    if(file.size>MAX_CSV_BYTES)throw new Error('Choose a telemetry CSV smaller than 8 MiB.');
    const rows=parseCsv(await file.text());
    if(['opening','handshake','connected','stale'].includes(state))throw new Error('Disconnect USB to open a recording.');
    replay={rows,model:new Instruments(),index:0,duration:rows.at(-1).at,position:0,playing:false,startedAt:0};
    $('replay').hidden=false;$('seek').max=String(replay.duration);$('play').disabled=replay.duration===0;
    shell.reset('replay');shell.log('Opened recording · '+file.name);pause();advance(0);notice('');view('flight');
  }catch(e){notice(e.message);}
};
$('seek').oninput=()=>{pause();advance(Number($('seek').value),true);render();};
$('play').onclick=()=>{
  if(!replay)return;
  if(replay.playing){pause();return;}
  if(replay.position>=replay.duration)advance(0,true);
  replay.startedAt=performance.now()-replay.position;replay.playing=true;text($('play'),'Pause');
};
$('close-replay').onclick=()=>{dropReplay();render();};
$('export').onclick=()=>{
  try{
    const url=URL.createObjectURL(new Blob([serialize(recording)],{type:'text/csv;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download='areion-telemetry-'+new Date().toISOString().replaceAll(':','-')+'.csv';a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){notice(e.message);}
};
function tick(now){
  if(now>=nextPaint){
    if(replay?.playing){advance(Math.min(now-replay.startedAt,replay.duration));if(replay.position>=replay.duration)pause();}
    render();nextPaint=now+50;
  }
  requestAnimationFrame(tick);
}
shell.start();render();requestAnimationFrame(tick);
