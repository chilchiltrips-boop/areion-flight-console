// Temporary scene geometry, independent of installed parts, electrical state and history.
const matchesStep = {
  motorWire: ([from]) => /^ESC[1-4]\.[UVW]$/.test(from),
  powerWire: ([from]) => from.startsWith('PDB.E'),
  escFc: ([,to]) => to.startsWith('FC.ESC'),
  xt60: ([from]) => from.startsWith('BAT.')
};

export function wiresForStep(ctx, id) {
  return matchesStep[id] ? ctx.referenceWires().filter(matchesStep[id]) : [];
}

export function register(ctx) {
  const box = ctx.$('#assemblyWiringPreviewBox');
  const button = ctx.$('#assemblyWiringPreviewBtn');
  const label = ctx.$('#assemblyWiringPreviewLabel');
  let playback = null;
  const segmentMs = 1050;

  function stop() {
    if (!playback) return;
    const {group, frame} = playback;
    playback = null;
    if (frame !== null) cancelAnimationFrame(frame);
    group.removeFromParent();
    group.traverse(object => {
      object.geometry?.dispose();
      object.material?.dispose();
    });
    button.textContent = 'Preview wiring';
    button.setAttribute('aria-pressed','false');
    label.textContent = '';
  }

  function showStep(step) {
    const wiring = ctx.wiringActionIds.has(step.id);
    const eligible = wiring && ctx.wiringPrerequisitesReady(step.id);
    if (playback && (playback.id !== step.id || !eligible)) stop();
    box.hidden = !wiring;
    button.disabled = !eligible;
    button.title = wiring && !eligible ? 'Install the parts for this step first' : '';
  }

  function play(step) {
    if (!step || step.id !== ctx.steps[ctx.state.step].id ||
        !ctx.wiringActionIds.has(step.id) || !ctx.wiringPrerequisitesReady(step.id)) return;
    if (playback) stop();
    const pairs = wiresForStep(ctx,step.id);
    if (!pairs.length) return;
    const {THREE} = ctx;
    const group = new THREE.Group();
    group.name = 'Wiring preview';
    const staticView = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const paths = pairs.map(([from,to]) => {
      const curve = new THREE.CatmullRomCurve3(ctx.routePoints({from,to}));
      const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve,28,0.045,6,false),
        new THREE.MeshBasicMaterial({color:ctx.wColor(from)}));
      mesh.visible = staticView;
      group.add(mesh);
      return {curve,mesh,description:from + ' → ' + to};
    });
    ctx.scene.add(group);
    playback = {id:step.id,group,frame:null};
    button.textContent = 'Stop preview';
    button.setAttribute('aria-pressed','true');
    if (staticView) {
      label.textContent = step.title;
      return;
    }

    const marker = new THREE.Mesh(new THREE.SphereGeometry(.095,12,8),
      new THREE.MeshBasicMaterial({color:0xddfff5}));
    group.add(marker);
    let last = -1;
    const start = performance.now();
    function advance(now) {
      if (!playback || playback.group !== group) return;
      const position = Math.max(0,now-start)/segmentMs;
      const index = Math.floor(position);
      if (index >= paths.length || ctx.steps[ctx.state.step].id !== step.id) { stop(); return; }
      const current = paths[index];
      if (last !== index) {
        if (last >= 0) paths[last].mesh.visible = false;
        current.mesh.visible = true;
        label.textContent = current.description;
        last = index;
      }
      current.curve.getPointAt(Math.min(1,(position-index)*1.25),marker.position);
      playback.frame = requestAnimationFrame(advance);
    }
    advance(start);
  }

  ctx.previewWiringAction = play;
  ctx.syncWiringPreview = showStep;
  ctx.stopWiringPreview = stop;
  button.onclick = () => playback ? stop() : play(ctx.steps[ctx.state.step]);
  button.setAttribute('aria-pressed','false');
}
