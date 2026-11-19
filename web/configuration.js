import {airframe} from './airframe.js';
import {drawResponse} from './pid-trace.js';
import {poses,SensorCheck} from './calibration.js';

const panes={wizard:'Setup wizard',input:'Input / receiver',imu:'IMU',esc:'ESC / motors',pid:'PID / settings'};
const steps=['Safety & connect','Aircraft profile','Input & wiring','Sensors','PPM receiver','ESC calibration','Motor outputs','Arming & flight modes','Review & save','Verify after restart'];
const profiles=['Areion 450','Areion 250','Areion Quad X','Generic Quad X'];
const sourceNames=['PPM receiver','AP Wi-Fi channels','USB channels'];
const ends=['Not checked','Pending restart','Calibrating','Confirm ESC response','ESC response confirmed','Calibration skipped','Interrupted / failed'];
const modes=['Angle','Rate / Acro'];
const axes=['Roll','Pitch','Yaw'];
const axes3=['X','Y','Z'];
const motorNames=['Front left · CW','Front right · CCW','Rear right · CW','Rear left · CCW'];
const blank='—';
const fmt=(v,unit='',digits=0)=>Number.isFinite(v)?v.toFixed(digits)+unit:blank;
const reading=(key)=>'<strong data-r="'+key+'">—</strong>';
const box=(title,html)=>'<section class="cfg-card"><h3>'+title+'</h3>'+html+'</section>';
const row=(title,key)=>'<div class="cfg-kv"><span>'+title+'</span>'+reading(key)+'</div>';
const opt=(name,arr,sel=0)=>'<select aria-label="'+name+'" data-select="'+name+'">'+arr.map((s,i)=>'<option value="'+i+'" '+(sel===i?'selected':'')+'>'+s+'</option>').join('')+'</select>';
const act=(id,text,cls='')=>'<button type="button" class="cfg-btn '+cls+'" data-act="'+id+'">'+text+'</button>';
const full=(text)=>act('full',text,'cfg-primary');
const canvas=(name='live')=>'<canvas data-scene="'+name+'" class="cfg-scene" role="img" aria-label="'+(name==='live'?'Reported aircraft attitude':'Areion Quad X model')+'"></canvas>';
const spark=(tag,i)=>'<div class="cfg-track"><i data-meter="'+tag+i+'"></i></div>';
const channelCell=(i)=>'<tr><th scope="row">CH'+(i+1)+'</th><td>'+reading('use'+i)+'</td><td>'+reading('ch'+i)+spark('ch',i)+'</td><td>'+reading('min'+i)+'</td><td>'+reading('center'+i)+'</td><td>'+reading('max'+i)+'</td><td>'+reading('reverse'+i)+'</td></tr>';
const sticks=()=>'<div class="cfg-sticks">'+['Yaw / Throttle','Roll / Pitch'].map((s,i)=>'<div><div class="cfg-stick"><i data-stick="'+i+'" hidden></i></div><small>'+s+'</small><br>'+reading('stick'+i)+'</div>').join('')+'</div>';
const motorRows=()=>'<div class="cfg-motors">'+motorNames.map((s,i)=>'<div><span><b>M'+(i+1)+'</b> '+s+'</span>'+reading('motor'+i)+spark('motor',i)+'</div>').join('')+'</div>';
const confirmation=(checked)=>'<label class="cfg-check"><input type="checkbox" data-props '+(checked?'checked':'')+'> All propellers removed</label>';
function kvTable(head,body){return '<div class="cfg-table"><table><thead><tr>'+head.map(t=>'<th scope="col">'+t+'</th>').join('')+'</tr></thead><tbody>'+body+'</tbody></table></div>';}

