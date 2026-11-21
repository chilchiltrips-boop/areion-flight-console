import {defaults} from './config-commands.js';
import {ConfigPanel,editor,extras} from './config-panel.js';
import {airframe} from './airframe.js';
import {drawResponse} from './pid-trace.js';
import {CalibrationSession} from './calibration-session.js';
import {sensorStudio,updateSensorStudio} from './sensor-studio.js';
import {tripodSession,tripodTelemetry} from './tripod/telemetry.js';
import {packGains} from './tripod/gains.js';

const panes={wizard:'Setup wizard',input:'Input / receiver',imu:'IMU',esc:'ESC / motors',pid:'PID / settings'};
const steps=['Safety & connect','Aircraft profile','Input & wiring','Sensors','PPM receiver','ESC calibration','Motor outputs','Arming & flight modes','Review & save','Verify after restart'];
const profiles=['Areion 450','Areion 250','Areion Quad X','Generic Quad X'];
const sourceNames=['PPM receiver','AP Wi-Fi channels','USB channels'];
const ends=['Not checked','Pending restart','Calibrating','Confirm ESC response','ESC response confirmed','Calibration skipped','Interrupted / failed'];
const modes=['Angle','Rate / Acro'];
const axes=['Roll','Pitch','Yaw'];
const pidTabs=[
  ['pid','Gain tuning'],['pid-stick','Stick response'],['pid-receiver','Receiver & arming'],
  ['pid-simulator','Tripod simulator'],['pid-tripod','Live tripod']
];
const motorNames=['Front left · CW','Front right · CCW','Rear right · CW','Rear left · CCW'];
const blank='—';
const fmt=(v,unit='',digits=0)=>Number.isFinite(v)?v.toFixed(digits)+unit:blank;
const reading=(key)=>'<strong data-r="'+key+'">—</strong>';
const box=(title,html)=>'<section class="cfg-card"><h3>'+title+'</h3>'+html+'</section>';
const row=(title,key)=>'<div class="cfg-kv"><span>'+title+'</span>'+reading(key)+'</div>';
const opt=(name,arr,sel=0)=>'<select aria-label="'+name+'" data-select="'+name+'">'+arr.map((s,i)=>'<option value="'+i+'" '+(sel===i?'selected':'')+'>'+s+'</option>').join('')+'</select>';
const act=(id,text,cls='')=>'<button type="button" class="cfg-btn '+cls+'" data-act="'+id+'">'+text+'</button>';

