// The virtual switchboard shares the assembly's parts, wiring and undo history.
import {register as registerDiagram} from './js/wiring-renderer.js';
import {register as registerValidation} from './js/wiring-validation.js';

const motorRows = [1,2,3,4].map(i => `<label><input id="wireM${i}" type="checkbox" checked>
  <span>M${i}</span><b id="wireM${i}State">OPEN</b></label>`).join('');

const panel = `<div class="wire-layout">
  <div class="wire-diagram-panel">
    <header class="wire-section-heading"><h2>2D wiring bench</h2>
      <button id="wireModeBadge" class="status" type="button" aria-pressed="false">Object mode</button></header>
    <div class="wire-buttons" aria-label="Edit wiring">
      <button id="autoWireBtn" type="button" class="btn primary">Reference wiring</button>
      <button id="wireUndoBtn" type="button" class="btn">Undo</button>
      <button id="deleteWireBtn" type="button" class="btn">Delete wire</button>
      <button id="deleteNodeBtn" type="button" class="btn">Delete object</button>
      <button id="centerWireLayoutBtn" type="button" class="btn">Reset layout</button>
      <button id="clearWireBtn" type="button" class="btn">Clear wires</button>
    </div>
    <p class="wire-instruction" id="wiringInstruction">In Object mode, drag parts by their labels. In Wire mode, select two terminals to connect them.</p>
    <div class="wire-viewport" tabindex="0" aria-label="Scrollable wiring diagram">
      <svg id="wiringSvg" viewBox="0 0 1500 900" aria-label="F450 terminals and connections" aria-describedby="wiringInstruction"></svg>
    </div>
    <div class="wire-legend-row"><span><i class="power"></i>Battery +</span><span><i class="ground"></i>Ground</span>
      <span><i class="signal"></i>PWM</span><span><i class="fivev"></i>5 V</span><span>Motor phases U / V / W</span></div>
    <small class="wire-fine">Virtual F450 circuit. The three-wire ESC leads represent the training model. Use your kit’s power and BEC wiring diagram for a physical build.</small>
  </div>
  <div class="wire-sidebar">
    <section class="wire-detail">
      <header class="wire-section-heading"><h3>Assembly checks</h3><span class="status" id="wireSyncBadge">0/4</span></header>
      <div id="wireAssemblySync"></div>
    </section>
    <details class="wire-detail" open><summary>Electrical check</summary><div id="wireValidation"></div></details>
    <details class="wire-detail"><summary>Virtual motor test</summary>
      <div class="wire-controls"><button type="button" id="wireRunBtn" class="btn">Run motor test</button>
      <span id="wireRunState" class="status">STOPPED</span></div>
      <label class="wire-range">PWM <output id="wirePwmOut">1000 µs</output>
        <input type="range" id="wireThrottle" min="1000" max="2000" step="10" value="1000"></label>
      <label class="wire-check"><input id="wireAllMotors" type="checkbox" checked>All four motors</label>
      <div class="wire-motors">${motorRows}</div>
    </details>
    <details class="wire-detail"><summary>Expansion modules</summary>
      <div class="wire-controls"><select aria-label="Virtual expansion module" id="optionalWireDevice">
        <option value="ppm">PPM receiver</option><option value="servo">Servo</option><option value="matrix">LED matrix</option>
        <option value="sensor">I²C sensor</option><option value="gps">GPS</option><option value="led">LED / output</option></select>
        <button type="button" id="addOptionalWireDevice" class="btn">Add</button></div>
      <label class="wire-check">GPS protocol <select id="wireGpsProtocol"><option value="NMEA_9600">NMEA 9600</option>
        <option value="UBX_10HZ">UBX 10 Hz</option></select></label><p class="wire-fine" id="wirePinPlan"></p>
    </details>
  </div></div>`;

