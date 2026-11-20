import * as THREE from './three.module.min.js';
import {loadGLB} from './glb-loader.js';
import {register as catalog} from './js/catalog.js';
import {register as project} from './js/project-state.js';
import {register as models} from './js/model-assets.js';
import {register as sound} from './js/sound-power.js';
import {register as sharedUI} from './js/shared-ui.js';
import {register as scene} from './js/assembly-scene.js';
import {register as wiringPreview} from './js/wiring-preview.js';
import {mountWiring} from './wiring.js';

const ctx = {
  THREE, loadGLB,
  config: {storageKey: 'areion.fc-a1.assembly.v1', historyLimit: 60}
};
for (const register of [catalog, project, models, sound, sharedUI, scene, wiringPreview]) register(ctx);
const wiring = mountWiring(ctx, document.querySelector('#tab-wiring'));
const {state} = ctx;
const get = id => document.getElementById(id);
let ready = false;

function updateControls() {
  for (const [id, pressed] of [
    ['guidedModeBtn', state.guided], ['freeModeBtn', !state.guided],
    ['explodeBtn', state.exploded]
  ]) {
    const button = get(id);
    button.classList.toggle('active', pressed);
    button.setAttribute('aria-pressed', String(pressed));
  }
  get('prevStepBtn').disabled = state.step === 0;
  get('nextStepBtn').disabled = state.step === ctx.steps.length - 1 || (state.guided && !ctx.stepDone(state.step));
  get('snapPartBtn').disabled = !ready || !state.selectedType;
  get('deletePartBtn').disabled = !ready || !state.selectedInstalledId;
  ctx.historyButtons();
}

const render = ctx.renderAssemblyUI;
ctx.renderAssemblyUI = () => {
  render();
  updateControls();
  ctx.persistWireLayout();
};
const selectProduct = ctx.selectProduct;
ctx.selectProduct = type => {
  selectProduct(type);
  if (state.selectedType === type) state.selectedInstalledId = null;
  updateControls();
};
// Scene picking is bound once during init3D; keyboard/touch controls share its selection.
const down = ctx.down;
ctx.down = event => {
  down(event);
  updateControls();
};

function changeView(name) {
  ctx.stopWiringPreview();
  const assembly = name !== 'wiring';
  for (const el of document.querySelectorAll('[data-bench-view]')) {
    const selected = el.dataset.benchView === (assembly ? 'assembly' : 'wiring');
    el.classList.toggle('active', selected);
    el.setAttribute('aria-pressed', String(selected));
  }
  for (const [id, active] of [['tab-assembly', assembly], ['tab-wiring', !assembly]]) {
    get(id).hidden = !active;
    get(id).classList.toggle('active', active);
  }
  if (assembly) {
    wiring.hide();
    requestAnimationFrame(ctx.resize3D);
  } else wiring.show();
}
ctx.setActiveTab = changeView;
for (const el of document.querySelectorAll('[data-bench-view]')) {
  el.addEventListener('click', () => changeView(el.dataset.benchView));
}