const canvas=(name='live')=>'<canvas data-scene="'+name+'" class="cfg-scene" role="img" aria-label="'+(name==='live'?'Reported aircraft attitude':'Areion Quad X model')+'"></canvas>';
const spark=(tag,i)=>'<div class="cfg-track"><i data-meter="'+tag+i+'"></i></div>';
const channelCell=(i)=>'<tr><th scope="row">CH'+(i+1)+'</th><td>'+reading('use'+i)+'</td><td>'+reading('ch'+i)+spark('ch',i)+'</td><td>'+reading('min'+i)+'</td><td>'+reading('center'+i)+'</td><td>'+reading('max'+i)+'</td><td>'+extras.reverse(i)+'</td></tr>';
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
  const calibration=new CalibrationSession();
  const sensor=calibration.sensor;
  const sensorControls=()=>({confirmed,entered:hardware.entered});
  const sensorVisible=()=>!root.hidden && !document.hidden && (page==='imu' || (page==='wizard' && step===3));
  let page='wizard',step=0,confirmed=false,subPID=0,pickedProfile=0,last=null,linkId=null;
  let endpoints=null,rxRun=false,statusRow=null;
  let tabRoots,sceneOrbit=0,profileEdited=false,responseAxis=0,responseAngle=0;
  let restartView=false,escProfile=1,resumeStep=false;
  const hardware=new ConfigPanel(root,{
    state:()=>({page,step,confirmed,profile:pickedProfile,endpoints,rxRun}),
    calibration,sensorControls,sensorVisible,
    clearReceiver:()=>{endpoints=null;rxRun=false;},
    clearCaptures:()=>{calibration.stop('Calibration stopped. Start again when ready.');rxRun=false;},
    resetDraft:()=>{calibration.reset();endpoints=null;rxRun=false;profileEdited=false;pickedProfile=0;}
  });
  let tripod=null,benchState=null;
  const suspend=(opts={})=>{tripod?.suspend();return hardware.suspend(opts);};
  window.addEventListener('blur',()=>suspend());
  window.addEventListener('pagehide',()=>suspend());
  document.addEventListener('visibilitychange',()=>{if(document.hidden)suspend();});
  function directControls(){return '<div class="cfg-actions cfg-session">'+confirmation(confirmed)+extras.begin()+extras.finalize()+'</div>';}
  function sensorEntry(){
    return '<div class="cfg-actions cfg-session">'+confirmation(confirmed)+
      '<button type="button" class="cfg-btn" data-kit="begin" data-sensor-lock>Lock kit for calibration</button>'+
      '<strong data-sensor-lock-state hidden>Arming locked</strong></div>';
  }
  function sensorFinish(){
    return '<div class="cfg-actions cfg-session" data-sensor-finish hidden>'+extras.finalize()+'</div>';
  }
  function safetyPage(){
    return box('Remove propellers',canvas('profile')+'<p>Motors can start during kit setup. Keep all propellers removed until setup is complete.</p>'+confirmation(confirmed))+
      box('Kit connection',row('Board','kit')+row('Firmware','firmware')+row('Arming','armed')+row('Setup lock','locked')+'<p>Begin setup to lock arming and load the current kit settings.</p>'+extras.begin()+extras.reset());
  }
  function aircraft(){
    return box('Aircraft profile',opt('Aircraft preview',profiles,pickedProfile)+canvas('profile')+act('rotate','Rotate model')+'<p>Changing profile loads the profile’s default gains. Saving the current profile keeps tuned gains.</p>')+
      box('Quad X',row('Saved profile','profile')+'<div class="cfg-kv"><span>Vehicle</span><strong>Multirotor</strong></div><div class="cfg-kv"><span>Frame</span><strong>Quadcopter · X</strong></div><div class="cfg-kv"><span>Motor drive</span><strong>Brushless ESC</strong></div>'+extras.profile());
  }
  function wiring(){
    return box('Areion FC A1 · fixed connections','<div class="cfg-wires">'+['D0 / GPIO 0|OUT 1|ESC 1 · M1','D1 / GPIO 1|OUT 2|ESC 2 · M2','D2 / GPIO 2|OUT 3|ESC 3 · M3','D3 / GPIO 21|OUT 4|ESC 4 · M4','D10 / GPIO 18|PPM|PPM receiver','D4 / GPIO 22|SDA|IMU SDA','D5 / GPIO 23|SCL|IMU SCL'].map(s=>{const [a,b,c]=s.split('|');return '<div><code>'+a+'</code><i></i><b>'+b+'</b><i></i><strong>'+c+'</strong></div>';}).join('')+'</div>')+
      box('Flight input',row('Selected','selected')+row('Active','active')+row('Input health','inputHealth')+'<p>Disconnect power while wiring. Connect each ESC to its matching board output.</p>'+extras.source());
  }
  function receiver() {
    return box('Receiver activity',sticks()+row('Selected input','selected')+row('Active input','active')+row('Receiver','inputHealth')+row('Switch channel','flightCh')+act('check-tx','Check transmitter')+extras.source())+
      box('PPM endpoint capture','<p>Sweep the sticks and switches through their full travel. This preview uses the raw PPM stream from the kit.</p><div class="cfg-actions">'+act('rx-capture','Capture range')+act('rx-clear','Clear range')+'</div>'+row('Raw PPM','rawStatus')+row('Samples','rxSamples')+extras.receiver())+
      '<section class="cfg-card cfg-wide"><h3>Physical PPM channels</h3>'+extras.mapping()+kvTable(['Channel','Function','Raw (µs)','Min','Center','Max','Direction'],Array.from({length:8},(_,i)=>channelCell(i)).join(''))+'<p>Min and max show captured ranges during this local check. Direction and channel assignment can be changed before saving.</p></section>';
  }
  function esc(){
    return box('ESC calibration',opt('ESC profile',['Standard ESC · 50 Hz','PWM ESC · 250 Hz','OneShot ESC'],escProfile)+row('Kit state','escState')+row('Output PWM','pwm')+row('Firmware range (duty)','duty')+'<div class="cfg-sequence">'+['Schedule','Power cycle','Endpoints','Confirm'].map((s,i)=>'<span data-phase="'+i+'">'+s+'</span>').join('')+'</div>'+extras.esc())+
      box('Motor outputs',motorRows()+row('Verified outputs','mask')+'<p>Readings are commanded pulses. Check rotation physically with the propellers removed.</p>'+extras.motors());
  }
  function arming(){
    return box('Arming timings',extras.arming())+
      box('Flight modes',row('Current mode','currentMode')+extras.modes());
  }
  function review(){
    return box(step===9?'Verify after restart':'Setup review',row('Kit identity','kit')+row('Firmware revision','revision')+row('Setup lock','locked')+row('Setup complete','complete')+row('Storage','storage'))+
      box('Controller checks',row('Sensors','sensorVerified')+row('Receiver','rxVerified')+row('ESC','escState')+row('Motors','mask')+(step===9?'<p>Save setup on the kit first. Reconnect the same kit after a restart to compare all eight saved groups.</p>'+extras.verify():extras.finalize()));
  }
  function configurationResume(){return box('Resume setup',confirmation(confirmed)+extras.begin());}
  function wizard(){
    const work=[safetyPage,aircraft,wiring,sensorStudio,receiver,esc,()=>box('Motor outputs',motorRows()+row('Verified outputs','mask')+extras.motors())+box('Motor order',canvas('profile')+'<p>M1 front left · M2 front right · M3 rear right · M4 rear left.</p>'),arming,review,review];
    return '<div class="cfg-wiz"><nav class="cfg-steps" aria-label="Setup steps">'+steps.map((s,i)=>'<button class="cfg-step" type="button" data-step="'+i+'" '+(i===step?'aria-current="step"':'')+(i&&!confirmed&&!(restartView&&i===9)?' disabled':'')+'><span>'+String(i+1).padStart(2,'0')+'</span>'+s+'</button>').join('')+'</nav><div><div class="cfg-wiz-head"><div><small>Setup wizard</small><h2>'+steps[step]+'</h2></div><small>Step '+(step+1)+' / '+steps.length+'</small></div><div class="cfg-grid">'+(step>0&&(!confirmed||!hardware.entered)&&!restartView?configurationResume():'')+work[step]()+'</div><div class="cfg-wiz-actions">'+act('back','Back')+(step<9?act('next','Next','cfg-primary'):'')+'</div></div></div>';
  }
  let stickChoice=0,stickPulse=1500;
  function stickCurve(){
    return '<section class="cfg-card cfg-stick-preview"><div class="pid-line"><h3>Stick preview</h3>'+opt('Stick preview axis',['Angle · Roll / Pitch','Rate · Roll / Pitch','Yaw rate'],stickChoice)+'</div><svg viewBox="0 0 300 162" role="img" aria-label="Stick response curve">'+
      '<path class="cfg-curve-grid" d="M40 12H285M40 76H285M40 140H285M40 12V140M101 12V140M162 12V140M224 12V140M285 12V140"/><g><text x="2" y="18" data-curve-max></text><text x="22" y="80">0</text><text x="2" y="138" data-curve-min></text><text x="28" y="156">1000</text><text x="149" y="156">1500</text><text x="264" y="156">2000</text></g>'+
      '<line class="cfg-curve-base" x1="40" x2="285"/><line class="cfg-curve-line" x1="40" x2="285"/><circle class="cfg-curve-dot" r="4"/></svg><div class="pid-line"><strong data-stick-pulse></strong><strong data-stick-target></strong></div><input type="range" min="1000" max="2000" value="'+stickPulse+'" data-stick-pulse-control aria-label="Stick preview pulse"><small>Editor values · local preview</small></section>';
  }
  function pid(){
    const matrix=(g,n,title,caption)=>{
      const copyAxis='Simulator axis for '+title;
      const prior=axes.indexOf(benchState?.lastAxis);
      const table=kvTable(['',...axes.slice(0,n)],['P · Proportional','I · Integral','D · Derivative'].map((k,i)=>'<tr><th scope="row">'+k+'</th>'+Array.from({length:n},(_,j)=>'<td>'+editor(g,i*n+j,k+' '+axes[j]+' '+(g===2?'rate':'angle'))+'</td>').join('')+'</tr>').join(''));
      return '<section class="cfg-card pid-matrix"><div class="pid-line"><h3>'+title+' <small>'+caption+'</small></h3><label><input type="checkbox" data-confirm="axis-'+g+'"> Link roll/pitch</label></div>'+table+'<div class="cfg-actions">'+
        ['read','saved','revert'].map((action,i)=>'<button type="button" class="cfg-btn" data-kit="'+action+'-'+g+'">'+['Read FC','Read saved','Revert'][i]+'</button>').join('')+
        (subPID===4?opt(copyAxis,axes.slice(0,n),prior>=0&&prior<n?prior:0)+'<button type="button" class="cfg-btn" data-stage-group="'+g+'" disabled>Copy sim gains to editor</button>':'')+
        extras.pid(g)+'</div><small>'+reading('boardGain')+'</small></section>';
    };
    const tracking=()=>'<section class="cfg-card cfg-tracking"><div class="pid-line"><h3>Tracking response</h3><div>'+opt('Loop',['Rate','Angle'],responseAngle)+opt('Axis',axes.slice(0,responseAngle?2:3),responseAxis)+'</div></div><small>Measured <b class="cfg-meas">━</b> &nbsp; Target <b class="cfg-target">━</b> · '+(responseAngle?'degrees':'degrees / second')+' · 10 s</small><canvas data-response class="cfg-response" role="img" aria-label="Measured and target response over ten seconds"></canvas></section>';
    const matrices=()=>'<div class="cfg-pid-matrices">'+matrix(2,3,'Rate PID','Inner loop')+matrix(3,2,'Attitude PID','Outer loop')+'</div>';
    const benchSlot='<div data-tripod-slot role="region" aria-label="Tripod workbench"></div>';
    const views=[
      ()=>matrices()+'<div class="cfg-gain-plots">'+tracking()+stickCurve()+'</div>',
      ()=>'<div class="cfg-pid-matrices">'+box('Flight mode & stick response',extras.response()+row('Input deadband','deadband')+extras.modes())+stickCurve()+'</div>',
      ()=>'<div class="cfg-pid-matrices">'+box('Receiver & arming',extras.arming()+act('go-arm','Open setup settings'))+box('Board configuration',row('Aircraft profile','profile')+row('Input source','selected')+row('Setup revision','revision')+row('Stored PID revision','pidSaved'))+'</div>',
      ()=>benchSlot,()=>benchSlot+matrices()
    ];
    return '<section class="cfg-pid"><div class="cfg-pid-head"><h2><img src="./assets/console/launch-pid.svg" alt=""> PID tuning</h2><div class="cfg-tabs">'+
      [0,3,4,1,2].map(i=>'<button type="button" data-pid="'+i+'" aria-pressed="'+(subPID===i)+'">'+pidTabs[i][1]+'</button>').join('')+'</div></div>'+
      (subPID===3?'':'<div class="cfg-pid-state">'+reading('pidSummary')+extras.bench()+'</div>')+views[subPID]()+'</section>';
  }
  function prepareTripod(slot,kind){
    if(!document.querySelector('link[data-tripod-css]')){
      const css=document.createElement('link');css.rel='stylesheet';css.href=new URL('./tripod/bench.css',import.meta.url);
      css.dataset.tripodCss='';document.head.append(css);
    }
    import('./tripod/bench.js').then(({createBenchState,mountTripod})=>{
      if(!slot.isConnected||root.hidden)return;
      benchState??=createBenchState();
      tripod=mountTripod(slot,kind,benchState);
      if(last)update(last);
    }).catch(()=>{if(slot.isConnected)slot.textContent='Tripod view could not load. Reopen this tab to retry.';});
  }
  function drawCurve(ctx){
    const graph=root.querySelector('.cfg-stick-preview');if(!graph)return;
    const i=stickChoice+1,active=ctx.group(7)?.[i],scale=hardware.draft.get('7:'+i)??active??defaults[7][i];
    const top=Math.max(10,Math.ceil(Math.max(scale,active??0)*50)*10),unit=i===1?'°':'°/s';
    const y=(pulse,gain)=>76-(pulse-1500)*gain/top*64;
    for(const [line,gain] of [['.cfg-curve-line',scale],['.cfg-curve-base',active??scale]]){
      const el=graph.querySelector(line);el.setAttribute('y1',y(1000,gain));el.setAttribute('y2',y(2000,gain));}
    const dot=graph.querySelector('circle');dot.setAttribute('cx',40+(stickPulse-1000)*.245);dot.setAttribute('cy',y(stickPulse,scale));
    for(const [selector,value] of [['[data-curve-max]','+'+top+unit],['[data-curve-min]','−'+top+unit],['[data-stick-pulse]',stickPulse+' µs'],['[data-stick-target]',((stickPulse-1500)*scale).toFixed(1)+unit]])graph.querySelector(selector).textContent=value;
  }
  function draw(){
    tripod?.dispose();tripod=null;
    root.innerHTML='<nav class="cfg-tabs" aria-label="Configuration sections">'+Object.entries(panes).map(([key,title])=>'<button type="button" data-nav="'+key+'" '+(key===page?'aria-current="page"':'')+'>'+title+'</button>').join('')+'</nav>'+
      (page==='wizard'?wizard():page==='pid'?pid():page==='imu'?sensorEntry()+'<div class="cfg-grid">'+sensorStudio()+'</div>'+sensorFinish():directControls()+'<div class="cfg-grid">'+({input:receiver,esc})[page]()+'</div>')+'<div role="status" class="cfg-operation" data-operation></div>';
    tabRoots=new Map();
    root.querySelectorAll('[data-r]').forEach(el=>{const key=el.dataset.r;if(!tabRoots.has(key))tabRoots.set(key,[]);tabRoots.get(key).push(el);});
    const slot=root.querySelector('[data-tripod-slot]');if(slot)prepareTripod(slot,subPID===3?'sim':'live');
    if(last) update(last);
  }
  function show(name='wizard'){
    const pidIndex=pidTabs.findIndex(([route])=>route===name);
    const target=pidIndex!==-1?'pid':Object.hasOwn(panes,name)?name:'wizard';
    if(target!==page || target==='pid' && subPID!==pidIndex)hardware.pageChange();
    if(pidIndex!==-1)subPID=pidIndex;
    restartView=name==='restart';if(restartView)step=9;
    if(page!==target) rxRun=false;
    page=target;draw();
  }
  function set(key,value){
    const text=value==null||value===''?blank:String(value);
    for(const el of tabRoots.get(key)??[]) if(el.textContent!==text)el.textContent=text;
  }
  function gate(ctx) {return !ctx.replay && ctx.state==='connected' && ctx.group(120,500)?.[0]===false;}
  function clearSessions() {
    calibration.reset();endpoints=null;rxRun=false;statusRow=null;
    confirmed=false;linkId=null;
  }
  function syncSafety(ctx){
    const id=ctx.group(130)?.[15];
    if(id&&linkId&&linkId!==id)clearSessions();
    if(id)linkId=id;
    calibration.sync(ctx,sensorControls());
    if(rxRun&&(!gate(ctx)||!hardware.lock)){rxRun=false;endpoints=null;}
  }
  function onPacket(packet,source) {
    if(root.hidden || document.hidden || !['usb','ap'].includes(source)) {
      calibration.stop('Calibration stopped. Return to live sensor data.');rxRun=false;return;
    }
    if(packet.group===120)statusRow=packet;
    if(tripod&&last){
      if(benchState?.capture.session)benchState.capture.packet(packet,tripodSession(last));
      if(tripod.mirroring&&[22,120,122].includes(packet.group))tripod.receive(tripodTelemetry(last,packet.at));
    }
    if(sensor.active && last && sensorVisible()){
      calibration.onPacket(packet,last,sensorControls());
    }
    if(packet.group===131){
      if(rxRun){
        const v=packet.values,n=v[8],timeout=last?.model.get(112,packet.at,Infinity)?.[0]??250;
        const selected=last?.model.get(122,packet.at,500);
        if(!v[9]||n<4||n>8||v.slice(0,n).some(x=>x<900||x>2100)||v.slice(n,8).some(x=>x!==0)||v[10]>=timeout||!statusRow || statusRow.values[0]!==false || packet.at-statusRow.at>500 || selected?.[0]!==0 || !selected?.[2]){rxRun=false;endpoints=null;return;}
        if(endpoints.count&&endpoints.count!==n){rxRun=false;endpoints=null;return;}
        endpoints.count=n;
        for(let i=0;i<n;i++){endpoints.min[i]=Math.min(endpoints.min[i],v[i]);endpoints.max[i]=Math.max(endpoints.max[i],v[i]);}
        if(!endpoints.samples)endpoints.first=packet.at;
        endpoints.last=packet.at;endpoints.samples++;
      }
    }
  }
  function update(ctx){
    last=ctx;
    const get=(id,age)=>ctx.group(id,age),s=ctx.snapshot,fc=get(130,500),cfg=get(134),dev=get(125),arm=get(4),flight=get(7),raw=get(131,500),cal=get(132),pidStatus=get(136,1500);
    const rawRecord=ctx.model.frames.get(131);
    const rawFresh=raw?.[9]&&raw[8]>=4&&raw[8]<=8&&rawRecord&&raw[10]+ctx.clock-rawRecord.at<(get(112)?.[0]??250);
    const yes=v=>typeof v==='boolean'?(v?'Yes':'No'):blank;
    const triple=(arr,d=2)=>arr?arr.map(v=>fmt(v,'',d)).join(' / '):blank;
    syncSafety(ctx);
    if(!confirmed&&step>0&&page==='wizard'&&!restartView&&!resumeStep){step=0;draw();return;}
    if(!profileEdited && cfg) pickedProfile=cfg[0];
    const values={
      boardGain:ctx.state==='connected'?'Controller values':'Firmware defaults · awaiting FC read',
      pidSummary:pidStatus?(pidStatus[3]|| (pidStatus[0]?'PID · Active in RAM, save after disarm':'PID · Saved revision '+pidStatus[2])):'PID · Status unavailable',
      kit:get(130)?.[15],firmware:dev?.[0],armed:s.status?(s.status[0]?'Armed':'Disarmed'):null,locked:yes(fc?.[0]),complete:yes(fc?.[1]),storage:s.health.storage.label,revision:fc?.[13],
      profile:profiles[cfg?.[0]],selected:sourceNames[get(122,500)?.[0]??get(110)?.[0]],active:['None','PPM','AP','USB'][get(122,500)?.[1]],inputHealth:s.input.label,
      flightCh:flight?'CH'+flight[0]:blank,modeLow:modes[flight?.[4]],modeHigh:modes[flight?.[5]],currentMode:s.status?modes[s.status[1]?0:1]:blank,
      armTime:fmt(arm?.[4],' s'),disarmTime:fmt(arm?.[5],' s'),idleTime:fmt(arm?.[6],' s'),armThr:fmt(arm?.[0],' µs'),
      escState:ends[fc?.[3]],mask:fc?String([0,1,2,3].filter(i=>fc[4]&(1<<i)).length)+' / 4':blank,sensorVerified:yes(fc?.[5]),rxVerified:yes(fc?.[6]),
      pwm:dev?dev[7]+' Hz · '+dev[8]+' bit':blank,duty:dev?dev[9]+' – '+dev[10]:blank,rawStatus:rawFresh?raw[8]+' channels':'Waiting for raw PPM',rxSamples:endpoints?.samples??0,
      angleScale:fmt(flight?.[1],'',3),rateScale:fmt(flight?.[2],'',3),yawScale:fmt(flight?.[3],'',3),deadband:fmt(cfg?.[6],' µs'),targets:triple(get(23,500)?.slice(7,10)),targetAngles:triple(get(23,500)?.slice(10,12)),pending:yes(pidStatus?.[0]),pidRev:pidStatus?.[1],pidSaved:pidStatus?.[2],pidError:pidStatus?pidStatus[3]||'OK':blank
    };
    for(const [k,v] of Object.entries(values))set(k,v);
    for(const g of [2,3])for(let i=0;i<(g===2?9:6);i++)set('gain'+g+'-'+i,fmt(get(g)?.[i],'',3));
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
      if(kind==='profile')airframe(node,pickedProfile===1?'areion250':'areion450',[0,0,sceneOrbit]);
    }
    const sel=root.querySelector('[data-select="Aircraft preview"]');if(sel)sel.value=String(pickedProfile);
    for(const ph of root.querySelectorAll('[data-phase]'))ph.classList.toggle('on',fc?.[3]!==5 && [1,2,3,4].slice(0,Math.min(4,fc?.[3]??0)).includes(Number(ph.dataset.phase)+1));
    if(page==='pid')drawCurve(ctx);
    const chart=root.querySelector('[data-response]');if(chart)drawResponse(chart,ctx,responseAxis,!!responseAngle);
    const sensorPending=step===3 && (sensor.active || sensor.ready && !calibration.saved || !fc?.[5]);
    const buttons={back:!step,next:!confirmed||(hardware.live&&!hardware.lock&&step<8)||(hardware.live&&sensorPending),
      'rx-capture':!rxRun&&(!confirmed||!hardware.lock||!gate(ctx)||!rawFresh||get(122,500)?.[0]!==0||!get(122,500)?.[2])};
    for(const [key,disabled] of Object.entries(buttons)){const b=root.querySelector('[data-act="'+key+'"]');if(b)b.disabled=!!disabled;}
    const rx=root.querySelector('[data-act="rx-capture"]');if(rx)rx.textContent=rxRun?'Stop capture':'Capture range';
    hardware.refresh(ctx);
    if(tripod){
      tripod.update(tripodTelemetry(ctx),{clock:ctx.clock,frames:ctx.model.frames,get rows(){return ctx.rows;}});
      for(const btn of root.querySelectorAll('[data-stage-group]'))btn.disabled=!hardware.live||hardware.busy||!ctx.group(Number(btn.dataset.stageGroup));
    }
    if(sensorVisible()){
      const lockControl=root.querySelector('[data-sensor-lock]');
      if(lockControl)lockControl.hidden=hardware.lock;
      const lockState=root.querySelector('[data-sensor-lock-state]');
      if(lockState)lockState.hidden=!hardware.lock;
      const finish=root.querySelector('[data-sensor-finish]');
      if(finish)finish.hidden=!(hardware.lock&&fc?.[5]&&!sensor.active&&(calibration.saved||!sensor.ready));
      const disabledReason=calibration.gate(ctx,sensorControls());
      updateSensorStudio(root,sensor,{
        ctx,canStart:!disabledReason&&!hardware.busy&&!sensor.active,disabledReason,
        saved:calibration.saved && fc?.[5]===true,working:hardware.busy,profile:pickedProfile===1?'areion250':'areion450'
      });
    }
  }
  function reset(){resumeStep=page==='wizard'&&step>0;last=null;clearSessions();hardware.reset();draw();}
  root.addEventListener('wheel',event=>{if(event.target.matches('input[type="number"],select')&&document.activeElement===event.target)event.target.blur();},{passive:true});
  root.addEventListener('change',event=>{
    const el=event.target;
    if(el.hasAttribute('data-props')){
      confirmed=el.checked;
      if(!confirmed){hardware.suspend();rxRun=false;if(page==='wizard')step=0;}
      draw();
    } else if(el.dataset.select==='ESC profile'){escProfile=Number(el.value);hardware.confirm.delete('compatible');hardware.confirm.delete('tones');hardware.confirm.delete('skip');hardware.refresh(last);}
    else if(el.dataset.select==='Aircraft preview'){pickedProfile=Number(el.value);profileEdited=true;if(last)update(last);}
    else if(el.dataset.select==='Stick preview axis'){stickChoice=Number(el.value);if(last)drawCurve(last);}
    else if(el.dataset.select==='Loop'){responseAngle=Number(el.value);if(responseAngle)responseAxis=Math.min(1,responseAxis);draw();}
    else if(el.dataset.select==='Axis'){responseAxis=Number(el.value);if(last)update(last);}
  });
  root.addEventListener('input',event=>{
    if(event.target.hasAttribute('data-stick-pulse-control')){stickPulse=Number(event.target.value);if(last)drawCurve(last);return;}
  });
  root.addEventListener('click',event=>{
    const el=event.target.closest('button');if(!el||el.disabled)return;
    if(el.dataset.nav){last?.navigate('configuration/'+el.dataset.nav);return;}
    if(el.hasAttribute('data-pid')){last?.navigate('configuration/'+pidTabs[Number(el.dataset.pid)][0]);return;}
    if(el.hasAttribute('data-stage-group')&&benchState){
      const g=Number(el.dataset.stageGroup),values=packGains({...benchState.sim.pid,...benchState.sim.pendingPID},g);
      const axis=el.closest('.pid-matrix').querySelector('select[data-select]');
      if(values&&axis)hardware.stagePid(g,values,Number(axis.value));
      return;
    }
    if(el.closest('[data-tripod]'))return;
    if(el.hasAttribute('data-step')){if(confirmed||el.dataset.step==='0'){hardware.pageChange();restartView=false;resumeStep=false;rxRun=false;step=Number(el.dataset.step);draw();}return;}
    switch(el.dataset.act){

      case 'go-arm':step=7;resumeStep=true;last?.navigate('configuration/wizard');return;
      case 'check-tx':last?.checkTransmitter();break;
      case 'next':case 'back':hardware.pageChange();restartView=false;resumeStep=false;rxRun=false;step=Math.max(0,Math.min(9,step+(el.dataset.act==='next'?1:-1)));if(step===4&&last?.group(134)?.[1]>0)step+=el.dataset.act==='next'?1:-1;draw();break;
      case 'rotate':sceneOrbit=(sceneOrbit+45)%360;break;
      case 'start-sensor':void hardware.run('start-sensor');break;
      case 'cancel-sensor':calibration.stop('Calibration cancelled. Start again when ready.');break;
      case 'rx-clear':endpoints=null;rxRun=false;break;
      case 'rx-capture':if(!rxRun){endpoints={min:Array(8).fill(Infinity),max:Array(8).fill(-Infinity),samples:0,count:0};}rxRun=!rxRun;break;
    }
    if(last)update(last);
  });
  draw();
  return {show,update,onPacket,reset,suspend};
}
