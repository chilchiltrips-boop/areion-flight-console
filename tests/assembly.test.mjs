import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import * as THREE from '../web/assembly/three.module.min.js';
import {loadGLB} from '../web/assembly/glb-loader.js';
import {CanvasRenderer} from '../web/assembly/js/canvas-renderer.js';
import {register as catalog} from '../web/assembly/js/catalog.js';
import {register as models} from '../web/assembly/js/model-assets.js';
import {register as project} from '../web/assembly/js/project-state.js';
import {register as scene} from '../web/assembly/js/assembly-scene.js';
import {register as guide} from '../web/assembly/js/shared-ui.js';
import {mountWiring} from '../web/assembly/wiring.js';
import {mount} from '../web/assembly/page.js';

const assets = new URL('../web/assembly/', import.meta.url);

function stubGlobal(t, name, value) {
  const original = Object.getOwnPropertyDescriptor(globalThis, name);
  Object.defineProperty(globalThis, name, {configurable:true, value});
  t.after(() => {
    if (original) Object.defineProperty(globalThis, name, original);
    else delete globalThis[name];
  });
}

test('opening Assembly loads its local viewer once and leaving flushes the project before detaching it', async t => {
  let active;
  const frames = [], events = [];
  const container = {replaceChildren(layout, frame) {
    assert.equal(layout.href, new URL('host.css', assets).href);
    active = frame;
  }};
  stubGlobal(t, 'document', {
    createElement(tag) {
      if (tag === 'link') return {};
      assert.equal(tag, 'iframe');
      const frame = {contentWindow:new EventTarget(), remove() { events.push('removed'); active = null; }};
      frame.contentWindow.addEventListener('areion-bench-leave', () => events.push('flush'));
      frames.push(frame);
      return frame;
    }
  });
  const page = mount(container);
  assert.equal(frames.length, 0);
  page.show();
  page.show();
  assert.equal(frames.length, 1);
  assert.equal(active.src, new URL('viewer.html', assets).href);
  const html = await readFile(new URL(active.src), 'utf8');
  const entryAssets = [...html.matchAll(/<(?:link|script)\b[^>]*(?:href|src)="([^"]+)"/g)];
  assert.ok(entryAssets.length > 0);
  for (const [,resource] of entryAssets) {
    assert.ok(new URL(resource, active.src).href.startsWith(assets.href));
    assert.ok((await readFile(new URL(resource, active.src))).length);
  }
  page.suspend();
  page.suspend();
  assert.deepEqual(events, ['flush', 'removed']);
  page.show();
  assert.equal(frames.length, 2);
  assert.notEqual(active, frames[0]);
});

test('the offline assembly loader builds every catalog mesh, including both propeller rotations', async t => {
  const ctx = {THREE, loadGLB};
  catalog(ctx);
  models(ctx);
  t.mock.method(globalThis, 'fetch', async path => {
    assert.match(path, /^[\w-]+\.glb$/);
    return new Response(await readFile(new URL(path, assets)));
  });
  const report = await ctx.loadAssets();
  assert.equal(report.failed, 0, JSON.stringify(report.errors));
  assert.equal(report.loaded, 15);
  for (const name of ctx.assetTemplates.keys()) {
    const model = ctx.cloneAsset(name);
    assert.ok(model && model !== ctx.assetTemplates.get(name), name);
    let vertices = 0;
    model.traverse(node => {
      if (node.isMesh) {
        vertices += node.geometry.getAttribute('position').count;
        assert.ok(Number.isFinite(node.geometry.boundingSphere.radius), name);
      }
    });
    assert.ok(vertices >= 3, name);
  }
  const prop = ctx.products.find(part => part.type === 'prop');
  assert.notEqual(prop.asset, prop.assetCCW);
  assert.ok(ctx.cloneAsset(prop.asset) && ctx.cloneAsset(prop.assetCCW));
  for (const {thumb} of ctx.products.filter(part => part.thumb)) {
    const bytes = await readFile(new URL(thumb, assets));
    assert.equal(bytes.readUInt32BE(), 0x89504e47, thumb);
  }

  // Exercise software projection with real GLB faces on machines without WebGL.
  let fills = 0;
  const drawing = {
    fill() { fills++; },
    moveTo(x,y) { assert.ok(Number.isFinite(x) && Number.isFinite(y)); },
    lineTo(x,y) { assert.ok(Number.isFinite(x) && Number.isFinite(y)); },
    setTransform(){}, beginPath(){}, closePath(){}, fillRect(){}, stroke(){}
  };
  stubGlobal(t, 'document', {createElement:() => ({getContext:() => drawing, setAttribute(){}, style:{}})});
  const renderer = new CanvasRenderer(THREE);
  renderer.setSize(640,480);
  const renderedScene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 640/480, .01, 1000);
  const frameModel = ctx.cloneAsset('f450_top_plate.glb');
  const bounds = new THREE.Box3().setFromObject(frameModel).getBoundingSphere(new THREE.Sphere());
  camera.position.copy(bounds.center).add(new THREE.Vector3(1,1,1).multiplyScalar(bounds.radius * 2));
  camera.lookAt(bounds.center);
  renderedScene.add(frameModel);
  renderer.render(renderedScene, camera);
  assert.ok(fills > 3 && renderer.faces.length > 0, 'the software camera draws the plate on the bench');
  renderer.dispose();
});

