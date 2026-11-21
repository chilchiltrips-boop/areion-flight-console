import {banks, limits} from './gains.js';
import {advanceSimulator, calibrateLevel, clamp, controlSettings, DEFAULT_PID, disturb, resetIntegrators, resetSimulator,
  setFlightMode, setSimulatorGains} from './tripod-physics.js';
import {bindSticks, inputNames, PAD_TRAVEL, SimulatorInput} from './inputs.js';
import {createTripodAudio} from './tripod-audio.js';
import {exercises, practiceStep, practiceTicks, practiceTrial} from './tripod-experiments.js';
import {drawPlot,plotColors} from './plot.js';

import {pulseForAxis} from '../stick-geometry.js';

const axisTitle = key => key[0].toUpperCase()+key.slice(1);
const axes=['roll','pitch','yaw'];
const num=(value,precision=1)=>Number.isFinite(value)?value.toFixed(precision):'—';
function traceSpec(chart, axis, mode) {
  const rate=axis==='yaw'||mode==='acro';
  if(chart==='terms')return {fields:['p','i','d'],labels:['P','I','D'],unit:null};
  if(chart==='travel')return {fields:['travel'],labels:['Travel'],unit:'cm'};
  if(chart==='motors'||chart==='rpm')return {fields:[0,1,2,3].map(i=>chart+i),labels:['M1','M2','M3','M4'],unit:chart==='rpm'?'RPM':'µs'};
  return {fields:[rate?'rate':'angle',rate?'targetRate':'targetAngle'],labels:['Measured','Target'],unit:rate?'°/s':'°'};
}
export function mountSimulator(ui, state) {
  const {root, field, action, out, signal} = ui, sim=state.sim;
  const prefs=state.simControls??={source:'local',mode:sim.mode,axis:'roll',plotLoop:'auto',sound:true,volume:55,profile:'normal',airflow:'normal'};
  const input=new SimulatorInput(sim,prefs.source);
  sim.settings=controlSettings();
  let kit=null,axis=prefs.axis,bank='',chart='response',graphFrozen=false,tilting=false;
  let samples=[],frozen=null,lastSample=-Infinity,graphEnd=sim.time;
  let playTick=null,previewTimer=null;
  prefs.livePreview??=true;
  const audio=createTripodAudio(message=>{
    const status={'AUDIO UNAVAILABLE':'Audio unavailable','AUDIO INITIALIZATION FAILED':'Audio unavailable','TAP SOUND ON TO UNLOCK AUDIO':'Toggle sound to enable audio','AUDIO ACTIVE • MOTOR PITCH FOLLOWS RPM':'Playing · motor RPM'};
    out('audioState',status[message]??'');
  });
  const gainFields=new Map([...root.querySelectorAll('[data-gain]')].map(el=>[el.dataset.gain,el]));
  const kitInputLink=root.querySelector('[data-kit-input-link]');
  const pads=root.querySelectorAll('[data-pad]'), plot=root.querySelector('[data-tp-plot=sim]');
  const comparisonPlot=root.querySelector('[data-tp-plot=compare]');
  const applied=()=>({...sim.pid,...sim.pendingPID});
  state.practiceBaseline??=structuredClone(DEFAULT_PID);
  prefs.exercise??='step';
  const gainPanel=root.querySelector('.tp-bank'),outerLabel=gainPanel.querySelector('[data-loop=angle] small');
  const metricLabels=root.querySelectorAll('[data-metric]');
  let comparison=null,comparisonKey='',matching=true;
  const dirty=()=>Object.keys(state.simEdits??{}).length>0;
  const controls=bindSticks(root,sim,()=>input.local&&playTick===null,signal,()=>sim.running?stop('Stopped'):start(),drawControls);
  function showGains(){
    const gains=applied();
    for(const [key,el] of gainFields){
      const [name,term]=key.split('.');
      el.value=state.simEdits?.[key]??gains[name][term];el.removeAttribute('aria-invalid');
    }
  }
  function applyEdits(automatic=false,replay=true){
    clearTimeout(previewTimer);
    const next=Object.fromEntries(banks.map(name=>[name,{}]));
    let invalid=null;
    for(const [key,el] of gainFields){
      const [name,term]=key.split('.'),value=el.valueAsNumber;
      next[name][term]=value;
      const ok=Number.isFinite(value)&&value>=0&&value<=limits[term];
      if(ok)el.removeAttribute('aria-invalid');else{el.setAttribute('aria-invalid','true');invalid??=el;}
    }
    if(invalid){
      if(!automatic)invalid.focus({preventScroll:true});
      out('gainNote',invalid.getAttribute('aria-label')+' must be between 0 and '+invalid.max+'.');return false;
    }
    if(setSimulatorGains(sim,next)){
      state.simEdits={};updateComparison();
      if(replay&&playTick!==null)playExercise();
      out('gainNote','Practice gains applied. Both traces use the same five-second exercise.');
      return true;
    }
  }
  function paintComparison(){
    if(!comparison)return;
    const [before,after]=comparison;
    const points=(run,key)=>run.samples.map(s=>[s.t,s[key]]);
    drawPlot(comparisonPlot,[
      {points:points(before,'measured'),color:plotColors[1]},
      {points:points(after,'measured'),color:plotColors[0]},
      {points:points(after,'target'),color:plotColors[2],dash:[5,4]}
    ],{start:0,end:after.duration,unit:after.unit});
  }
  function updateComparison(){
    const gains=applied(),baseline=state.practiceBaseline;
    const settings={mode:sim.mode,axis,exercise:prefs.exercise,environment:sim.environment,settings:sim.settings};
    const key=JSON.stringify([baseline,gains,settings]);
    if(key!==comparisonKey){
      const before=practiceTrial({...settings,gains:baseline});
      matching=banks.every(name=>['p','i','d'].every(term=>gains[name][term]===baseline[name][term]));
      const after=matching?before:practiceTrial({...settings,gains});
      comparison=[before,after];comparisonKey=key;
    }
    const [before,after]=comparison;
    const isLoad=prefs.exercise==='load',modeTitle=sim.mode==='angle'?'Angle':'Rate / Acro';
    const rate=sim.mode==='acro'||axis==='yaw';
    out('modeGuide',sim.mode==='angle'?
      'Angle · Roll and pitch sticks set tilt. Release to level. The yaw stick sets turn rate.':
      'Rate / Acro · Sticks set rotation speed. Centering stops the rotation and leaves the new tilt.');
    gainPanel.dataset.mode=sim.mode;
    outerLabel.textContent=sim.mode==='angle'?'Active in Angle':'Bypassed in Rate / Acro';
    out('practiceMode',modeTitle+' · '+axisTitle(axis)+(rate?' rate':' angle'));
    out('lessonHint',exercises[prefs.exercise].hint);
    metricLabels[2].textContent=isLoad?'Peak movement':'Settling after release';
    metricLabels[3].textContent=axis==='yaw'?'Final heading change':'Final tilt';
    for(const [prefix,run] of [['before',before],['after',after]]){
      const unit=' '+run.unit;
      out(prefix+'0',num(run.rms,2)+unit);out(prefix+'1',num(run.tail,2)+unit);
      out(prefix+'2',isLoad?num(run.peak,2)+unit:run.settling===null?'Unsettled':num(run.settling,2)+' s');
      out(prefix+'3',num(run.finalAngle,2)+'°');
    }
    let feedback=matching?'The curves overlap. Change a gain to compare it with this baseline.':
      Math.abs(before.rms-after.rms)<.005?'Tracking RMS is unchanged for this axis and mode.':
      'Tracking RMS is '+num(Math.abs(before.rms-after.rms),2)+' '+after.unit+' '+(after.rms<before.rms?'lower':'higher')+' with this tune.';
    if(before.limit||after.limit)feedback+=' Stand travel limit reached.';
    out('compare',feedback);
    action('baseline').disabled=matching||dirty();
    action('restore').disabled=matching&&!dirty();
    paintComparison();
  }
  const plotResize=new ResizeObserver(paintComparison);
  plotResize.observe(comparisonPlot);
  signal.addEventListener('abort',()=>plotResize.disconnect(),{once:true});
  function track(){
    axis=prefs.axis;
    bank=(prefs.plotLoop==='auto'&&sim.mode==='angle'&&axis!=='yaw'?'angle':'rate')+axisTitle(axis);
    field('Practice axis').value=field('Test axis').value=axis;
    updateComparison();clearPlot();
  }
  function clearPlot(){
    samples=[];frozen=null;graphFrozen=false;lastSample=-Infinity;graphEnd=sim.time;
    action('freeze').textContent='Freeze graph';
    const spec=traceSpec(chart,axis,bank.startsWith('angle')?'angle':'acro');
    root.querySelector('[data-tp-legend]').replaceChildren(...spec.labels.map((label,i)=>{
      const el=document.createElement('span');el.textContent=label;el.style.setProperty('--ink',plotColors[i]);return el;
    }));
    drawResponse();
  }
  function mode(value){
    if(value && sim.mode!==value && setFlightMode(sim,value))track();
  }
  function stop(message){
    playTick=null;input.stop();controls.release();audio.stop();out('status',message);
    drawControls();
  }
  function start(){
    if(!input.local && prefs.mode==='follow' && !input.receiver(kit,performance.now())?.mode){out('status','Waiting for receiver flight mode');return false;}
    const reason=input.start(kit,performance.now());
    out('status',reason||'Running');
    if(!reason && prefs.sound)audio.start();
    drawControls();return !reason;
  }
  function playExercise(){
    if(!input.local || (dirty()&&!applyEdits(false,false)))return;
    stop('Ready');resetSimulator(sim);
    if(!start())return;
    playTick=0;chart='response';prefs.plotLoop='auto';
    field('Plot').value=chart;field('Plot loop').value='auto';track();
    out('status','Playing · '+exercises[prefs.exercise].label+' · '+axisTitle(axis));
    root.querySelector('.tp-toolbar').scrollIntoView({block:'start'});
    drawControls();
  }
  function playStep(stand){
    practiceStep(stand,axis,prefs.exercise,playTick++);
    record();
    if(playTick===practiceTicks)stop('Exercise complete · graph retained');
  }
  function record(){
    if(!sim.running || sim.time-lastSample<.05)return;
    lastSample=sim.time;const title=axisTitle(axis),m=sim.memory[bank];
    const sample={t:sim.time,rate:sim[axis+'Rate'],angle:sim[axis],targetRate:sim['target'+title+'Rate'],
      targetAngle:sim['target'+title],p:m.p,i:m.i,d:m.d,travel:sim.vertical.z*100};
    for(let j=0;j<4;j++){sample['motors'+j]=1000+10*sim.motorCommands[j];sample['rpm'+j]=sim.motorRPM[j];}
    samples.push(sample);
    while(samples.length && samples[0].t<sim.time-10)samples.shift();
  }
  function drawResponse(){
    const data=graphFrozen?frozen:samples,end=graphFrozen?graphEnd:sim.time;
    const spec=traceSpec(chart,axis,bank.startsWith('angle')?'angle':'acro');
    drawPlot(plot,spec.fields.map(key=>({points:data.map(r=>[r.t-end,r[key]])})),{
      start:-10,end:0,unit:spec.unit??(bank.startsWith('rate')?'µs':'°/s')
    });
    const rate=bank.startsWith('rate'),errorKey=rate?'targetRate':'targetAngle',actual=rate?'rate':'angle';
    const rms=data.length?Math.sqrt(data.reduce((a,r)=>a+(r[errorKey]-r[actual])**2,0)/data.length):null;
    const peak=data.length?Math.max(...data.map(r=>Math.abs(r.rate))):null;
    out('error','RMS error '+num(rms)+(rate?' °/s':' °'));
    out('peak','Peak rate '+num(peak)+' °/s');
    const key=axisTitle(axis),unit=rate?' °/s':'°';
    const last=data.at(-1);
    const target=graphFrozen?last?.[errorKey]:sim['target'+key+(rate?'Rate':'')];
    const measured=graphFrozen?last?.[actual]:sim[axis+(rate?'Rate':'')];
    out('command','Target '+num(target)+unit);out('measured','Measured '+num(measured)+unit);
  }
  function drawControls(){
    const local=input.local,remote=input.receiver(kit,performance.now());
    const show=local||!!remote,knownMode=local||prefs.mode!=='follow'||!!remote?.mode;
    field('Flight mode').options[2].disabled=local;
    action('run').disabled=sim.running||(!local&&(!remote||!knownMode||remote.channels[2]>1025));
    action('run').textContent=local&&!sim.running?'Run at '+input.virtualStartPulse()+' µs':'Run simulator';
    action('stop').disabled=!sim.running;action('play').disabled=!local;
    action('load').hidden=!kit?.gains;
    action('load').disabled=!kit?.gains;
    field('Throttle').disabled=!local||playTick!==null;field('Throttle').value=Math.round(sim.throttle);
    kitInputLink.hidden=local||!!remote;
    const name=inputNames[input.source];
    out('receiver',local?'':remote?remote.source+' channels · simulation only':'Waiting for '+name);
    const modeLabel=sim.mode==='angle'?'Angle':'Rate / Acro';
    const follow=prefs.mode==='follow'?' · receiver switch':'';
    let hint=modeLabel+follow;
    if(!local && !remote)hint=kit?.input?'Kit input is '+kit.input.source+' · waiting for '+name:'Waiting for '+name;
    else if(!knownMode)hint='Waiting for receiver flight mode';
    else if(!local&&!sim.running&&remote.channels[2]>1025)hint+=' · lower throttle to start';
    else if(sim.running&&sim.throttle<sim.settings.throttleLow)hint+=' · throttle below '+sim.settings.throttleLow+' µs';
    else if(sim.running&&(Math.abs(sim.roll)>=44.9||Math.abs(sim.pitch)>=44.9))hint+=' · stand limit ±45°';
    out('keys',playTick!==null?'Playing the selected exercise':local?'Arrow keys · roll / pitch   ·   A / D · yaw   ·   W / S · throttle':hint);
    out('loopState',(knownMode?modeLabel:'Waiting for mode')+' · '+(sim.mode==='angle'?'attitude + rate':'rate loop'));
    out('sourceMode',hint);
    const xy=[[sim.cmdYaw,(sim.throttle-1500)/500],[sim.cmdRoll,sim.cmdPitch]];
    pads.forEach((pad,i)=>{
      const knob=pad.firstElementChild;knob.hidden=!show;
      knob.style.left=(50+xy[i][0]*100*PAD_TRAVEL)+'%';knob.style.top=(50-xy[i][1]*100*PAD_TRAVEL)+'%';
      const enabled=local&&playTick===null;pad.setAttribute('aria-disabled',String(!enabled));pad.tabIndex=enabled?0:-1;
    });
    for(const [key,us] of [['throttle',sim.throttle],['yawCh',pulseForAxis(sim.cmdYaw)],['rollCh',pulseForAxis(sim.cmdRoll)],['pitchCh',pulseForAxis(sim.cmdPitch)]])
      out(key,show?Math.round(us)+' µs':'—');
  }
  root.addEventListener('click',e=>{
    const key=e.target.closest('[data-tp-action]')?.dataset.tpAction;
    switch(key){
      case 'run': start();break;
      case 'stop': stop('Stopped · graph retained');break;
      case 'play':playExercise();break;
      case 'reset': stop('Reset');resetSimulator(sim);clearPlot();break;
      case 'tilt': tilting=!tilting;action('tilt').setAttribute('aria-pressed',String(tilting));break;
      case 'level':if(playTick!==null)stop('Exercise stopped');calibrateLevel(sim);out('status','Current position is virtual level');break;
      case 'integrator':if(playTick!==null)stop('Exercise stopped');resetIntegrators(sim);out('status','Virtual integrators reset');break;
      case 'apply':applyEdits();break;
      case 'baseline':
        if(!dirty()){state.practiceBaseline=structuredClone(applied());updateComparison();out('gainNote','Current practice gains set as the baseline.');}break;
      case 'load':case 'restore':case 'defaults':{
        const values=key==='load'?kit?.gains:key==='restore'?state.practiceBaseline:DEFAULT_PID;
        if(!values||!setSimulatorGains(sim,values))break;
        clearTimeout(previewTimer);state.simEdits={};showGains();updateComparison();
        if(playTick!==null)playExercise();
        out('gainNote',key==='load'?'Kit gains loaded into the simulator.':key==='restore'?'Practice baseline restored.':'Factory gains applied to the simulator.');break;
      }
      case 'freeze':
        graphFrozen=!graphFrozen;frozen=graphFrozen?samples.slice():null;graphEnd=sim.time;
        action('freeze').textContent=graphFrozen?'Resume graph':'Freeze graph';drawResponse();break;
      case 'practice':gainPanel.querySelector('input').focus({preventScroll:true});gainPanel.closest('.tp-lab').scrollIntoView({block:'start'});break;
    }
  },{signal});
  root.addEventListener('change',e=>{
    const el=e.target;
    if(playTick!==null&&(el.dataset.env||['Flight mode','Practice axis','Test axis','Practice exercise'].includes(el.dataset.tp)))stop('Exercise changed · ready to replay');
    if(el.dataset.env)updateComparison();
    switch(el.dataset.tp){
      case 'Simulator input':
        stop('Input selected');
        input.source=prefs.source=el.value;
        prefs.mode=input.local?sim.mode:'follow';
        field('Flight mode').value=prefs.mode;
        sim.settings=!input.local&&kit?controlSettings(kit.flight,kit.arming,kit.setup):controlSettings();
        mirror(performance.now());updateComparison();drawControls();break;
      case 'Flight mode':
        prefs.mode=el.value;mode(el.value==='follow'?input.receiver(kit,performance.now())?.mode:el.value);
        drawControls();break;
      case 'Test axis':case 'Practice axis':prefs.axis=el.value;track();break;
      case 'Plot loop':prefs.plotLoop=el.value;track();break;
      case 'Plot':chart=el.value;clearPlot();break;
      case 'Live preview':
        prefs.livePreview=el.checked;clearTimeout(previewTimer);if(el.checked&&dirty())applyEdits(true);break;
      case 'Practice exercise':prefs.exercise=el.value;updateComparison();break;
      case 'Motor sound profile':prefs.profile=el.value;audio.setProfile(el.value);break;
      case 'Airflow':prefs.airflow=el.value;break;
      case 'Sound':
        prefs.sound=el.checked;
        if(prefs.sound&&sim.running)audio.start();else audio.stop();
        break;
    }
  },{signal});
  root.addEventListener('input',e=>{
    const el=e.target;
    if(el.dataset.gain){
      (state.simEdits??={})[el.dataset.gain]=el.value;
      action('baseline').disabled=true;action('restore').disabled=false;
      out('gainNote',prefs.livePreview?'Previewing draft gains…':'Draft gains · choose Apply & compare to test them.');
      clearTimeout(previewTimer);
      if(prefs.livePreview)previewTimer=setTimeout(()=>applyEdits(true),350);
    }
    if(el.dataset.tp==='Throttle' && input.local){sim.throttle=clamp(el.valueAsNumber,1000,2000);drawControls();}
    if(el.dataset.tp==='Volume'){
      prefs.volume=el.valueAsNumber;audio.setVolume(prefs.volume/100);out('volume',prefs.volume+'%');
      if(prefs.sound&&sim.running&&!audio.running)audio.start();
    }
    if(el.dataset.env){
      if(playTick!==null)stop('Conditions changed · ready to replay');
      sim.environment[el.dataset.env]=el.valueAsNumber;
      out(el.dataset.env,el.value+' '+el.dataset.unit);
    }
  },{signal});
  for(const el of root.querySelectorAll('[data-env]')){
    el.value=sim.environment[el.dataset.env];out(el.dataset.env,el.value+' '+el.dataset.unit);
  }
  function mirror(now){
    if(input.local)return;
    const remote=input.receiver(kit,now);
    const reason=input.sample(kit,now);
    if(reason){stop(reason);return;}
    if(prefs.mode==='follow'){
      if(remote?.mode)mode(remote.mode);
      else if(sim.running)stop('Receiver flight mode lost');
    }
  }
  field('Flight mode').value=prefs.mode;field('Simulator input').value=input.source;
  field('Live preview').checked=prefs.livePreview;
  field('Practice exercise').value=prefs.exercise;
  field('Test axis').value=axis;field('Plot loop').value=prefs.plotLoop;
  field('Sound').checked=prefs.sound;field('Motor sound profile').value=prefs.profile;
  field('Volume').value=prefs.volume;out('volume',prefs.volume+'%');field('Airflow').value=prefs.airflow;
  audio.setVolume(prefs.volume/100);audio.setProfile(prefs.profile);
  showGains();track();drawControls();
  if(dirty())out('gainNote','Draft gains · choose Apply & compare to test them.');
  return {
    get mirroring(){return !input.local;},
    receive(value){
      kit=value;
      if(!input.local){
        if(kit){
          const next=controlSettings(kit.flight,kit.arming,kit.setup);
          if(['angleScale','rateScale','yawScale','throttleLow'].some(k=>next[k]!==sim.settings[k])||next.idles.some((v,i)=>v!==sim.settings.idles[i])){
            sim.settings=next;updateComparison();
          }
        }
        mirror(performance.now());
      }
    },
    tilt(r,p){if(tilting&&playTick===null){disturb(sim,r,p);return true;}return false;},
    advance(now,dt){
      mirror(now);
      controls.update(dt);
      if(sim.running){
        advanceSimulator(sim,dt,playTick===null?undefined:playStep);
        record();if(prefs.sound&&sim.running)audio.update(sim.motors,sim.motorRPM);
      }
    },
    paint(){
      drawControls();drawResponse();
      for(const [i,k] of axes.entries())out('att'+i,num(sim[k])+'°');
      sim.motorCommands.forEach((value,i)=>ui.motor(i,value,num(1000+10*value,0)+' µs',num(sim.motorRPM[i],0)+' RPM'));
      [num(sim.vertical.thrust,2)+' N',num(sim.vertical.weight,2)+' N',num(sim.vertical.z*100,1)+' cm',
        num(sim.metrics.motorSpread,1)+'%'].forEach((v,i)=>out('load'+i,v));
    },
    stop(){if(sim.running)stop('Stopped · bench paused');else controls.release();},
    dispose(){clearTimeout(previewTimer);this.stop();audio.dispose();}
  };
}