export function mountWiring(ctx, container) {
  container.innerHTML = panel;
  registerDiagram(ctx);
  registerValidation(ctx);
  ctx.fcHeaderForMotor = motor => motor;
  const find = id => container.querySelector('#' + id);
  const bind = (id, event, run) => find(id).addEventListener(event, run);
  const {state} = ctx;
  let visible = false, frame = 0;

  function drawConnections() {
    ctx.render2D();
    ctx.rebuild3DWires();
    ctx.rebuildSolder();
  }
  function animate(now) {
    frame = 0;
    if (!visible || document.hidden || !ctx.wireMotorRun) return;
    ctx.animate2DMotors(now);
    frame = requestAnimationFrame(animate);
  }
  function stopTest() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    if (ctx.wireMotorRun) ctx.destroyMotorAudio('wire');
    ctx.wireMotorRun = false;
    find('wireRunBtn').textContent = 'Run motor test';
    ctx.updateMotorTestUI();
  }
  ctx.stopMotorTest = stopTest;
  function changeMode() {
    ctx.setWireMode();
    find('wireModeBadge').setAttribute('aria-pressed', String(ctx.wireMode));
  }
  bind('wireModeBadge','click',changeMode);
  bind('wireUndoBtn','click',ctx.undoAction);
  bind('deleteWireBtn','click',ctx.deleteSelectedWire);
  bind('deleteNodeBtn','click',ctx.deleteSelectedObject);
  bind('centerWireLayoutBtn','click',ctx.resetWireLayout);
  bind('addOptionalWireDevice','click',ctx.addOptionalWireDevice);
  bind('autoWireBtn','click',() => {
    ctx.historyPush();
    const plan = ctx.optionalReferencePlan(), stamp = Date.now();
    state.connections = [...ctx.referenceWires(), ...plan.wires].map(([from,to], i) => ({from,to,id:`ref-${stamp}-${i}`}));
    ctx.referencePinPlan = plan.assignments;
    ctx.selPort = ctx.selectedWireId = null;
    drawConnections();
    ctx.notify(`Reference wiring drawn: ${state.connections.length} connections.`);
  });
  bind('clearWireBtn','click',() => {
    ctx.historyPush();
    state.connections = [];
    ctx.selPort = ctx.selectedWireId = null;
    stopTest();
    drawConnections();
  });
  bind('wireGpsProtocol','change',event => {
    ctx.historyPush();
    state.gpsProtocol = event.target.value;
    ctx.render2D();
  });
  bind('wireRunBtn','click',() => {
    if (ctx.wireMotorRun) stopTest();
    else {
      ctx.wireMotorRun = true;
      ctx.ensureMotorAudio('wire');
      find('wireRunBtn').textContent = 'Stop motor test';
      ctx.wireAnimLast = performance.now();
      frame = requestAnimationFrame(animate);
    }
    ctx.render2D();
  });
  bind('wireThrottle','input',ctx.render2D);
  const allMotors = [1,2,3,4].map(i => find('wireM' + i));
  bind('wireAllMotors','change',event => {
    for (const check of allMotors) check.checked = event.target.checked;
    ctx.render2D();
  });
  allMotors.forEach(check => check.addEventListener('change',() => {
    find('wireAllMotors').checked = allMotors.every(box => box.checked);
    ctx.render2D();
  }));

  window.addEventListener('pointermove',event => {
    if (!visible || !ctx.wireDrag) return;
    const point = ctx.svgLocalPoint(find('wiringSvg'),event.clientX,event.clientY);
    ctx.setNodePos(ctx.wireDrag.id,point.x - ctx.wireDrag.dx,point.y - ctx.wireDrag.dy);
    ctx.render2D();
  });
  function endDrag() {
    if (!ctx.wireDrag) return;
    ctx.wireDrag = null;
    document.body.style.userSelect = '';
    ctx.persistWireLayout();
  }
  window.addEventListener('pointerup',endDrag);
  window.addEventListener('pointercancel',endDrag);
  window.addEventListener('keydown',event => {
    if (!visible || event.repeat || event.ctrlKey || event.metaKey || event.altKey ||
        event.target.closest?.('input, textarea, select, [contenteditable="true"]')) return;
    const key = event.key.toLowerCase();
    const action = {w:changeMode, r:ctx.rotateSelectedNode, f:ctx.flipSelectedNode,
      backspace:ctx.deleteSelectedObject, delete:ctx.deleteSelectedObject}[key];
    if (action) {event.preventDefault();action();}
    if (key === 'escape') {
      ctx.selPort = ctx.selectedWireId = ctx.selectedWireNodeId = null;
      ctx.render2D();
    }
  });
  window.addEventListener('blur',() => { if (ctx.wireMotorRun) stopTest(); endDrag(); });
  document.addEventListener('visibilitychange',() => { if (document.hidden && ctx.wireMotorRun) stopTest(); });
  return {
    show() { visible = true; ctx.render2D(); ctx.historyButtons(); },
    hide() { visible = false; endDrag(); if (ctx.wireMotorRun) stopTest(); }
  };
}
