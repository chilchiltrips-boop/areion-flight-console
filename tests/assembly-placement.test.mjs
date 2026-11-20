import assert from 'node:assert/strict';
import test from 'node:test';
import * as THREE from '../web/assembly/three.module.min.js';
import {register as catalog} from '../web/assembly/js/catalog.js';
import {register as scene} from '../web/assembly/js/assembly-scene.js';
import {register as guide} from '../web/assembly/js/shared-ui.js';

const rect = {left:80, top:120, width:900, height:480};

function bench(type, guided = true) {
  const ctx = {THREE};
  catalog(ctx);
  scene(ctx);
  guide(ctx);
  const message = {textContent:''};
  const camera = new THREE.PerspectiveCamera(38, rect.width / rect.height, .1, 1000);
  camera.position.set(8.7,7.6,11.5);
  camera.lookAt(0,.58,0);
  Object.assign(ctx, {
    state:{guided, selectedType:type, step:ctx.steps.findIndex(step => step.types.includes(type)), parts:[]},
    camera, renderer:{domElement:{getBoundingClientRect:() => rect}},
    snapPreview:{position:new THREE.Vector3(), material:{color:new THREE.Color()}},
    $:() => message, notify:text => { message.textContent = text; },
    install:(part, slot) => ctx.state.parts.push({type:part, slotId:slot.id}),
    historyPush(){}, renderAssemblyUI(){}, showGuides(){}, advanceGuidedStepIfReady(){}
  });
  return {ctx, message};
}

function pointer(clientX, clientY) {
  return {clientX, clientY, pointerId:1, button:0, isPrimary:true};
}

function aim(ctx, slot) {
  ctx.camera.updateMatrixWorld();
  const p = new THREE.Vector3(...slot.p).project(ctx.camera);
  return pointer(rect.left + (1 + p.x) * rect.width / 2, rect.top + (1 - p.y) * rect.height / 2);
}

test('guided taps snap even when the pointer lands far from the centre mount, while orbit drags never place', () => {
  const {ctx, message} = bench('bottomPlate');
  const corner = pointer(rect.left + 8, rect.top + 8);
  ctx.down(corner);
  ctx.move(pointer(corner.clientX + 40, corner.clientY));
  ctx.up(corner);
  assert.equal(ctx.state.parts.length, 0, 'an orbit returning to the same pixel still counts as a drag');
  assert.equal(message.textContent, 'Snap to bottom');
  ctx.down(corner);
  assert.equal(ctx.state.parts.length, 0);
  ctx.up(corner);
  assert.deepEqual(ctx.state.parts, [{type:'bottomPlate', slotId:'bottom'}]);
  assert.equal(ctx.state.selectedType, null);
});

test('the guided drop picks the nearest compatible unoccupied mount and ignores ineligible parts', () => {
  const {ctx} = bench('motor');
  const m3 = ctx.slots.motor.find(slot => slot.id === 'M3');
  const cursor = aim(ctx, m3);
  ctx.previewPlacement(cursor);
  assert.deepEqual(ctx.snapPreview.position.toArray(), [m3.p[0],m3.p[1] + .05,m3.p[2]]);
  ctx.placeSelected(cursor);
  assert.equal(ctx.state.parts[0].slotId, 'M3');
  for (let i = 0; i < 4; i++) {
    ctx.state.selectedType = 'motor';
    ctx.placeSelected(cursor);
  }
  assert.deepEqual(ctx.state.parts.map(p => p.slotId).sort(), ['M1','M2','M3','M4']);
  for (const type of ['armWhite','receiver','batteryStrap']) {
    ctx.state.selectedType = type;
    ctx.placeSelected(cursor);
  }
  assert.equal(ctx.state.parts.length, 4);
});

test('free build preserves its pointer radius and button placement uses the next open slot', () => {
  const {ctx, message} = bench('armRed', false);
  ctx.placeSelected(pointer(rect.left + 4, rect.top + 4));
  assert.equal(ctx.state.parts.length, 0);
  assert.match(message.textContent, /Move closer/);
  ctx.placeSelected(aim(ctx, ctx.slots.armRed[1]));
  assert.equal(ctx.state.parts[0].slotId, ctx.slots.armRed[1].id);
  ctx.state.selectedType = 'armRed';
  ctx.placeSelected();
  assert.equal(ctx.state.parts[1].slotId, ctx.slots.armRed[0].id);
});

test('ordinary page scrolling leaves the orbit distance unchanged and deliberate zoom stays available', () => {
  const ctx = {THREE};
  catalog(ctx);
  const canvas = Object.assign(new EventTarget(), {style:{}, setAttribute(){}});
  const camera = new THREE.PerspectiveCamera();
  camera.position.set(8.7,7.6,11.5);
  const controls = new ctx.MiniOrbitControls(camera,canvas);
  const radius = () => camera.position.distanceTo(controls.target);
  const start = radius();
  const wheel = modifiers => {
    const event = Object.assign(new Event('wheel',{cancelable:true}), {deltaY:150,...modifiers});
    canvas.dispatchEvent(event);
    controls.update();
    return event.defaultPrevented;
  };
  assert.equal(wheel({}), false);
  assert.ok(Math.abs(radius()-start) < 1e-6);
  assert.equal(wheel({metaKey:true}), true);
  assert.ok(Math.abs(radius()-(start+1.5)) < 1e-6);
  assert.equal(wheel({ctrlKey:true}), true);
  canvas.dispatchEvent(Object.assign(new Event('keydown',{cancelable:true}), {key:'+'}));
  controls.update();
  assert.ok(Math.abs(radius()-(start+2)) < 1e-6);
});
