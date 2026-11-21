import {createSimulator} from './tripod-physics.js';
import {tripodMarkup} from './markup.js';
import {createScene} from './scene.js';
import {mountSimulator} from './simulator.js';
export function createBenchState() {
  return {sim:createSimulator()};
}

export function mountTripod(slot,state) {
  const controller=new AbortController(),{signal}=controller;
  slot.innerHTML=tripodMarkup();
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
  const bench=mountSimulator(ui,state);
  let raf=0,last=0,lastPaint=-Infinity,disposed=false,modelStatus='';
  let scene;
  try {scene=createScene(root.querySelector('[data-tp-stage]'),s=>{modelStatus=s;},(r,p)=>bench.tilt?.(r,p),signal,()=>{fields.get('Camera view').value='orbit';});}
  catch {modelStatus='3D canvas unavailable';}
  fields.get('Camera view').querySelector('[value=orbit]').disabled=true;
  fields.get('Camera view').addEventListener('change',e=>scene?.view(e.target.value),{signal});
  if(fields.has('Airflow')){
    const airflow=fields.get('Airflow');scene?.wash(airflow.value);
    airflow.addEventListener('change',()=>scene?.wash(airflow.value),{signal});
  }
  function frame(now){
    raf=0;
    if(disposed||document.hidden||!root.isConnected||root.closest('[hidden]'))return;
    const dt=last?Math.max(0,Math.min(.25,(now-last)/1000)):0;last=now;
    bench.advance?.(now,dt);
    scene?.draw(state.sim,state.sim,dt);
    if(now-lastPaint>95){
      lastPaint=now;bench.paint?.();
      out('model',modelStatus);
    }
    raf=requestAnimationFrame(frame);
  }
  function schedule(){if(!raf&&!disposed&&!document.hidden)raf=requestAnimationFrame(frame);}
  schedule();
  return {
    get mirroring(){return !!bench.mirroring;},
    receive(snapshot){bench.receive(snapshot);},
    update(snapshot){bench.receive(snapshot);schedule();},
    suspend(){bench.stop();cancelAnimationFrame(raf);raf=0;last=0;},
    dispose(){disposed=true;cancelAnimationFrame(raf);bench.dispose();controller.abort();scene?.dispose();}
  };
}
