import {createSimulator} from './tripod-physics.js';
import {tripodMarkup} from './markup.js';
import {createScene} from './scene.js';
import {mountSimulator} from './simulator.js';
import {TripodRecording} from './telemetry.js';
import {drawResponse} from '../pid-trace.js';
import {downloadCsv} from '../analysis-common.js';

export function createBenchState() {
  return {sim:createSimulator(),capture:new TripodRecording()};
}
const liveChart='<section class="tp-card"><div class="tp-card-head"><h3>FC tracking response</h3>'+
  '<select data-tp="Loop" aria-label="Measured loop"><option value="rate">Rate</option><option value="angle">Angle</option></select>'+
  '<select data-tp="Axis" aria-label="Measured axis"><option value="0">Roll</option><option value="1">Pitch</option><option value="2">Yaw</option></select></div>'+
  '<button type="button" class="cfg-btn" data-tp-action="trace-live" hidden>Show live trace</button><div class="tp-legend"><span style="--ink:#71dac4">Measured</span><span style="--ink:#ffb66b">Target</span><output data-tp-out="units"></output></div>'+
  '<canvas data-tp-plot="real" class="cfg-response" role="img" aria-label="Measured FC response and reported target"></canvas><p class="tp-note" data-tp-out="readings"></p></section>';

function mountLive(ui,state){
  const {root,field,action,out,signal}=ui,capture=state.capture;
  let kit=null,stream=null,reviewCapture=!!capture.rows.length;
  const chart=root.querySelector('[data-tp-plot=real]');
  function paint(){
    const linked=!!kit, sample=kit?.attitude;
    const angle=field('Loop').value==='angle',axis=Number(field('Axis').value);
    const unit=angle?'°':'°/s';
    out('link',linked?(kit.kit||'Areion FC A1')+' · '+kit.path:'Waiting for USB / AP');
    out('armed',kit?.armed===true?'Armed':kit?.armed===false?'Disarmed':'—');
    [kit?.mode==='angle'?'Angle':kit?.mode==='acro'?'Rate / Acro':'—',kit?.input?.source??'—',
      ...[0,1,2].map(i=>value(kit?.rates?.[i],' °/s'))].forEach((x,i)=>out('live'+i,x));
    [sample?.roll,sample?.pitch,sample?.yaw].forEach((v,i)=>out('att'+i,value(v,'°')));
    for(let i=0;i<4;i++){
      const v=kit?.motors?.[i];ui.motor(i,Number.isFinite(v)?(v-1000)/10:0,value(v,' µs',0),['Front left','Front right','Rear right','Rear left'][i]);
    }
    const active=!!capture.session;
    action('record').disabled=active||!sample;action('finish').disabled=!active;
    action('export').disabled=active||!capture.rows.length;
    out('capture',active?'Recording · '+Math.max(0,(capture.end-stream.clock)/1000).toFixed(1)+' s left':
      capture.rows.length?capture.message+' · '+capture.rows.length+' packets':sample?'Ready to record':'Waiting for fresh IMU');
    out('units',unit+' · 10 s');
    const actual=angle?[sample?.roll,sample?.pitch][axis]:kit?.rates?.[axis];
    const target=kit?.targets?.[angle?'angle':'rate']?.[axis];
    const held=reviewCapture&&!active&&capture.rows.length>0;
    const switchTrace=action('trace-live');
    switchTrace.hidden=active||!capture.rows.length;
    switchTrace.textContent=held?'Show live trace':'Review captured trace';
    const rows=held||active?capture.rows:kit&&stream?stream.rows:[];
    const clock=held?rows.at(-1).at:stream?.clock??performance.now();
    drawResponse(chart,{clock,rows},axis,angle);
    out('readings',held?'Recorded trace · '+capture.rows.length+' packets':
      'Measured '+value(actual,unit)+' · Target '+value(target,unit));
  }
  function value(n,unit,digits=1){return Number.isFinite(n)?n.toFixed(digits)+unit:'—';}
  root.addEventListener('change',e=>{
    if(e.target===field('Loop')){
      const last=field('Axis').options[2];last.disabled=field('Loop').value==='angle';
      if(last.disabled&&field('Axis').value==='2')field('Axis').value='0';
    }
    paint();
  },{signal});
  root.addEventListener('click',e=>{
    switch(e.target.closest('[data-tp-action]')?.dataset.tpAction){
      case 'record':if(capture.start(stream,kit))reviewCapture=true;break;
      case 'trace-live':reviewCapture=!reviewCapture;break;
      case 'finish':capture.stop();break;
      case 'export':if(capture.rows.length)downloadCsv({rows:capture.rows},'areion-tripod-run.csv');break;
      default:return;
    }
    paint();
  },{signal});
  return {receive(next,data){kit=next;stream=data;capture.update(stream.clock,kit);paint();},
    dispose(){capture.stop('Capture paused');},stop(){capture.stop('Capture paused');}};
}