export function mount(root) {
  root.classList.add('cfg-page');
  if(!document.querySelector('link[data-cfg]')){
    const css=document.createElement('link');
    css.rel='stylesheet'; css.href=new URL('./configuration.css',import.meta.url);css.dataset.cfg='';document.head.append(css);
  }
  const sensor=new SensorCheck();
  let page='wizard',step=0,confirmed=false,subPID=0,pickedProfile=0,pose=0,last=null,linkId=null;
  let offsetDraft=[null,null,null],endpoints=null,rxRun=false,statusRow=null;
  let tabRoots,sceneOrbit=0,profileEdited=false,responseAxis=0,responseAngle=0;
  function safetyPage(){
    return box('Remove propellers',canvas('profile')+'<p>Motors can start during kit setup. Keep all propellers removed until setup is complete.</p>'+confirmation(confirmed))+
      box('Kit connection',row('Board','kit')+row('Firmware','firmware')+row('Arming','armed')+row('Setup lock','locked')+'<p>Browse steps here. Start kit setup in the full console to engage the controller’s arming lock.</p>'+full('Start kit setup'));
  }
  function aircraft(){
    return box('Aircraft profile',opt('Aircraft preview',profiles,pickedProfile)+canvas('profile')+act('rotate','Rotate model'))+
      box('Quad X',row('Saved profile','profile')+'<div class="cfg-kv"><span>Vehicle</span><strong>Multirotor</strong></div><div class="cfg-kv"><span>Frame</span><strong>Quadcopter · X</strong></div><div class="cfg-kv"><span>Motor drive</span><strong>Brushless ESC</strong></div>'+full('Set aircraft profile'));
  }
  function wiring(){
    return box('Areion FC A1 · fixed connections','<div class="cfg-wires">'+['D0 / GPIO 0|OUT 1|ESC 1 · M1','D1 / GPIO 1|OUT 2|ESC 2 · M2','D2 / GPIO 2|OUT 3|ESC 3 · M3','D3 / GPIO 21|OUT 4|ESC 4 · M4','D10 / GPIO 18|PPM|PPM receiver','D4 / GPIO 22|SDA|IMU SDA','D5 / GPIO 23|SCL|IMU SCL'].map(s=>{const [a,b,c]=s.split('|');return '<div><code>'+a+'</code><i></i><b>'+b+'</b><i></i><strong>'+c+'</strong></div>';}).join('')+'</div>')+
      box('Flight input',row('Selected','selected')+row('Active','active')+row('Input health','inputHealth')+'<p>Disconnect power while wiring. Connect each ESC to its matching board output.</p>'+full('Choose flight input'));
  }
  function sensors(){
    const rows=axes3.map((a,i)=>'<tr><th>'+a+'</th><td>'+reading('off'+i)+'</td><td><input type="number" data-off="'+i+'" step=".001" min="-.5" max=".5" aria-label="'+a+' draft offset in g" value="'+(offsetDraft[i]??'')+'" placeholder="FC offset"></td><td>'+reading('after'+i)+'</td></tr>').join('');
    return box('Live IMU',canvas('live')+row('Roll / pitch / relative yaw','rpy')+row('Gyro X / Y / Z','rates')+row('Sensor','imuHealth'))+
      box('Accelerometer offsets',kvTable(['Axis','FC offset (g)','Draft (g)','After offset (g)'],rows)+'<p>After-offset readings preview the draft on this screen.</p>'+row('Candidate offsets (g)','candidate')+full('Apply offsets in full console'))+
      box('Six-position accelerometer check',canvas('target')+opt('Target pose',poses.map(p=>p[0]),pose)+'<div class="cfg-actions">'+act('pose','Capture position')+act('reset-sensor','Reset captures')+'</div><progress data-progress="sensor" value="0" max="1"></progress>'+row('Positions','faces')+reading('sensorNote'))+
      box('Stationary gyro check',confirmation(confirmed)+'<p>Keep the disarmed kit still on a level surface. Each capture uses at least 20 samples over three seconds.</p>'+act('gyro','Capture gyro residual')+row('Residual (°/s)','bias')+row('Gyro after residual (°/s)','afterGyro'));
  }
  function receiver() {
    return box('Receiver activity',sticks()+row('Selected input','selected')+row('Active input','active')+row('Receiver','inputHealth')+row('Switch channel','flightCh'))+
      box('PPM endpoint capture',confirmation(confirmed)+'<p>Sweep the sticks and switches through their full travel. This preview uses the raw PPM stream from the kit.</p><div class="cfg-actions">'+act('rx-capture','Capture range')+act('rx-clear','Clear range')+'</div>'+row('Raw PPM','rawStatus')+row('Samples','rxSamples')+full('Calibrate or verify transmitter link'))+
      '<section class="cfg-card cfg-wide"><h3>Physical PPM channels</h3>'+kvTable(['Channel','Function','Raw (µs)','Min','Center','Max','Direction'],Array.from({length:8},(_,i)=>channelCell(i)).join(''))+'<p>Min and max show captured ranges during this local check. Center and direction come from the controller.</p></section>';
  }
  function esc(){
    return box('ESC calibration',row('Kit state','escState')+row('Output PWM','pwm')+row('Firmware range (duty)','duty')+'<div class="cfg-sequence">'+['Schedule','Power cycle','Endpoints','Confirm'].map((s,i)=>'<span data-phase="'+i+'">'+s+'</span>').join('')+'</div><p>One-shot endpoint calibration and response confirmation run in the full console.</p>'+full('Open ESC calibration'))+
      box('Motor outputs',motorRows()+row('Verified outputs','mask')+'<p>Readings are commanded pulses. Check rotation physically with the propellers removed.</p>'+full('Open motor tests'));
  }
  function arming(){
    return box('Arming timings',row('ARM hold','armTime')+row('DISARM hold','disarmTime')+row('Idle auto-disarm','idleTime')+row('Low throttle','armThr'))+
      box('Flight modes',row('Switch channel','flightCh')+row('Low position','modeLow')+row('High position','modeHigh')+row('Current mode','currentMode')+full('Edit arming & flight modes'));
  }
  function review(){
    return box(step===9?'Verify after restart':'Setup review',row('Kit identity','kit')+row('Firmware revision','revision')+row('Setup lock','locked')+row('Setup complete','complete')+row('Storage','storage'))+
      box('Controller checks',row('Sensors','sensorVerified')+row('Receiver','rxVerified')+row('ESC','escState')+row('Motors','mask')+full(step===9?'Open restart verification':'Review and save to kit'));
  }
  function wizard(){
    const work=[safetyPage,aircraft,wiring,sensors,receiver,esc,()=>box('Motor outputs',motorRows()+row('Verified outputs','mask')+full('Open output calibration'))+box('Motor order',canvas('profile')+'<p>M1 front left · M2 front right · M3 rear right · M4 rear left.</p>'),arming,review,review];
    return '<div class="cfg-wiz"><nav class="cfg-steps" aria-label="Setup steps">'+steps.map((s,i)=>'<button class="cfg-step" type="button" data-step="'+i+'" '+(i===step?'aria-current="step"':'')+(i&&!confirmed?' disabled':'')+'><span>'+String(i+1).padStart(2,'0')+'</span>'+s+'</button>').join('')+'</nav><div><div class="cfg-wiz-head"><div><small>Setup wizard</small><h2>'+steps[step]+'</h2></div><small>Step '+(step+1)+' / '+steps.length+'</small></div><div class="cfg-grid">'+work[step]()+'</div><div class="cfg-wiz-actions">'+act('back','Back')+(step<9?act('next','Next','cfg-primary'):'')+'</div></div></div>';
  }
  function pid(){
    const gains=(g,n)=>kvTable(['Gain',...axes.slice(0,n)],['P','I','D'].map((k,i)=>'<tr><th scope="row">'+k+'</th>'+Array.from({length:n},(_,j)=>'<td>'+reading('gain'+g+'-'+(i*n+j))+'</td>').join('')+'</tr>').join(''));
    const views=[
      ()=>box('Inner loop · rate',gains(2,3))+box('Outer loop · angle',gains(3,2)),
      ()=>box('Stick response',row('Angle scale','angleScale')+row('Rate scale','rateScale')+row('Yaw scale','yawScale')+row('Input deadband','deadband'))+box('Live targets',row('Roll / pitch / yaw (°/s)','targets')+row('Measured gyro (°/s)','rates')+row('Target roll / pitch (°)','targetAngles'))+'<section class="cfg-card cfg-wide"><h3>Tracking response</h3><div class="cfg-actions">'+opt('Loop',['Rate','Angle'],responseAngle)+opt('Axis',axes.slice(0,responseAngle?2:3),responseAxis)+'</div><canvas data-response class="cfg-response" role="img" aria-label="Measured and target tracking response over ten seconds"></canvas><small>Measured <b class="cfg-meas">━</b> &nbsp; Target <b class="cfg-target">━</b> · '+(responseAngle?'degrees':'degrees / second')+'</small></section>',
      ()=>box('Stored tune',row('Pending','pending')+row('Active revision','pidRev')+row('Stored revision','pidSaved')+row('Controller result','pidError'))+box('Aircraft',row('Saved profile','profile')+canvas('profile'))
    ];
    return '<div class="cfg-tabs">'+['Gains','Response','Stored tune'].map((p,i)=>'<button type="button" data-pid="'+i+'" aria-pressed="'+(subPID===i)+'">'+p+'</button>').join('')+'</div><div class="cfg-grid">'+views[subPID]()+'</div><div class="cfg-actions">'+full('Open PID tuning & apply')+'</div>';
  }
  function draw(){
    root.innerHTML='<nav class="cfg-tabs" aria-label="Configuration sections">'+Object.entries(panes).map(([key,title])=>'<button type="button" data-nav="'+key+'" '+(key===page?'aria-current="page"':'')+'>'+title+'</button>').join('')+'</nav>'+
      (page==='wizard'?wizard():page==='pid'?pid():'<div class="cfg-grid">'+({imu:sensors,input:receiver,esc})[page]()+'</div>');
    tabRoots=new Map();
    root.querySelectorAll('[data-r]').forEach(el=>{const key=el.dataset.r;if(!tabRoots.has(key))tabRoots.set(key,[]);tabRoots.get(key).push(el);});
    if(last) update(last);
  }
  function show(name='wizard'){
    const target=Object.hasOwn(panes,name)?name:'wizard';
    if(page!==target && sensor.active) sensor.stop('Capture cancelled.');
    if(page!==target) rxRun=false;
    page=target;draw();
  }
  function set(key,value){
    const text=value==null||value===''?blank:String(value);
    for(const el of tabRoots.get(key)??[]) if(el.textContent!==text)el.textContent=text;
  }
  function gate(ctx) {return !ctx.replay && ctx.state==='connected' && ctx.group(120,500)?.[0]===false;}
  function clearSessions() {
    sensor.clear();endpoints=null;rxRun=false;statusRow=null;
    offsetDraft=[null,null,null];confirmed=false;linkId=null;
  }
  function syncSafety(ctx){
    const id=ctx.group(130)?.[15];
    if(id&&linkId&&linkId!==id)clearSessions();
    if(id)linkId=id;
    const base=ctx.group(6);
    if(sensor.baseline&&base&&!sensor.baseline.every((x,i)=>x===base[i]))sensor.clear();
    if(sensor.active&&(!gate(ctx)||!ctx.snapshot.imu||!base||ctx.clock-sensor.active.started>12000))
      sensor.stop('Capture stopped. Check disarmed kit and live IMU.');
    if(rxRun&&!gate(ctx))rxRun=false;
  }
  function onPacket(packet,source) {
    if(root.hidden || source!=='usb') {if(sensor.active)sensor.stop('Capture cancelled.');rxRun=false;return;}
    if(packet.group===120){statusRow=packet;if(packet.values[0]||!packet.values[2]||!packet.values[5]){if(sensor.active)sensor.stop('Capture stopped. Kit must be disarmed with valid IMU.');}}
    if(packet.group===21){
      if(sensor.active && statusRow?.values[0]===false && packet.at>=statusRow.at && packet.at-statusRow.at<=500)
        sensor.sample(packet.values,packet.at);
    }
    if(packet.group===131){
      if(rxRun){
        const v=packet.values,n=v[8],timeout=last?.model.get(112,packet.at,Infinity)?.[0]??250;
        const selected=last?.model.get(122,packet.at,500);
        if(!v[9]||n<4||n>8||v[10]>=timeout||!statusRow || statusRow.values[0]!==false || packet.at-statusRow.at>500 || selected?.[0]!==0 || !selected?.[2]){rxRun=false;return;}
        if(endpoints.count&&endpoints.count!==n){rxRun=false;endpoints=null;return;}
        endpoints.count=n;
        for(let i=0;i<n;i++){endpoints.min[i]=Math.min(endpoints.min[i],v[i]);endpoints.max[i]=Math.max(endpoints.max[i],v[i]);}
        endpoints.samples++;
      }
    }
  }
  function update(ctx){
    last=ctx;
    const get=(id,age)=>ctx.group(id,age),s=ctx.snapshot,fc=get(130,500),cfg=get(134),dev=get(125),arm=get(4),flight=get(7),base=get(6),raw=get(131,500),cal=get(132),pidStatus=get(136,1500),imu=s.imu?get(21,500):null;
    const rawRecord=ctx.model.frames.get(131);
    const rawFresh=raw?.[9]&&raw[8]>=4&&raw[8]<=8&&rawRecord&&raw[10]+ctx.clock-rawRecord.at<(get(112)?.[0]??250);
    const yes=v=>typeof v==='boolean'?(v?'Yes':'No'):blank;
    const triple=(arr,d=2)=>arr?arr.map(v=>fmt(v,'',d)).join(' / '):blank;
    syncSafety(ctx);
    if(!confirmed&&step>0&&page==='wizard'){step=0;draw();return;}
    if(!profileEdited && cfg) pickedProfile=cfg[0];
    const values={
      kit:get(130)?.[15],firmware:dev?.[0],armed:s.status?(s.status[0]?'Armed':'Disarmed'):null,locked:yes(fc?.[0]),complete:yes(fc?.[1]),storage:s.health.storage.label,revision:fc?.[13],
      profile:profiles[cfg?.[0]],selected:sourceNames[get(122,500)?.[0]??get(110)?.[0]],active:['None','PPM','AP','USB'][get(122,500)?.[1]],inputHealth:s.input.label,
      rpy:s.imu?[s.imu.roll,s.imu.pitch,s.imu.yaw].map(v=>fmt(v,'°',1)).join(' / '):blank,
      rates:triple(imu?.slice(0,3)),imuHealth:s.health.sensor.label,candidate:triple(sensor.offsets,4),faces:sensor.faces.size+' / 6',sensorNote:sensor.note||'Choose a position to capture.',bias:triple(sensor.gyro),afterGyro:sensor.gyro&&imu?triple(imu.slice(0,3).map((v,i)=>v-sensor.gyro[i])):blank,
      flightCh:flight?'CH'+flight[0]:blank,modeLow:modes[flight?.[4]],modeHigh:modes[flight?.[5]],currentMode:s.status?modes[s.status[1]?0:1]:blank,
      armTime:fmt(arm?.[4],' s'),disarmTime:fmt(arm?.[5],' s'),idleTime:fmt(arm?.[6],' s'),armThr:fmt(arm?.[0],' µs'),
      escState:ends[fc?.[3]],mask:fc?String([0,1,2,3].filter(i=>fc[4]&(1<<i)).length)+' / 4':blank,sensorVerified:yes(fc?.[5]),rxVerified:yes(fc?.[6]),
      pwm:dev?dev[7]+' Hz · '+dev[8]+' bit':blank,duty:dev?dev[9]+' – '+dev[10]:blank,rawStatus:rawFresh?raw[8]+' channels':'Waiting for raw PPM',rxSamples:endpoints?.samples??0,
      angleScale:fmt(flight?.[1],'',3),rateScale:fmt(flight?.[2],'',3),yawScale:fmt(flight?.[3],'',3),deadband:fmt(cfg?.[6],' µs'),targets:triple(get(23,500)?.slice(7,10)),targetAngles:triple(get(23,500)?.slice(10,12)),pending:yes(pidStatus?.[0]),pidRev:pidStatus?.[1],pidSaved:pidStatus?.[2],pidError:pidStatus?pidStatus[3]||'OK':blank
    };
    for(const [k,v] of Object.entries(values))set(k,v);
    for(const g of [2,3])for(let i=0;i<(g===2?9:6);i++)set('gain'+g+'-'+i,fmt(get(g)?.[i],'',3));
    for(let i=0;i<3;i++){
      set('off'+i,fmt(base?.[i],'',4));
      set('after'+i,imu&&base?fmt(imu[i+3]-base[i]+(offsetDraft[i]??base[i]),'',4):blank);
    }
    const functions=['Roll','Pitch','Throttle','Yaw'];
    for(let i=0;i<8;i++){
      const live=rawFresh&&i<raw[8]?raw[i]:null;
      const roles=functions.filter((unused,j)=>cfg?.[j+2]===i+1);if(flight?.[0]===i+1)roles.push('Flight mode');
      set('use'+i,roles.join(' / ')||(cfg?'AUX':null));
      set('ch'+i,fmt(live));
      set('min'+i,Number.isFinite(endpoints?.min[i])?endpoints.min[i]:cal?.[i*4]);set('max'+i,Number.isFinite(endpoints?.max[i])?endpoints.max[i]:cal?.[i*4+2]);set('center'+i,cal?.[i*4+1]);set('reverse'+i,cal?(cal[i*4+3]?'Reversed':'Normal'):blank);
      const meter=root.querySelector('[data-meter="ch'+i+'"]');if(meter)meter.style.width=Number.isFinite(live)?Math.max(0,Math.min(100,(live-1000)/10))+'%':'0';
      if(i<4){set('motor'+i,fmt(s.motor?.[i],' µs'));const bar=root.querySelector('[data-meter="motor'+i+'"]');if(bar)bar.style.width=Math.min(100,Math.max(0,((s.motor?.[i]??1000)-1000)/10))+'%';}
    }
    for(const [i,x,y] of [[0,3,2],[1,0,1]]){
      const stick=root.querySelector('[data-stick="'+i+'"]');if(!stick)continue;
      // Group 22 is normalized into roll, pitch, throttle, yaw order by the FC.
      set('stick'+i,s.channels?s.channels[x]+' / '+s.channels[y]+' µs':null);
      stick.hidden=!s.channels;
      if(s.channels){const clamp=v=>Math.min(94,Math.max(6,(v-1000)/10));stick.style.left=clamp(s.channels[x])+'%';stick.style.top=(100-clamp(s.channels[y]))+'%';}
    }
    for(const node of root.querySelectorAll('[data-scene]')){
      const kind=node.dataset.scene;
      node.hidden=kind==='live'&&!s.imu;
      if(node.hidden)continue;
      airframe(node,pickedProfile===1?'areion250':'areion450',kind==='target'?poses[pose][3]:kind==='live'?[s.imu.roll,s.imu.pitch,s.imu.yaw??0]:[0,0,sceneOrbit]);
    }
    const sel=root.querySelector('[data-select="Aircraft preview"]');if(sel)sel.value=String(pickedProfile);
    for(const ph of root.querySelectorAll('[data-phase]'))ph.classList.toggle('on',fc?.[3]!==5 && [1,2,3,4].slice(0,Math.min(4,fc?.[3]??0)).includes(Number(ph.dataset.phase)+1));
    const chart=root.querySelector('[data-response]');if(chart)drawResponse(chart,ctx,responseAxis,!!responseAngle);
    const canSample=confirmed&&gate(ctx)&&!!imu&&!!base&&!sensor.active;
    const buttons={back:!step,next:!confirmed,pose:!canSample||sensor.faces.has(pose),gyro:!canSample,'rx-capture':!rxRun&&(!confirmed||!gate(ctx)||!rawFresh||get(122,500)?.[0]!==0||!get(122,500)?.[2])};
    for(const [key,disabled] of Object.entries(buttons)){const b=root.querySelector('[data-act="'+key+'"]');if(b)b.disabled=!!disabled;}
    const rx=root.querySelector('[data-act="rx-capture"]');if(rx)rx.textContent=rxRun?'Stop capture':'Capture range';
    const progress=root.querySelector('[data-progress="sensor"]');if(progress)progress.value=sensor.active?sensor.progress:sensor.faces.has(pose)?1:0;
  }
  function reset(){last=null;clearSessions();if(page==='wizard')step=0;draw();}
  root.addEventListener('change',event=>{
    const el=event.target;
    if(el.hasAttribute('data-props')){
      confirmed=el.checked;
      if(!confirmed){rxRun=false;if(sensor.active)sensor.stop('Capture cancelled.');if(page==='wizard')step=0;}
      draw();
    } else if(el.dataset.select==='Aircraft preview'){pickedProfile=Number(el.value);profileEdited=true;if(last)update(last);}
    else if(el.dataset.select==='Loop'){responseAngle=Number(el.value);if(responseAngle)responseAxis=Math.min(1,responseAxis);draw();}
    else if(el.dataset.select==='Axis'){responseAxis=Number(el.value);if(last)update(last);}
    else if(el.dataset.select==='Target pose'){pose=Number(el.value);if(last)update(last);}
  });
  root.addEventListener('input',event=>{
    const key=event.target.dataset.off;if(key===undefined)return;
    const x=event.target.valueAsNumber;offsetDraft[Number(key)]=Number.isFinite(x)&&Math.abs(x)<=.5?x:null;if(last)update(last);
  });
  root.addEventListener('click',event=>{
    const el=event.target.closest('button');if(!el||el.disabled)return;
    if(el.dataset.nav){last?.navigate('configuration/'+el.dataset.nav);return;}
    if(el.hasAttribute('data-pid')){subPID=Number(el.dataset.pid);draw();return;}
    if(el.hasAttribute('data-step')){if(confirmed||el.dataset.step==='0'){if(sensor.active)sensor.stop('Capture cancelled.');rxRun=false;step=Number(el.dataset.step);draw();}return;}
    switch(el.dataset.act){
      case 'full':last?.fullConsole();break;
      case 'next':case 'back':if(sensor.active)sensor.stop('Capture cancelled.');rxRun=false;step=Math.max(0,Math.min(9,step+(el.dataset.act==='next'?1:-1)));draw();break;
      case 'rotate':sceneOrbit=(sceneOrbit+45)%360;break;
      case 'pose':case 'gyro':if(last&&gate(last)&&confirmed&&last.snapshot.imu)sensor.begin(el.dataset.act==='pose'?pose:'gyro',last.clock,last.group(6));break;
      case 'reset-sensor':sensor.clear();break;
      case 'rx-clear':endpoints=null;rxRun=false;break;
      case 'rx-capture':if(!rxRun){endpoints={min:Array(8).fill(Infinity),max:Array(8).fill(-Infinity),samples:0,count:0};}rxRun=!rxRun;break;
    }
    if(last)update(last);
  });
  draw();
  return {show,update,onPacket,reset};
}
