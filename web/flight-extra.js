import {airframe} from './airframe.js';

const HEALTH = ['TELEMETRY','INPUT','PPM','AP','USB','IMU','OUTPUT','CONFIG','LOOP','MODE','ARM','STORAGE'];
const state = (label,level='warn') => ({label,level});
export function healthReadout(s,group,available) {
  const h = s.health, stat = s.status;
  const values = Object.fromEntries(HEALTH.map(k=>[k,state('Offline','idle')]));
  const inputSources = ['PPM','AP','USB'];
  for(const k of inputSources) values[k]=state('Inactive','idle');
  if(!available){values.TELEMETRY=state('Offline','bad');return values;}
  const setup=group(130,500), receipt=group(136,500), device=group(125), outputs=group(23,500);
  const wait = v=>v.level==='idle'?state(v.label,'warn'):v;
  values.TELEMETRY=wait(h.telemetry); values.INPUT=wait(h.input); values.IMU=wait(h.sensor);
  const source=s.source??inputSources[group(110)?.[0]??group(134)?.[1]];
  if(source) values[source]=wait(h.input);
  values.OUTPUT=wait(h.output);
  if(setup?.[14]==='MOTOR_OUTPUT_FAILED') values.OUTPUT=state('Write fault','bad');
  else if(outputs) {
    const motors=outputs.slice(3,7);
    const ok=motors.length===4 && motors.every(x=>Number.isFinite(x)&&x>=1000&&x<=2000);
    values.OUTPUT=ok?state(Math.max(...motors)===1000?'Minimum':'Commands','good'):state('Invalid','bad');
  }
  values.CONFIG=wait(h.setup);
  if(setup?.[14]) values.CONFIG=state('Fault','bad');
  else if(receipt?.[3]) values.CONFIG=state('Save error','bad');
  else if(receipt?.[0]||receipt&&receipt[1]!==receipt[2])values.CONFIG=state('Unsaved');
  else if(stat&&!stat[7])values.CONFIG=state('Storage');
  values.STORAGE=wait(h.storage);
  values.ARM=stat?state(stat[0]?'Armed':'Disarmed',stat[0]?'good':'idle'):state('Unknown');
  if(stat && (stat[4]<.001||stat[4]>.008)) values.LOOP=state('Timing','bad');
  else if(s.loop)values.LOOP=state(Math.round(s.loop)+' Hz',device&&Math.abs(s.loop-device[1])<=device[1]*.2?'good':'warn');
  else values.LOOP=state('Waiting');
  values.MODE=stat?state(stat[1]?'Angle':'Rate', ['INPUT','CONFIG','IMU'].every(k=>values[k].level==='good') && values.OUTPUT.level!=='bad'?'good':'warn'):state('Waiting');
  return values;
}