function workbench(t) {
  const ctx = {THREE, config:{historyLimit:30}}, buttons = new Map();
  catalog(ctx);
  project(ctx);
  scene(ctx);
  guide(ctx);
  const get = selector => {
    if (!buttons.has(selector)) buttons.set(selector, Object.assign(new EventTarget(), {
      classList:{add(){}, remove(){}, toggle(){}}, setAttribute(){}, value:'', checked:true
    }));
    return buttons.get(selector);
  };
  const dom = {querySelector:get};
  stubGlobal(t, 'document', new EventTarget());
  stubGlobal(t, 'window', new EventTarget());
  stubGlobal(t, 'cancelAnimationFrame', () => {});
  ctx.$ = get;
  mountWiring(ctx, dom);
  // Geometry is exercised separately. The guide, parts list, wiring, history and
  // inspection use their production methods without a GPU or a connected kit.
  const noop = () => {};
  Object.assign(ctx, {
    partsRoot:new THREE.Group(), extrasRoot:new THREE.Group(), createPart:() => new THREE.Group(),
    notify:noop, renderAssemblyUI:noop, renderShelf:noop, showInspector:noop,
    showGuides:noop, rebuildSolder:noop, rebuild3DWires:noop, playFX:noop, destroyMotorAudio:noop,
    setPowerVisual:on => {ctx.state.powered = on;},
    render2D:() => {ctx.syncWiringActionsToAssembly();ctx.advanceGuidedStepIfReady();}
  });
  return {ctx, click:id => get('#' + id).dispatchEvent(new Event('click'))};
}

test('guided placement, reference wiring, inspection and undo share the same virtual project', t => {
  const {ctx, click} = workbench(t), inspection = ctx.steps.at(-1);
  assert.equal(inspection.id, 'inspect');
  ctx.performAction(inspection);
  assert.equal(ctx.state.doneActions.has('inspect'), false);
  // Reference wiring alone cannot bypass installation.
  click('autoWireBtn');
  assert.ok(ctx.state.connections.length > 0);
  assert.equal(ctx.state.step, 0);
  assert.equal(ctx.state.doneActions.size, 0);

  const visited = new Set();
  while (ctx.steps[ctx.state.step] !== inspection) {
    const index = ctx.state.step, step = ctx.steps[index];
    assert.ok(!visited.has(step.id), 'Guide stalled at ' + step.id);
    visited.add(step.id);
    for (const type of step.types) {
      for (const slot of ctx.slots[type]) ctx.install(type, slot, false);
    }
    ctx.render2D();
    assert.ok(ctx.state.step > index, step.id);
  }
  assert.deepEqual([...ctx.wiringActionIds].filter(id => !ctx.state.doneActions.has(id)), []);
  assert.deepEqual([1,2,3,4].map(i => ctx.motorElectrical(i).dir), ['CW','CCW','CW','CCW']);
  assert.equal(ctx.state.powered, true);
  assert.equal(ctx.electricalIssues().some(issue => issue.level === 'bad'), false);

  const short = {from:'BAT.+',to:'PDB.BAT-'};
  ctx.state.connections.push(short);
  ctx.performAction(inspection);
  assert.equal(ctx.stepDone(ctx.steps.length-1), false);
  ctx.state.connections.pop();
  ctx.performAction(inspection);
  assert.equal(ctx.stepDone(ctx.steps.length-1), true);

  ctx.historyPush();
  ctx.state.connections.pop();
  ctx.render2D();
  assert.equal(ctx.state.doneActions.has('inspect'), false);
  ctx.undoAction();
  assert.equal(ctx.state.doneActions.has('inspect'), true);
  assert.equal(ctx.wiringActionReady('motorWire'), true);

  ctx.state.connections.push(short);
  ctx.render2D();
  assert.equal(ctx.state.doneActions.has('inspect'), false);
  ctx.state.connections.pop();
  ctx.render2D();
  assert.equal(ctx.state.doneActions.has('inspect'), false, 'Correcting the wiring requires inspection again');
});

test('the virtual auxiliary plan preserves the fixed Areion FC A1 PPM and IMU inputs', t => {
  const {ctx} = workbench(t);
  for (const type of ['receiver', 'sensor', 'servo', 'gps', 'led']) {
    ctx.install(type, ctx.slots[type][0], false);
  }
  ctx.$('#wireGpsProtocol').value = 'UBX_10HZ';
  const plan = ctx.optionalReferencePlan();
  const targets = plan.wires.map(wire => wire[1]);
  for (const target of ['FC.RX-S', 'FC.I2C-SDA', 'FC.I2C-SCL']) assert.ok(targets.includes(target), target);
  const aux = targets.filter(pin => pin.startsWith('FC.AUX-')).sort();
  assert.deepEqual(aux, ['FC.AUX-D7', 'FC.AUX-D8', 'FC.AUX-D9']);
  assert.notEqual(plan.assignments.gps.pin, plan.assignments.gps.txPin);
});
