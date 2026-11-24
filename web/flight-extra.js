import {stickPoint} from './stick-geometry.js';
import {airframe} from './airframe.js';
import {cockpitMarkup} from './cockpit-markup.js';
import {flightDisplay, signed, tilt, wrap} from './cockpit-pfd.js';
import {CockpitSender, Controls, DEFAULT_KEYS, KEY_OPTIONS, MODE_NAMES, SOURCES, clamp, currentGuard, transmitterView, switchPulse, validKeys} from './cockpit-controls.js';
import {mountTxEvidence} from './tx-evidence.js';

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

const text=(el,value)=>{const str=String(value);if(el.textContent!==str)el.textContent=str;};
const formatKey=k=>({ArrowUp:'Up',ArrowDown:'Down',ArrowLeft:'Left',ArrowRight:'Right'})[k]??k.toUpperCase();
export function mountFlightExtra(root){
  const css=document.createElement('link');css.rel='stylesheet';css.href=new URL('./flight-extra.css',import.meta.url).href;document.head.append(css);
  root.innerHTML=cockpitMarkup();
  const q=sel=>root.querySelector(sel), all=sel=>Array.from(root.querySelectorAll(sel));
  const values=Object.fromEntries(all('[data-v]').map(e=>[e.dataset.v,e]));
  const buttons=Object.fromEntries(all('[data-do]').map(e=>[e.dataset.do,e]));
  const value=(name,val)=>text(values[name],val);
  const transmitter=mountTxEvidence(q('#cockpit-tx-badge'));
  // The desktop badge opens the check from Input. Use the same control directly here.
  const badge=q('.tx-evidence-badge'), check=q('#cockpit-tx-badge button');
  badge.setAttribute('aria-hidden','true');check.setAttribute('aria-label','Check transmitter');check.replaceChildren(badge);
  check.className='radio-check';check.title='Check transmitter';
  const drawPfd=flightDisplay(root);
  const pfd=q('.pfd-field canvas');
  const input=q('[data-input]'),clock=()=>performance.now(),keyboard=q('[data-keyboard]');
  const tiles=all('[data-tile]'), dots=all('[data-stick-dot]');
  const channelNames=all('[data-ch-name]'),channelReadings=all('[data-ch-value]'),channelBars=all('.tx-channel em');
  const aux=all('[data-aux]'),motors=all('.motor-strip > div');
  const mesh=q('.pose-viewport canvas'),standby=q('.pose-viewport span');
  const keysDialog=q('.keys-dialog'), keyStorage='areion.flight.keys.v1';
  let bindings=DEFAULT_KEYS;
  try{const stored=JSON.parse(localStorage.getItem(keyStorage));if(validKeys(stored))bindings=stored;}catch{}
  const controls=new Controls(bindings);
  let ctx=null,saving=false,dirty=false,savedSource=null,model=null,lastSource=null;
  let zero=0,prevTime=null,prevStamp=null,lastYaw=null,mapView=false,keyboardOnly=false,savedRead=null;
  let retrySavedAt=Infinity;
  const sender = new CockpitSender(controls,()=>ctx,reason=>{
    message(reason);
    if(ctx?.state==='connected')Promise.resolve(ctx.stopKit?.()).catch(e=>message(e.message));
  });
  function message(s){
    if(ctx?.message){ctx.message(s);return;}
    const el=q('[data-feedback]');el.hidden=!s;text(el,s);
  }
  function showTab(name){
    all('[data-pane]').forEach(p=>{p.hidden=p.dataset.pane!==name;});
    ['channels','aux','controls'].forEach(k=>buttons[k].setAttribute('aria-pressed',String(k===name)));
  }
  function viewMap(yes){
    if(yes&&sender.running)return;
    mapView=yes;controls.reset();
    q('[data-view="map"]').hidden=!yes;q('[data-view="joystick"]').hidden=yes;
    buttons.map.setAttribute('aria-pressed',String(yes));buttons.joystick.setAttribute('aria-pressed',String(!yes));
  }
  let txView='preview';
  const canEdit=()=>!mapView&&!root.hidden&&['local','preview'].includes(txView)&&!keysDialog.open;
  function stopActive(reason){
    const wasRunning=sender.stop();
    if(wasRunning){message(reason);Promise.resolve(ctx?.stopKit?.()).catch(e=>message(e.message));}
  }
  function drawSticks(channels){
    dots.forEach((node,i)=>{
      const h=channels?.[i===0?3:0],v=channels?.[i===0?2:1];
      node.style.display=Number.isFinite(h)&&Number.isFinite(v)?'':'none';
      if(node.style.display)return;
      const x=80+clamp((h-1500)/500,-1,1)*51,y=80-clamp((v-1500)/500,-1,1)*51;
      const t='translate('+x+' '+y+')';
      if(node.lastElementChild.getAttribute('transform')===t)return;
      node.firstElementChild.setAttribute('d','M80 80L'+x+' '+y);
      node.lastElementChild.setAttribute('transform',t);
    });
  }
  function finishPointer(stick){
    if(stick.dataset.pointer===undefined)return;
    delete stick.dataset.pointer;controls.stick(stick.dataset.side==='left',0,0,false);
    if(canEdit())drawSticks(controls.values);
  }
  function movePointer(stick,e){
    if(String(e.pointerId)!==stick.dataset.pointer||!canEdit())return;
    const point=stickPoint(stick.getBoundingClientRect(),e.clientX,e.clientY,51/160);
    controls.stick(stick.dataset.side==='left',point.x,point.y,true);
    drawSticks(controls.values);
  }
  for(const stick of all('.tx-stick')){
    stick.onpointerdown=e=>{
      if(!canEdit()||e.button!==0||stick.dataset.pointer!==undefined)return;
      e.preventDefault();stick.dataset.pointer=String(e.pointerId);stick.setPointerCapture(e.pointerId);movePointer(stick,e);
    };
    stick.onpointermove=e=>movePointer(stick,e);
    stick.onpointerup=e=>{if(String(e.pointerId)===stick.dataset.pointer)finishPointer(stick);};
    stick.onlostpointercapture=stick.onpointercancel=stick.onpointerup;
  }
  function keyEvent(e,down) {
    if(root.hidden||document.hidden)return;
    if(down&&sender.running&&(e.key==='Escape'||e.code==='Space')){e.preventDefault();stopActive('Sender stopped.');return;}
    const k=formatKey(e.key);
    if(!down){controls.key(k,false);return;}
    if(!canEdit()||!keyboard.checked||e.ctrlKey||e.metaKey||e.altKey||e.shiftKey||document.querySelector('dialog[open]'))return;
    if(e.target?.closest?.('input,select,textarea,[contenteditable=true]'))return;
    if(controls.key(k,true)){keyboardOnly=true;e.preventDefault();}
  }
  window.addEventListener('keydown',e=>keyEvent(e,true));window.addEventListener('keyup',e=>keyEvent(e,false));
  const release=()=>{for(const stick of all('.tx-stick'))finishPointer(stick);stopActive('Sender stopped on focus loss.');keyboardOnly=false;};
  window.addEventListener('blur',release);window.addEventListener('pagehide',release);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)release();});
  keyboard.onchange=()=>{controls.pressed.clear();controls.stick(false,0,0,false);controls.stick(true,0,0,false);keyboardOnly=false;};
  for(const slider of aux)slider.oninput=()=>{if(canEdit())controls.values[Number(slider.dataset.aux)]=slider.valueAsNumber;};
  input.onchange=()=>{dirty=true;};
  function keyEditor(){
    if(!canEdit()||sender.running)return;
    const grid=q('.key-grid');grid.replaceChildren();
    for(let i=0;i<8;i++){
      const label=document.createElement('strong');label.textContent='CH'+(i+1);grid.append(label);
      for(let j=0;j<2;j++){
        const field=document.createElement('select');field.setAttribute('aria-label','CH'+(i+1)+(j?' increase':' decrease'));
        for(const k of KEY_OPTIONS)field.add(new Option(k,k));
        field.value=controls.keys[i*2+j];grid.append(field);
      }
    }
    controls.reset();text(keysDialog.querySelector('p'),'');keysDialog.showModal();
  }
  function persistKeys(){
    const arr=all('.key-grid select').map(el=>el.value);
    if(!validKeys(arr)){text(keysDialog.querySelector('p'),'Assign a different key to each direction.');return;}
    try{localStorage.setItem(keyStorage,JSON.stringify(arr));}catch{message('Using bindings for this session.');}
    controls.keys=arr;controls.reset();keysDialog.close();
  }
  function cancelSavedRead(){
    savedRead?.abort();savedRead=null;
  }
  function inspectSaved(c){
    cancelSavedRead();
    const link=c.link,owner=link?.session;
    savedSource=null;retrySavedAt=Infinity;
    if(!owner||!link?.readGroup||c.replay||c.state!=='connected'||saving||sender.running)return;
    const request=savedRead=new AbortController();
    link.readGroup(134,{saved:true,signal:request.signal}).then(saved=>{
      if(request.signal.aborted||ctx?.link!==link||link.session!==owner)return;
      savedSource=saved?.[1]??null;
      if(!dirty && savedSource!=null)input.value=String(savedSource);
    }).catch(error=>{
      if(!request.signal.aborted && ['BUSY','CANCELLED','EXPIRED','AP_FRAME_DROPPED'].includes(error.code))retrySavedAt=clock()+1200;
    }).finally(()=>{if(savedRead===request)savedRead=null;});
  }
  async function saveSource(){
    if(saving||!ctx||ctx.replay||sender.running||ctx.state!=='connected'||ctx.group(120,500)?.[0]!==false)return;
    const c=ctx,source=Number(input.value);
    cancelSavedRead();
    saving=true;
    try{
      await c.saveInput(source);
      if(ctx?.model!==c.model)return;
      dirty=false;savedSource=source;controls.reset();message('Active and saved input verified · '+SOURCES[source]);
    }catch(e){if(ctx?.model===c.model)message(e.message);}
    finally{saving=false;if(ctx?.model===c.model && savedSource==null)retrySavedAt=clock();}
  }
  root.addEventListener('click',async e=>{
    const name=e.target.closest('[data-do]')?.dataset.do;if(!name)return;
    switch(name){
      case 'map':case 'joystick':viewMap(name==='map');break;
      case 'keys':keyEditor();break;
      case 'save-keys':persistKeys();break;
      case 'cancel-keys':keysDialog.close();break;
      case 'channels':case 'aux':case 'controls':showTab(name);break;
      case 'record':ctx?.openRecording?.();break;
      case 'save-input':await saveSource();break;
      case 'send':
        if(sender.running)stopActive('Sender stopped.');
        else if(!mapView){
          cancelSavedRead();if(savedSource==null)retrySavedAt=clock();
          try{sender.start();}catch(error){message(error.message);}
        }
        break;
      case 'arm':
        try{await sender.arm();if(sender.running)message('FC armed · status verified.');}
        catch(error){if(sender.running)stopActive(error.message);}break;
      case 'angle':case 'rate':{
        if(!sender.ready||!currentGuard(ctx,clock()).ready)break;
        const settings=ctx.group(7),pulse=switchPulse(settings,name==='angle'?0:1);
        if(pulse!==null)controls.values[settings[0]-1]=pulse;
        break;
      }
      case 'zero':if(lastYaw!=null){zero=lastYaw;prevStamp=null;}break;
      case 'expand':{
        const big=root.classList.toggle('cockpit-expanded');
        buttons.expand.setAttribute('aria-pressed',String(big));text(buttons.expand,big?'Show instruments':'Expand health');break;
      }
    }
    if(ctx)refresh(ctx);
  });
  function refresh(c){
    ctx=c;const now=clock(),s=c.snapshot,imu=s.imu;
    const report=c.group(122,500),selected=report?.[0]??c.group(110)?.[0]??null;
    const modelChanged=model!==c.model;
    if(modelChanged||!imu||prevStamp!=null&&imu.at<prevStamp)zero=0;
    const since=prevTime===null?50:Math.max(0,now-prevTime);prevTime=now;prevStamp=imu?.at;lastYaw=imu?.yaw;
    if(modelChanged){
      if(sender.running)stopActive('Flight controller session changed.');
      dirty=false;controls.reset();model=c.model;lastSource=null;
    }
    const g=currentGuard(c,now),nextView=transmitterView(c,g,selected);
    if(txView!==nextView || selected!==lastSource){
      controls.reset();keyboardOnly=false;
      for(const stick of all('.tx-stick'))finishPointer(stick);
      if(keysDialog.open)keysDialog.close();
    }
    txView=nextView;
    const monitor=!['local','preview'].includes(txView),ppm=txView==='ppm';
    if(modelChanged||selected!==lastSource){
      if(selected!=null&&!dirty)input.value=String(selected);
      lastSource=selected;inspectSaved(c);
    }else if(!saving&&!sender.running&&now>=retrySavedAt){inspectSaved(c);}
    const live=c.state==='connected'&&!c.replay;
    const status=s.status,mode=status?(status[1]?0:1):null;
    const yaw=lastYaw==null?null:wrap(lastYaw-zero);
    value('source','Active: '+(['NONE','PPM','AP','USB'][report?.[1]]??'—')+' · Saved: '+(SOURCES[savedSource]??'—'));
    input.disabled=Boolean(c.replay||sender.running||saving);
    buttons['save-input'].disabled=!live||sender.running||saving||status?.[0]!==false||!status?.[7];
    value('input-note',selected==null?(live?'Awaiting input':c.replay?'Replay':'Offline'):SOURCES[selected]+' input');
    value('tx-title',monitor?(c.replay?'Recorded transmitter':'Receiver monitor'):'Virtual transmitter');
    const liveChannels=s.input.level==='good'?s.channels:null;
    const receiverName=SOURCES[selected]??'receiver';
    value('stick-note',c.replay?'Recorded channels':monitor?
      (liveChannels?'Received '+receiverName+' channels':'Waiting for '+receiverName+' channels'):'Local TX channels');
    value('pilot-note',ppm?'Use the radio sticks and its configured arm and disarm gestures.':
      txView==='replay'?'Playback of the recorded input.':
      txView==='monitor'?'Control from the selected '+receiverName+' sender. To use the browser, connect via that input.':
      txView==='waiting'?'Waiting for the kit to identify its input and sender.':
      'USB or AP · Start sender, then select ARM. For an AP app or Python sender, disconnect this console first.');
    root.classList.toggle('receiver-mode',monitor);
    if(keyboardOnly&&keyboard.checked&&canEdit())controls.step(since/1000);
    const received=c.replay?s.channels:liveChannels,local=monitor?received:controls.values;
    drawSticks(local);
    const settings=c.group(7),modeChannel=settings?.[0]??5;
    for(let i=0;i<8;i++){
      const n=local?.[i],pretty=n??'—';
      text(channelNames[i],(i+1)+' · '+(['Roll','Pitch','Thr','Yaw'][i]??(i+1===modeChannel?'Mode':'Aux')));
      text(channelReadings[i],monitor?pretty:pretty+' / '+(received?.[i]??'—'));
      channelBars[i].style.width=clamp(((n??1000)-1000)/10,0,100)+'%';
      if(i>=4){const slider=aux[i-4];slider.disabled=monitor;slider.value=String(n??1000);text(slider.previousElementSibling,pretty);}
    }
    value('channel-label',c.replay?'Recorded channels · µs':monitor?'Received '+receiverName+' channels · µs':'TX command / received FC value');
    value('switch-info',settings?'Mode switch · CH'+modeChannel:'Flight mode · offline');
    value('key-summary','Roll '+controls.keys.slice(0,2).join('/')+' · Pitch '+controls.keys.slice(2,4).join('/')+' · Throttle '+controls.keys.slice(4,6).join('/')+' · Yaw '+controls.keys.slice(6,8).join('/'));
    keyboard.disabled=monitor;buttons.keys.disabled=monitor||sender.running;
    value('mode','FC MODE: '+(mode===null?'UNKNOWN / STALE':MODE_NAMES[mode]));
    for(const [i,name] of ['angle','rate'].entries()){
      buttons[name].disabled=!sender.ready||!g.ready||switchPulse(settings,i)==null;
      buttons[name].setAttribute('aria-pressed',String(mode===i));
    }
    buttons.send.disabled=!sender.running&&(!g.canStart||saving);text(buttons.send,sender.running?'Stop sender':'Start sender · 50 Hz');
    buttons.arm.disabled=!sender.canArm(now);buttons.map.disabled=check.disabled=sender.running;
    value('sender',sender.running?(sender.ready?(sender.rate?sender.rate.toFixed(1)+' Hz · READY':'SENDER READY'):'Waiting for FC input'):'SENDER OFF');
    buttons.zero.disabled=lastYaw==null;
    value('yaw',signed(yaw));value('ROLL',signed(imu?.roll));value('PITCH',signed(imu?.pitch));value('TILT',imu?tilt(imu.roll,imu.pitch).toFixed(1)+'°':'—');
    value('armed',status?(status[0]?'ARMED':'DISARMED'):'ARM —');values.armed.dataset.armed=status?String(status[0]):'';
    value('flight-mode',mode===null?'':MODE_NAMES[mode]);
    const setup=c.group(130,500),statusMap=healthReadout(s,c.group,live||c.replay);
    const tx=transmitter.update(c);
    if(tx.code==='off'&&tx.label==='TX OFF'&&statusMap.INPUT.level!=='bad'){
      statusMap.INPUT=statusMap.PPM=state('TX OFF');if(statusMap.MODE.level==='good')statusMap.MODE=state(statusMap.MODE.label);
    }
    const reason=!live&&!c.replay?'FC disconnected':!status?'Waiting for FC status':statusMap.IMU.level==='bad'?'IMU read fault':
      !status[5]?'Waiting for gyro calibration':setup?.[0]?'Setup lock active':setup&&!setup[1]?'Setup incomplete':
      live&&selected>0&&!status[0]&&g.lockClear&&(!g.pidSaved||!status[7])?'Waiting for saved PID confirmation':
      tx.label==='TX OFF'?'PPM transmitter off':!report?'Waiting for input status':s.input.label;
    value('reason',reason);
    for(const t of tiles){
      const val=statusMap[t.dataset.tile];t.dataset.tone=val.level;text(t.lastElementChild,val.label.toUpperCase());
    }
    buttons.expand.title=root.classList.contains('cockpit-expanded')?'Restore primary flight display':'Enlarge IMU and system health';
    drawPfd(imu,yaw,since,modelChanged);
    const attitudeLabel=imu?'Roll '+signed(imu.roll)+', pitch '+signed(imu.pitch)+', relative yaw '+signed(yaw):'Waiting for live IMU';
    pfd.setAttribute('aria-label',attitudeLabel);
    value('pose-state',imu?(c.replay?'REPLAY':'LIVE'):'OFFLINE');standby.hidden=!!imu;
    value('pose-ROLL',signed(imu?.roll));value('pose-PITCH',signed(imu?.pitch));value('pose-REL YAW',signed(yaw));
    if(imu)airframe(mesh,c.group(134)?.[0]===2?'areion250':'areion450',[imu.roll,imu.pitch,yaw??0]);
    else if(mesh.dataset.pose!=='offline'){mesh.dataset.pose='offline';mesh.getContext('2d')?.clearRect(0,0,mesh.width,mesh.height);}
    motors.forEach((el,i)=>{const n=s.motor?.[i];text(el.querySelector('b'),Number.isFinite(n)?Math.round(n):'—');el.querySelector('em').style.width=clamp(((n??1000)-1000)/10,0,100)+'%';});
  }
  return {update:refresh,transmitter,cancelSender:()=>sender.stop(),get running(){return sender.running;}};
}