function setMode(guided) {
  if (state.guided === guided) return;
  ctx.stopWiringPreview();
  ctx.historyPush();
  state.guided = guided;
  // Return from free build to the earliest outstanding requirement.
  if (guided) {
    const next = ctx.steps.findIndex((_, i) => !ctx.stepDone(i));
    state.step = next < 0 ? ctx.steps.length - 1 : next;
  }
  state.selectedType = null;
  ctx.renderAssemblyUI();
  if (guided) ctx.showGuides();
  else ctx.guidesRoot.clear();
}
function moveStep(direction) {
  if (direction > 0 && state.guided && !ctx.stepDone(state.step)) return;
  ctx.historyPush();
  state.step = ctx.clamp(state.step + direction, 0, ctx.steps.length - 1);
  state.selectedType = null;
  ctx.renderAssemblyUI();
  ctx.showGuides();
}
const controls = {
  guidedModeBtn: () => setMode(true), freeModeBtn: () => setMode(false),
  prevStepBtn: () => moveStep(-1), nextStepBtn: () => moveStep(1),
  snapPartBtn: () => ctx.placeSelected(), deletePartBtn: () => ctx.deleteInstalled(state.selectedInstalledId),
  undoBtn: ctx.undoAction, redoBtn: ctx.redoAction, resetBtn: ctx.resetProject,
  explodeBtn: () => {ctx.stopWiringPreview(); ctx.toggleExplode();},
  view3dBtn: () => ctx.setView('3d'), topBtn: () => ctx.setView('top'), frontBtn: () => ctx.setView('front'),
  batteryConnectBtn: ctx.toggleBatteryPower,
  soundBtn: () => {
    ctx.soundEnabled = !ctx.soundEnabled;
    if (!ctx.soundEnabled) {
      ctx.stopTransientTones();
      ctx.destroyMotorAudio('wire');
    }
    get('soundBtn').textContent = ctx.soundEnabled ? 'Sound on' : 'Sound off';
    get('soundBtn').setAttribute('aria-pressed', String(ctx.soundEnabled));
  }
};
for (const [id, action] of Object.entries(controls)) {
  get(id).addEventListener('click', () => {
    if (!ready) return;
    action();
    updateControls();
  });
}

window.addEventListener('keydown', e => {
  if (!ready || e.defaultPrevented || e.target.closest?.('input,textarea,select,[contenteditable="true"]')) return;
  const key = e.key.toLowerCase();
  if ((e.ctrlKey || e.metaKey) && ['z','y'].includes(key)) {
    e.preventDefault();
    if (key === 'y' || e.shiftKey) ctx.redoAction();
    else ctx.undoAction();
  } else if (!get('tab-assembly').hidden && !e.repeat && !e.altKey && !e.ctrlKey && !e.metaKey) {
    if (['backspace','delete'].includes(key) && state.selectedInstalledId) {
      e.preventDefault();
      ctx.deleteInstalled(state.selectedInstalledId);
    } else if (key === 'escape') {
      ctx.stopWiringPreview();
      state.selectedType = null;
      state.selectedInstalledId = null;
      if (ctx.snapPreview) ctx.snapPreview.visible = false;
      ctx.renderShelf();
      updateControls();
    }
  }
});
function leaveBench() {
  if (!ready) return;
  ctx.stopWiringPreview();
  ctx.saveProject();
  wiring.hide();
  ctx.stopTransientTones();
}
window.addEventListener('areion-bench-leave', leaveBench);
window.addEventListener('pagehide', leaveBench);

async function boot() {
  get('app').inert = true;
  ctx.init3D();
  new ResizeObserver(ctx.resize3D).observe(get('threeContainer'));
  const result = await ctx.loadAssets();
  ctx.loadProject();
  ready = true;
  ctx.renderAssemblyUI();
  ctx.render2D();
  ctx.setWireMode(false, true);
  ctx.showGuides();
  const engine = ctx.renderer?.isCanvasRenderer ? 'Software 3D' : '3D';
  ctx.setBootStatus(engine + ' · ' + result.loaded + '/' + result.total + ' models', result.failed ? 'bad' : 'good');
  const app = get('app');
  app.dataset.models = String(result.loaded);
  app.dataset.modelErrors = String(result.failed);
  app.dataset.webgl = String(!ctx.renderer?.isCanvasRenderer);
  app.dataset.ready = 'true';
  app.inert = false;
}
boot().catch(error => {
  console.error('Assembly initialization failed', error);
  get('app').inert = false;
  ctx.setBootStatus('Workbench could not start.', 'bad');
  const retry = document.createElement('button');
  retry.className = 'btn';
  retry.textContent = 'Retry';
  retry.onclick = () => location.reload();
  get('assetStatus').after(retry);
});
