import {banks, terms, limits, validGains} from './gains.js';
import {advanceSimulator, calibrateLevel, clamp, controlSettings, DEFAULT_PID, disturb, resetIntegrators, resetSimulator,
  setFlightMode, setPID, startTuningPulse} from './tripod-physics.js';
import {bindSticks, SimulatorInput} from './inputs.js';
import {createTripodAudio} from './tripod-audio.js';
import {simulateResponse} from './tripod-experiments.js';
import {drawPlot,plotColors} from './plot.js';

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
  const input=new SimulatorInput(sim);
  sim.settings=controlSettings();
  let kit=null,bank='rateRoll',axis='roll',chart='response',graphFrozen=false,tilting=false,sound=false;
  let samples=[],frozen=null,lastSample=-Infinity,graphEnd=sim.time;
  const audio=createTripodAudio(msg=>{if(msg.includes('UNAVAILABLE')||msg.includes('FAILED'))out('status',msg);});
  const gainFields=Object.fromEntries([...root.querySelectorAll('[data-gain]')].map(el=>[el.dataset.gain,el]));
  const pads=root.querySelectorAll('[data-pad]'), plot=root.querySelector('[data-tp-plot=sim]');
  const comparisonPlot=root.querySelector('[data-tp-plot=compare]');
  const applied=()=>({...sim.pid,...sim.pendingPID});
  const controls=bindSticks(root,sim,()=>input.source==='local',signal,()=>sim.running?stop('Stopped'):start());
  function gainEditor(){
    for(const term of terms)gainFields[term].value=applied()[bank][term];
    const term=field('Comparison term').value,base=applied()[bank][term];
    const step={p:.5,i:1,d:.01}[term];
    field('A').max=field('B').max=limits[term];
    field('A').value=Number(Math.max(0,base*.65).toFixed(4));
    field('B').value=Number(Math.min(limits[term],Math.max(step,base*1.35)).toFixed(4));
  }
  function selectBank(value){
    bank=value;axis=bank.replace(/^(angle|rate)/,'').toLowerCase();state.lastAxis=axisTitle(axis);state.lastBank=bank;
    field('Test axis').value=axis;field('PID bank').value=bank;
    gainEditor();clearPlot();
  }
  function clearPlot(){
    samples=[];frozen=null;graphFrozen=false;lastSample=-Infinity;graphEnd=sim.time;
    action('freeze').textContent='Freeze graph';
    const spec=traceSpec(chart,axis,sim.mode);
    root.querySelector('[data-tp-legend]').replaceChildren(...spec.labels.map((label,i)=>{
      const el=document.createElement('span');el.textContent=label;el.style.setProperty('--ink',plotColors[i]);return el;
    }));
    drawResponse();
  }
  function mode(value){
    if(sim.mode!==value){setFlightMode(sim,value);field('Flight mode').value=value;clearPlot();}
  }
  function stop(message){
    input.stop();controls.release();audio.stop();out('status',message);
    drawControls();
  }
  function start(){
    const reason=input.start(kit,performance.now());
    out('status',reason||'Running');
    if(!reason && sound)audio.start();
    drawControls();return !reason;
  }
  function pulse(){
    if(input.source!=='local')return;
    if(!sim.running && !start())return;
    sim.throttle=1500;
    if(startTuningPulse(sim,axis,14)) {
      chart='response';field('Plot').value=chart;clearPlot();
      out('status',axisTitle(axis)+' step · 1500 µs virtual throttle');
    }
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
    const spec=traceSpec(chart,axis,sim.mode);
    drawPlot(plot,spec.fields.map(key=>({points:data.map(r=>[r.t-end,r[key]])})),{
      start:-10,end:0,unit:spec.unit??(bank.startsWith('rate')?'µs':'°/s')
    });
    const rate=axis==='yaw'||sim.mode==='acro',errorKey=rate?'targetRate':'targetAngle',actual=rate?'rate':'angle';
    const rms=data.length?Math.sqrt(data.reduce((a,r)=>a+(r[errorKey]-r[actual])**2,0)/data.length):null;
    const peak=data.length?Math.max(...data.map(r=>Math.abs(r.rate))):null;
    out('error','RMS error '+num(rms)+(rate?' °/s':' °'));
    out('peak','Peak rate '+num(peak)+' °/s');
  }
  function compare(){
    const term=field('Comparison term').value,values=['A','B'].map(k=>field(k).valueAsNumber);
    if(!values.every(v=>Number.isFinite(v)&&v>=0&&v<=limits[term])){out('compare','Enter A and B between 0 and '+limits[term]+'.');return;}
    const result=simulateResponse({basePID:applied(),bank,gain:term,values,axis,settings:sim.settings,environment:{...sim.environment}});
    const unit=result.mode==='angle'&&axis!=='yaw'?'°':'°/s';
    const [a,b]=result.results;
    drawPlot(comparisonPlot,[a,b].map(r=>({points:r.samples.map(s=>[s.t,s.actual])})),{start:0,end:6.5,unit});
    out('compare',axisTitle(axis)+' '+term.toUpperCase()+' · A (mint) RMS '+num(a.metrics.rms)+unit+' · B (amber) RMS '+num(b.metrics.rms)+unit+' · '+(result.scenario==='bias'?'constant bias':'target step'));
  }
  function drawControls(){
    const local=input.source==='local',remote=kit?.input && kit.input.until>performance.now()?kit.input:null;
    field('Simulator input').disabled=sim.running;field('Flight mode').disabled=!local;
    action('run').disabled=sim.running || (!local && !remote);
    action('stop').disabled=!sim.running; action('pulse').disabled=!local;
    action('load').disabled=!kit?.gains;
    field('Throttle').disabled=!local;field('Throttle').value=Math.round(sim.throttle);
    out('receiver',local?'Keyboard / sticks':remote?remote.source+' receiver':'Waiting for receiver');
    out('throttle',Math.round(sim.throttle)+' µs');
    const xy=[[sim.cmdYaw,(sim.throttle-1500)/500],[sim.cmdRoll,sim.cmdPitch]];
    pads.forEach((pad,i)=>{const n=pad.firstElementChild;n.style.left=(50+xy[i][0]*39)+'%';n.style.top=(50-xy[i][1]*39)+'%';});
  }
  root.addEventListener('click',e=>{
    const key=e.target.closest('[data-tp-action]')?.dataset.tpAction;
    switch(key){
      case 'run': start();break;
      case 'stop': stop('Stopped · graph retained');break;
      case 'pulse': pulse();break;
      case 'reset': stop('Reset');resetSimulator(sim);clearPlot();break;
      case 'tilt': tilting=!tilting;action('tilt').setAttribute('aria-pressed',String(tilting));break;
      case 'level':calibrateLevel(sim);out('status','Current position is virtual level');break;
      case 'integrator':resetIntegrators(sim);out('status','Virtual integrators reset');break;
      case 'apply':{
        const next=Object.fromEntries(terms.map(k=>[k,gainFields[k].valueAsNumber]));
        if(!validGains(next)){out('gainNote','Enter valid P (0–100), I (0–500) and D (0–20).');break;}
        setPID(sim,bank,next);state.lastAxis=axisTitle(axis);out('gainNote',bank.replace(/([A-Z])/,' $1')+' applied to simulator');break;
      }
      case 'load':case 'defaults':{
        const values=key==='load'?kit?.gains:DEFAULT_PID;
        if(!values)break;
        for(const name of banks)setPID(sim,name,values[name]);
        gainEditor();out('gainNote',key==='load'?'Copied active kit gains into the simulator.':'Simulator defaults restored.');break;
      }
      case 'freeze':
        graphFrozen=!graphFrozen;frozen=graphFrozen?samples.slice():null;graphEnd=sim.time;
        action('freeze').textContent=graphFrozen?'Resume graph':'Freeze graph';drawResponse();break;
      case 'compare':compare();break;
    }
  },{signal});
  root.addEventListener('change',e=>{
    const el=e.target;
    switch(el.dataset.tp){
      case 'Simulator input':
        stop('Input selected');input.source=el.value;
        sim.settings=el.value==='receiver'&&kit?controlSettings(kit.flight,kit.arming,kit.setup):controlSettings();
        break;
      case 'Flight mode':mode(el.value);break;
      case 'Test axis':selectBank((sim.mode==='angle'&&el.value!=='yaw'?'angle':'rate')+axisTitle(el.value));break;
      case 'PID bank':selectBank(el.value);break;
      case 'Plot':chart=el.value;clearPlot();break;
      case 'Comparison term':gainEditor();break;
      case 'Sound':sound=el.checked;if(sound&&sim.running)audio.start();else audio.stop();break;
    }
  },{signal});
  root.addEventListener('input',e=>{
    const el=e.target;
    if(el.dataset.gain)out('gainNote','Edited · select Apply to simulator to test');
    if(el.dataset.tp==='Throttle' && input.source==='local')sim.throttle=clamp(el.valueAsNumber,1000,2000);
    if(el.dataset.env){
      sim.environment[el.dataset.env]=el.valueAsNumber;
      out(el.dataset.env,el.value+' '+el.dataset.unit);
    }
  },{signal});
  for(const el of root.querySelectorAll('[data-env]')){
    el.value=sim.environment[el.dataset.env];out(el.dataset.env,el.value+' '+el.dataset.unit);
  }
  field('Flight mode').value=sim.mode;selectBank(state.lastBank??bank);drawControls();
  return {
    get mirroring(){return input.source==='receiver';},
    receive(value){
      kit=value;
      if(input.source==='receiver'){
        if(kit)sim.settings=controlSettings(kit.flight,kit.arming,kit.setup);
        if(sim.running){const reason=input.sample(kit,performance.now());if(reason)stop(reason);}
      }
    },
    tilt(r,p){if(tilting)disturb(sim,r,p);return tilting;},
    advance(now,dt){
      if(input.source==='receiver' && kit?.mode && kit.input?.until>now)mode(kit.mode);
      const reason=input.sample(kit,now);if(reason)stop(reason);
      controls.update(dt);
      if(sim.running){advanceSimulator(sim,dt);record();if(sound)audio.update(sim.motors,sim.motorRPM);}
    },
    paint(){
      drawControls();drawResponse();
      for(const [i,k] of axes.entries())out('att'+i,num(sim[k])+'°');
      sim.motorCommands.forEach((value,i)=>ui.motor(i,value,num(1000+10*value,0)+' µs',num(sim.motorRPM[i],0)+' RPM'));
      [num(sim.vertical.thrust,2)+' N',num(sim.vertical.weight,2)+' N',num(sim.vertical.z*100,1)+' cm',
        num(sim.metrics.motorSpread,1)+'%'].forEach((v,i)=>out('load'+i,v));
    },
    stop(){if(sim.running)stop('Stopped · bench paused');else controls.release();},
    dispose(){this.stop();audio.dispose();}
  };
}