function make(tag,cls,txt) {
  const el=document.createElement(tag);if(cls)el.className=cls;if(txt)el.textContent=txt;return el;
}
function action(label,fn) {
  const el=make('button','flight-action',label);el.type='button';el.onclick=fn;return el;
}
const angle=v=>Number.isFinite(v)?(v>=0?'+':'')+v.toFixed(1)+'°':'—';
export function mountFlightExtra(root) {
  const css=make('link');css.rel='stylesheet';css.href=new URL('./flight-extra.css',import.meta.url).href;document.head.append(css);
  const receiver=root.querySelector('.receiver'), health=root.querySelector('.health');
  let ctx, expanded=false, mapView=false, lastModel, lastStamp, zero=0, lastYaw=null;
  const panelHeading=receiver.querySelector('h2');panelHeading.textContent='Virtual transmitter';
  const rxViews=make('div','flight-choices');
  const map=make('div','flight-gps');map.hidden=true;
  const world=make('img');world.src=new URL('./assets/world-land-110m.svg',import.meta.url);world.alt='World map';
  map.append(world,make('span','','Waiting for GPS'));
  const sticks=receiver.querySelector('.sticks'), bars=receiver.querySelector('.channels');
  const setView=name=>{
    mapView=name==='map';
    map.hidden=!mapView;sticks.hidden=mapView;bars.hidden=mapView;
    showTx.setAttribute('aria-pressed',String(!mapView));showMap.setAttribute('aria-pressed',String(mapView));
  };
  const showTx=action('Joystick TX',()=>setView('tx')),showMap=action('GPS map',()=>setView('map'));
  const controls=action('Transmitter controls',()=>ctx?.fullConsole?.());
  controls.title='Open the interactive transmitter with keyboard, mode and sender controls.';
  rxViews.append(showTx,showMap,controls);receiver.querySelector('header').after(rxViews);receiver.append(map);setView('tx');
  const tools=make('div','flight-choices flight-topline');
  const zeroBtn=action('Zero yaw',()=>{if(lastYaw!=null){zero=lastYaw; refresh(ctx);}});
  const expand=action('Expand health',()=>{
    expanded=!expanded;root.classList.toggle('expanded-health',expanded);
    expand.textContent=expanded?'Show instruments':'Expand health';expand.setAttribute('aria-pressed',String(expanded));
  });
  tools.append(zeroBtn,expand);
  const tilt=make('span','tilt-readout','Tilt —');tools.prepend(tilt);root.querySelector('.summary').after(tools);
  const pose=make('section','panel flight-pose');
  const header=make('header'), title=make('h2','','IMU attitude'), badge=make('span','eyebrow','OFFLINE');header.append(title,badge);
  const canvas=make('canvas'); canvas.setAttribute('aria-label','Quad X attitude from the IMU');
  const strip=make('div','pose-values');
  const nums=['ROLL','PITCH','REL YAW'].map(s=>{const unit=make('div'),value=make('b','','—');unit.append(make('span','',s),value);strip.append(unit);return value;});
  pose.append(header,canvas,strip);health.before(pose);
  const waiting=make('span','pose-wait','Waiting for IMU');canvas.after(waiting);
  const tiles=root.querySelector('#tiles');tiles.replaceChildren();
  const labels=Object.fromEntries(HEALTH.map(k=>{const box=make('div','tile'),word=make('b','',k),value=make('span','','Offline');box.append(word,value);tiles.append(box);return [k,{box,value}];}));
  function refresh(context){
    if(!context)return;
    ctx=context;
    const s=ctx.snapshot, imu=s.imu;
    if(lastModel!==ctx.model || !imu || lastStamp!=null && imu.at<lastStamp)zero=0;
    lastModel=ctx.model;lastStamp=imu?.at;lastYaw=imu?.yaw;zeroBtn.disabled=lastYaw==null;
    const yaw=lastYaw==null?null:((lastYaw-zero+540)%360+360)%360-180;
    const poseData=imu?{roll:imu.roll,pitch:imu.pitch,yaw}:null;
    const readouts=[imu?.roll,imu?.pitch,yaw];nums.forEach((n,i)=>{n.textContent=angle(readouts[i]);});
    if(imu){const dot=Math.cos(imu.roll*Math.PI/180)*Math.cos(imu.pitch*Math.PI/180);tilt.textContent='Tilt '+(Math.acos(Math.max(-1,Math.min(1,dot)))*180/Math.PI).toFixed(1)+'°';}
    else tilt.textContent='Tilt —';
    const pfdYaw=root.querySelector('#yaw');if(pfdYaw)pfdYaw.textContent=angle(yaw);
    badge.textContent=imu?(imu.yaw==null?'TILT ONLY':ctx.replay?'REPLAY':'LIVE'):'NO DATA';waiting.hidden=!!poseData;
    if(poseData)airframe(canvas,'areion450',[poseData.roll,poseData.pitch,poseData.yaw??0]);
    else if(canvas.dataset.pose!=='offline'){canvas.dataset.pose='offline';canvas.getContext('2d')?.clearRect(0,0,canvas.width,canvas.height);}
    const statuses=healthReadout(s,ctx.group,ctx.replay||ctx.state==='connected');
    for(const key of HEALTH){const pair=labels[key],v=statuses[key];pair.box.dataset.tone=v.level;pair.value.textContent=v.label;}
    labels.PPM.box.title='PPM pulses reported by the kit. For verified radio power/loss, use Check transmitter in the full console.';
  }
  return {update:refresh};
}
