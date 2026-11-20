import assert from 'node:assert/strict';
import test from 'node:test';
import * as THREE from '../web/assembly/three.module.min.js';
import {register as catalog} from '../web/assembly/js/catalog.js';
import {register as project} from '../web/assembly/js/project-state.js';
import {register as guide} from '../web/assembly/js/shared-ui.js';
import {register as preview,wiresForStep} from '../web/assembly/js/wiring-preview.js';

function workbench(t, reducedMotion=false) {
  const ctx = {THREE,config:{historyLimit:3},fcHeaderForMotor:i => i};
  catalog(ctx); project(ctx); guide(ctx);
  const nodes=new Map(), queued=new Map();
  let frame=0;
  ctx.$=selector=>{
    if(!nodes.has(selector)) nodes.set(selector,{
      classList:{remove(){},toggle(){}},
      setAttribute(name,value){this[name]=value;}
    });
    return nodes.get(selector);
  };
  // Use an actual Three scene and geometry, independent of GPU availability.
  ctx.scene = new THREE.Scene();
  ctx.routePoints = () => [new THREE.Vector3(), new THREE.Vector3(1,.1,1), new THREE.Vector3(2,0,2)];
  ctx.wColor = () => 0xffac00;
  const globals = {
    window:{matchMedia:()=>({matches:reducedMotion})},
    requestAnimationFrame:fn=>{queued.set(++frame,fn);return frame;},
    cancelAnimationFrame:id=>queued.delete(id)
  };
  for(const [key,value] of Object.entries(globals)){
    const previous=Object.getOwnPropertyDescriptor(globalThis,key);
    Object.defineProperty(globalThis,key,{value,configurable:true});
    t.after(()=>{if(previous)Object.defineProperty(globalThis,key,previous);else delete globalThis[key];});
  }
  preview(ctx);
  const step=id=>{
    ctx.state.step=ctx.steps.findIndex(s=>s.id===id);
    ctx.syncWiringPreview(ctx.steps[ctx.state.step]);
  };
  return {ctx,queued,step,button:ctx.$('#assemblyWiringPreviewBtn'),box:ctx.$('#assemblyWiringPreviewBox')};
}

test('bench preview shows only the current wiring group and does not commit the demonstration', t=>{
  const {ctx,step,button,box,queued}=workbench(t);
  ctx.state.parts=[1,2,3,4].flatMap(i=>[{type:'esc',slotId:'ESC'+i},{type:'motor',slotId:'M'+i}]);
  step('motors');assert.equal(box.hidden,true);
  ctx.previewWiringAction(ctx.steps.find(s=>s.id==='motorWire'));
  assert.equal(ctx.scene.children.length,0);
  step('motorWire');assert.equal(box.hidden,false);assert.equal(button.disabled,false);
  const before=ctx.snapState();
  button.onclick();
  const group=ctx.scene.getObjectByName('Wiring preview');
  assert.equal(group.children.length,13); // twelve phase wires and one moving marker
  assert.equal(group.children.filter(c=>c.visible).length,2);
  assert.equal(ctx.$('#assemblyWiringPreviewLabel').textContent,'ESC1.U → M1.U');
  assert.equal(ctx.snapState(),before);
  assert.equal(ctx.history.undo.length,0);
  const staleCallback=[...queued.values()][0];
  // A completed edit elsewhere in the bench advances the guide while playback is active.
  ctx.stepDone=i=>ctx.steps[i].id==='motorWire';
  ctx.renderAssemblyUI=()=>ctx.syncWiringPreview(ctx.steps[ctx.state.step]);
  ctx.notify=ctx.showGuides=()=>{};
  ctx.advanceGuidedStepIfReady('wiring');
  assert.equal(ctx.steps[ctx.state.step].id,'powerWire');
  assert.equal(button.disabled,true); // PDB still missing
  assert.equal(ctx.scene.children.length,0);assert.equal(queued.size,0);
  staleCallback(performance.now()+500);
  assert.equal(queued.size,0);
  assert.equal(ctx.state.connections.length,0);
  assert.deepEqual(['motorWire','powerWire','escFc','xt60'].map(id=>wiresForStep(ctx,id).length),[12,8,12,2]);
});

test('reduced-motion previews are static and undo clears even a same-step preview', t=>{
  const {ctx,step,button,queued}=workbench(t,true);
  ctx.state.parts=[{type:'battery',slotId:'BAT'},{type:'bottomPlate',slotId:'bottom'}];
  step('xt60');ctx.historyPush();
  button.onclick();
  assert.equal(ctx.scene.getObjectByName('Wiring preview').children.filter(c=>c.visible).length,2);
  assert.equal(queued.size,0);assert.equal(ctx.state.powered,false);
  ctx.install=(type,slot)=>ctx.state.parts.push({type,slotId:slot.id});
  ctx.setPowerVisual=ctx.rebuildSolder=ctx.rebuild3DWires=ctx.render2D=ctx.showGuides=ctx.notify=()=>{};
  ctx.phaseMap=()=>null;ctx.pairPresent=()=>false;
  ctx.renderAssemblyUI=()=>ctx.syncWiringPreview(ctx.steps[ctx.state.step]);
  ctx.undoAction();
  assert.equal(ctx.steps[ctx.state.step].id,'xt60');assert.equal(ctx.scene.children.length,0);
  assert.equal(button['aria-pressed'],'false');assert.equal(ctx.state.connections.length,0);
  button.onclick();assert.equal(ctx.scene.children.length,1);
  button.onclick();assert.equal(ctx.scene.children.length,0);
});