export function mountTripod(slot,kind,state) {
  const live=kind==='live',controller=new AbortController(),{signal}=controller;
  slot.innerHTML=tripodMarkup(live,liveChart);
  const root=slot.firstElementChild;
  const outputs=new Map([...root.querySelectorAll('[data-tp-out]')].map(el=>[el.dataset.tpOut,el]));
  const fields=new Map([...root.querySelectorAll('[data-tp]')].map(el=>[el.dataset.tp,el]));
  const actions=new Map([...root.querySelectorAll('[data-tp-action]')].map(el=>[el.dataset.tpAction,el]));
  const bars=[...root.querySelectorAll('[data-tp-bar]')];
  function out(key,value){const el=outputs.get(key);if(el&&el.textContent!==value)el.textContent=value;}
  function motor(i,percent,label,detail){
    bars[i].style.width=Math.min(100,Math.max(0,percent))+'%';out('motor'+i,label);out('motorDetail'+i,detail);
  }
  const ui={root,field:k=>fields.get(k),action:k=>actions.get(k),out,motor,signal};
  const bench=live?mountLive(ui,state):mountSimulator(ui,state);
  let raf=0,last=0,lastPaint=-Infinity,disposed=false,kit=null,modelStatus='';
  let scene;
  try {scene=createScene(root.querySelector('[data-tp-stage]'),s=>{modelStatus=s;},(r,p)=>bench.tilt?.(r,p),signal);}
  catch {modelStatus='3D canvas unavailable';}
  fields.get('Camera view').addEventListener('change',e=>scene?.view(e.target.value),{signal});
  fields.get('Airflow')?.addEventListener('change',e=>scene?.wash(e.target.checked),{signal});
  function frame(now){
    raf=0;
    if(disposed||document.hidden||!root.isConnected||root.closest('[hidden]'))return;
    const dt=last?Math.max(0,Math.min(.25,(now-last)/1000)):0;last=now;
    bench.advance?.(now,dt);
    scene?.draw(live?kit?.attitude:state.sim,live?null:state.sim,dt);
    if(now-lastPaint>95){
      lastPaint=now;bench.paint?.();
      out('model',live&&!kit?.attitude?'Waiting for live IMU':modelStatus);
    }
    raf=requestAnimationFrame(frame);
  }
  function schedule(){if(!raf&&!disposed&&!document.hidden)raf=requestAnimationFrame(frame);}
  schedule();
  return {
    get mirroring(){return !!bench.mirroring;},
    receive(snapshot){kit=snapshot;bench.receive(snapshot);},
    update(snapshot,stream){kit=snapshot;bench.receive(snapshot,stream);schedule();},
    suspend(){bench.stop();cancelAnimationFrame(raf);raf=0;last=0;},
    dispose(){disposed=true;cancelAnimationFrame(raf);bench.dispose();controller.abort();scene?.dispose();}
  };
}
