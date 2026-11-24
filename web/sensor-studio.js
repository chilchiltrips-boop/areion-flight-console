import {airframe} from './airframe.js';
import {poses} from './calibration.js';

const shortNames = poses.map(([label]) => label);
const instructions = [
  'Rest the frame upright on a level surface.',
  'Point the front of the frame straight up.',
  'Point the front of the frame straight down.',
  'Rest the frame on its left side.',
  'Rest the frame on its right side.',
  'Turn the frame over with its top facing down.'
];
const axes = ['X', 'Y', 'Z'];
const faceLabels = {captured:'Captured',holding:'Capturing',next:'Suggested',waiting:'Waiting',retry:'Repeat'};
const empty = '—';
const bindings = new WeakMap();
const unitValue = (value, precision) => Number.isFinite(value) ? value.toFixed(precision) : empty;
const signed = (value, precision) => Number.isFinite(value)
  ? (value > 0 && Number(value.toFixed(precision)) !== 0 ? '+' : '') + value.toFixed(precision) : empty;
const field = (key,value=empty) => '<span data-sensor-field="'+key+'">'+value+'</span>';

function loadStyles() {
  if (document.querySelector('link[data-sensor-css]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = new URL('./sensor-studio.css',import.meta.url).href;
  link.dataset.sensorCss = '';
  document.head.append(link);
}

export function sensorStudio() {
  loadStyles();
  const checkpoints = shortNames.map((name,i) =>
    '<li data-sensor-face="'+i+'"><span class="imu-face-mark" aria-hidden="true"></span>'+
    '<button type="button" class="imu-face-button" data-kit="face-'+i+'" aria-label="Recapture '+name+'" disabled>'+
    '<strong>'+name+'</strong>'+field('face'+i,'Waiting')+'</button></li>').join('');
  const rows = axes.map((a,i) =>
    '<tr><th scope="row"><i class="imu-axis axis-'+i+'" aria-hidden="true"></i>'+a+'</th><td>'+field('fc'+i)+'</td>'+
    '<td>'+field('offset'+i)+'</td><td>'+field('corrected'+i)+'</td><td>'+field('gyro'+i)+'</td></tr>').join('');
  return '<section class="imu-studio cfg-wide" data-sensor-studio aria-label="Automatic IMU calibration">'+
    '<div class="imu-grid"><section class="imu-card imu-stage"><header class="imu-heading"><h3>Orientation guide</h3>'+
    '<span class="imu-live-chip" data-sensor-signal><i aria-hidden="true"></i>'+field('signal','No live IMU')+'</span></header>'+
    '<div class="imu-views"><figure class="imu-model"><figcaption>'+field('guideLabel','Suggested position')+'</figcaption>'+
    '<canvas data-sensor-guide role="img" aria-label="Suggested aircraft orientation"></canvas><strong>'+field('guide','Flat / level')+'</strong></figure>'+
    '<figure class="imu-model imu-live-model"><figcaption>Measured position</figcaption>'+
    '<canvas data-sensor-live role="img" aria-label="Live aircraft orientation" hidden></canvas>'+
    '<div data-sensor-placeholder>Waiting for IMU</div><strong>'+field('detected')+'</strong></figure></div>'+
    '<dl class="imu-attitude">'+['Roll','Pitch','Rel yaw'].map((label,i)=>'<div><dt>'+label+'</dt><dd>'+field('angle'+i)+'</dd></div>').join('')+'</dl></section>'+
    '<section class="imu-card imu-capture"><header class="imu-heading"><h3>Accelerometer</h3>'+
    '<span class="imu-count">'+field('count','0 / 6')+'</span></header>'+
    '<div class="imu-methods" role="group" aria-label="Accelerometer calibration method">'+
    '<button type="button" data-acc-mode="six" aria-pressed="true">Six faces</button><button type="button" data-acc-mode="level" aria-pressed="false">Flat level</button></div>'+
    '<ol class="imu-faces" aria-label="Calibration positions">'+checkpoints+'</ol>'+
    '<div class="imu-instruction" role="status" aria-live="polite" aria-atomic="true"><strong>'+field('instruction','Start calibration')+'</strong>'+
    '<span>'+field('detail','Hold the frame still on each side.')+'</span></div>'+
    '<div class="imu-progress"><progress aria-label="Current position capture" max="100" value="0"></progress>'+field('percent','0%')+'</div>'+
    '<div class="imu-level-check" hidden><button class="cfg-btn" data-act="level-check" type="button">Check level</button><span data-level-result role="status">Uses the current offsets.</span></div>'+
    '<div class="imu-actions"><button class="cfg-btn cfg-primary" type="button" data-act="start-sensor" disabled>Start calibration</button>'+
    '<button class="cfg-btn cfg-primary" type="button" data-kit="resume-sensor" hidden disabled>Resume remaining faces</button>'+
    '<button class="cfg-btn cfg-primary" type="button" data-kit="retry-sensor" hidden disabled>Repeat highlighted faces</button>'+
    '<button class="cfg-btn" type="button" data-act="cancel-sensor" hidden>Cancel</button>'+
    '<button class="cfg-btn cfg-primary" type="button" data-kit="imu" hidden disabled>Save calibration to kit</button></div></section></div>'+
    '<section class="imu-card imu-gyro"><header class="imu-heading"><h3>Gyroscope</h3><strong class="imu-badge" data-gyro-badge>Awaiting kit</strong></header>'+
    '<div class="imu-gyro-grid"><div><p data-gyro-guide>Rest the frame on a firm surface and keep it still.</p>'+
    '<div class="imu-actions"><button class="cfg-btn cfg-primary" type="button" data-kit="start-gyro" disabled>Calibrate gyro</button>'+
    '<button class="cfg-btn" type="button" data-kit="cancel-gyro" hidden>Cancel gyro</button>'+
    '<button class="cfg-btn" type="button" data-act="gyro-drift" disabled>Check drift</button></div></div>'+
    '<div class="imu-gyro-result"><strong data-gyro-result role="status">Waiting for gyro readings</strong>'+
    '<progress data-gyro-progress aria-label="Gyroscope progress" max="100" value="0" hidden></progress>'+
    '<span data-gyro-values></span></div></div></section>'+
    '<section class="imu-card imu-readings"><header class="imu-heading"><h3>Sensor readings</h3>'+field('result','Awaiting calibration')+'</header>'+
    '<div class="imu-table"><table><thead><tr><th scope="col">Axis</th><th scope="col">FC offset <small>(g)</small></th>'+
    '<th scope="col">Proposed offset <small>(g)</small></th><th scope="col">Corrected accel <small>(g)</small></th>'+
    '<th scope="col">Gyro rate <small>(°/s)</small></th></tr></thead><tbody>'+rows+'</tbody></table></div>'+
    '<div class="imu-quality" hidden><span>Max gravity error <b>'+field('error')+'</b></span>'+
    '<span>Stationary gyro residual <b>'+field('residual')+'</b></span></div>'+
    '</section></section>';
}

function bind(panel) {
  let view = bindings.get(panel);
  if (view) return view;
  const node = q => panel.querySelector(q);
  const fields = new Map(Array.from(panel.querySelectorAll('[data-sensor-field]'), el=>[el.dataset.sensorField,el]));
  view = {
    write(key, text) {
      const el = fields.get(key);
      if (el.textContent !== text) el.textContent = text;
    },
    methods: Array.from(panel.querySelectorAll('[data-acc-mode]')),
    levelRow:node('.imu-level-check'),levelResult:node('[data-level-result]'),levelCheck:node('[data-act="level-check"]'),
    gyroBadge:node('[data-gyro-badge]'), gyroGuide:node('[data-gyro-guide]'), gyroResult:node('[data-gyro-result]'),
    gyroValues:node('[data-gyro-values]'), gyroProgress:node('[data-gyro-progress]'), drift:node('[data-act="gyro-drift"]'),
    gyroStart:node('[data-kit="start-gyro"]'),gyroCancel:node('[data-kit="cancel-gyro"]'),
    faces: Array.from(panel.querySelectorAll('[data-sensor-face]')),
    guide: node('[data-sensor-guide]'), live: node('[data-sensor-live]'),
    placeholder: node('[data-sensor-placeholder]'), signal: node('[data-sensor-signal]'),
    start: node('[data-act="start-sensor"]'), cancel: node('[data-act="cancel-sensor"]'),
    resume:node('[data-kit="resume-sensor"]'),retry: node('[data-kit="retry-sensor"]'), save: node('[data-kit="imu"]'), progress: node('progress'), quality: node('.imu-quality')
  };
  bindings.set(panel,view);
  return view;
}

function captureMessage(sensor, options, next) {
  if (options.working) return ['Kit operation in progress', 'Waiting for the controller’s reply.'];
  if (options.saved) return ['Calibration saved', 'The kit confirmed the offsets and sensor check.'];
  if (sensor.needsRetry) return ['Repeat '+sensor.quality.failed.map(i=>shortNames[i]).join(' · '), sensor.note];
  if (sensor.phase === 'error') return ['Calibration could not finish', sensor.note];
  if (sensor.ready) return ['Calibration ready to save', 'Review the readings, then save the offsets to the kit.'];
  if (sensor.phase === 'stopped') return ['Calibration stopped',sensor.note || options.disabledReason];
  if (options.mode==='level' && !sensor.active) return ['Quick level calibration',options.disabledReason || 'Rest the frame top up on a known level surface. For first setup, choose Six faces.'];
  if (!sensor.active) return ['Six-position calibration', options.disabledReason || 'Start once, then hold the frame still on each of its six sides.'];
  if (sensor.phase === 'holding') return ['Hold still · '+shortNames[sensor.detected], 'Keep the frame still for three seconds while samples are collected.'];
  if (options.mode==='level') return ['Keep the frame top up',sensor.note];
  if (Number.isInteger(sensor.detected) && sensor.faces.has(sensor.detected)) {
    return [shortNames[sensor.detected]+' captured', instructions[next] || 'All positions captured.'];
  }
  if (sensor.quality?.failed.length) {
    const face = sensor.detected ?? next;
    return ['Align '+shortNames[face], sensor.detected===null ? instructions[face] : sensor.note];
  }
  return ['Move to an uncaptured position', sensor.note || instructions[next]];
}

// Derive the static pose from gravity so the guide can display an inverted board.
// The FC's regular pitch/roll display can fold an upside-down orientation into ±90°.
function gravityPose(accel, relativeYaw) {
  if (!accel?.every(Number.isFinite)) return null;
  const [x,y,z] = accel, magnitude = Math.hypot(x,y,z);
  if (magnitude < .6 || magnitude > 1.5) return null;
  const degrees = 180 / Math.PI;
  const across = Math.hypot(y,z);
  return [across < .04 ? 0 : Math.atan2(y,z)*degrees, Math.atan2(-x,across)*degrees, relativeYaw ?? 0];
}

export function updateSensorStudio(root,sensor,options={}) {
  const panel = root.querySelector('[data-sensor-studio]');
  if (!panel) return;
  const view = bind(panel);
  const {write} = view;
  const {ctx,working=false,saved=false,canStart=false} = options;
  const liveImu = options.liveImu ?? ctx?.snapshot.imu;
  const imuValues = liveImu && ctx?.group(21,500);
  const base = options.base ?? ctx?.group(6);
  const accel = options.accel ?? imuValues?.slice(3,6);
  const gyro = options.gyro ?? imuValues?.slice(0,3);
  const measured = liveImu && gravityPose(accel,liveImu.yaw);
  const active = !!sensor.active;
  const level=options.mode==='level';
  for(const button of view.methods) {
    button.setAttribute('aria-pressed',String(button.dataset.accMode===(level?'level':'six')));
    button.disabled=working || active || options.levelCheck?.phase==='holding' || (!saved && (sensor.ready||sensor.needsRetry||sensor.phase==='error'));
  }
  const holding = sensor.phase==='holding';
  const done = sensor.faces.size;
  const target = sensor.needsRetry ? sensor.quality.failed[0] : holding && Number.isInteger(sensor.detected) ? sensor.detected : sensor.nextPose;
  const targetIndex = Number.isInteger(target) && poses[target] ? target : 0;
  const finished = sensor.ready || saved;
  const current = sensor.detected;
  const reason = options.disabledReason || options.gateMessage || '';
  panel.dataset.phase = saved ? 'saved' : sensor.phase;
  write('count',done+' / '+(level?1:6));
  write('guideLabel',finished?'Reference position':'Suggested position');
  write('guide',shortNames[targetIndex]);
  const model = options.profile==='areion250' ? 'areion250':'areion450';
  airframe(view.guide,model,poses[targetIndex][3],true);
  view.live.hidden = !measured;
  view.placeholder.hidden = !!measured;
  const replay = ctx?.replay;
  view.signal.dataset.live = !!liveImu && !replay ? 'yes' : 'no';
  write('signal',replay?'Recording':liveImu?'IMU receiving':'No live IMU');
  write('detected',measured && active && shortNames[current] ? shortNames[current] : measured?'Tracking':empty);
  if (measured) airframe(view.live,model,measured,true);
  for (let i=0;i<3;i++) {
    const angle = i===2 ? liveImu?.yaw : measured?.[i];
    write('angle'+i,Number.isFinite(angle)?signed(angle,1)+'°':empty);
  }
  for (let i=0;i<view.faces.length;i++) {
    view.faces[i].hidden=level && i!==0;
    const flag = sensor.quality?.failed.includes(i) && (sensor.needsRetry || active && !sensor.faces.has(i));
    const state = holding && current===i ? 'holding' : flag ? 'retry' : sensor.faces.has(i) ? 'captured' : active && target===i ? 'next' : 'waiting';
    if (view.faces[i].dataset.state !== state) view.faces[i].dataset.state = state;
    write('face'+i,state==='retry' ? 'Repeat · '+sensor.quality.faceErrors[i].toFixed(3)+' g error' : faceLabels[state]);
  }
  const [instruction,detail] = captureMessage(sensor,{working,saved,disabledReason:reason,mode:options.mode},targetIndex);
  write('instruction',instruction);
  write('detail',detail||'');
  const percent = finished ? 100 : holding ? Math.min(100,Math.round(sensor.progress*100)) : 0;
  if (view.progress.value !== percent) view.progress.value = percent;
  write('percent',percent+'%');
  view.start.hidden = active;
  view.start.disabled = working || !canStart;
  const startLabel = level?'Capture flat level':sensor.phase==='idle' && !saved ? 'Start calibration':'Restart calibration';
  if (view.start.textContent!==startLabel) view.start.textContent=startLabel;
  view.start.classList.toggle('cfg-primary',!sensor.ready && !sensor.needsRetry || saved);
  view.resume.hidden = !sensor.resumable;
  view.retry.hidden = !sensor.needsRetry;
  if (sensor.needsRetry) {
    const label = sensor.quality.failed.length===1 ? 'Repeat highlighted face' : 'Repeat highlighted faces';
    if (view.retry.textContent!==label) view.retry.textContent=label;
  }
  view.cancel.hidden = !active && (saved || !(sensor.ready||sensor.needsRetry||sensor.phase==='error'));
  view.cancel.textContent=active?'Stop capture':'Discard capture';
  view.save.hidden = !sensor.ready || saved;
  const saveLabel=level?'Save level offsets':'Save ACC calibration';
  if(view.save.textContent!==saveLabel)view.save.textContent=saveLabel;
  if ('canSave' in options) view.save.disabled = !options.canSave || working;
  const stored = options.stored ?? ctx?.group(130)?.[5];
  const verified=!!stored && !replay && ctx?.state==='connected';
  panel.dataset.accVerified=String(verified && (saved || !sensor.ready && !sensor.needsRetry && !sensor.active));
  write('result', saved?'✓ ACC saved on kit':sensor.ready?'Proposed offsets':sensor.needsRetry?'Outside fit limit':sensor.active?'Capture in progress':verified?'✓ ACC verified on kit':'Awaiting calibration');
  for (let i=0;i<3;i++) {
    const offset = sensor.offsets?.[i], reported = accel?.[i], currentOffset=base?.[i];
    const corrected = Number.isFinite(offset)&&Number.isFinite(currentOffset) ? reported-currentOffset+offset : reported;
    write('fc'+i,signed(currentOffset,4)); write('offset'+i,signed(offset,4));
    write('corrected'+i,signed(corrected,4)); write('gyro'+i,signed(gyro?.[i],2));
  }
  const gyroState=options.gyroState, native=!!gyroState, run=gyroState?.[0], drift=options.drift;
  const checking=drift?.phase==='holding', doneDrift=drift?.phase==='verified', state=ctx?.group(120,500);
  const streaming=ctx?.state==='connected'&&!replay&&!!liveImu;
  const manual=native&&run===2&&streaming, old=ctx?.group(125)?.[0] && !options.supportsGyro;
  const bootZero=streaming && state?.[2]===true && state[5]>=2000 && (!native||run===0);
  const gyroBadge=!streaming?'Awaiting kit':manual?'✓ Calibrated this boot':run===1?'Calibrating':
    run===3?'Capture failed':run===4?'Cancelled':bootZero?'✓ Startup zero complete':'Waiting for startup zero';
  if(view.gyroBadge.textContent!==gyroBadge)view.gyroBadge.textContent=gyroBadge;
  view.gyroBadge.dataset.ok=String(manual||bootZero);
  view.gyroBadge.dataset.bad=String(streaming && run===3);
  const message=old?'This firmware zeros the gyro at startup. Keep the frame still during restart, then check drift. Firmware 3.5 adds Calibrate gyro.':
    'Keep the frame still in any orientation. The kit measures gyro bias again at each startup.';
  if(view.gyroGuide.textContent!==message)view.gyroGuide.textContent=message;
  const gyroNote=checking?'Measuring stationary drift…':run===1?(gyroState[1]<500?'Measuring gyro bias…':'Verifying gyro bias…'):
    drift && drift.phase!=='idle'?drift.note:run>=2?gyroState[4]:streaming?'Ready for a stationary check':'Waiting for live gyro readings';
  if(view.gyroResult.textContent!==gyroNote)view.gyroResult.textContent=gyroNote;
  view.gyroResult.dataset.ok=String(!!doneDrift && streaming);
  view.gyroResult.dataset.bad=String((!checking && !doneDrift && run===3)||drift?.phase==='failed');
  view.gyroStart.hidden=!!old||run===1;view.gyroCancel.hidden=run!==1;
  const levelResult=options.levelCheck,checkingLevel=levelResult?.phase==='holding';
  view.levelRow.hidden=!level;
  view.levelCheck.disabled=!options.canDrift || checking || checkingLevel || run===1 || active || working;
  const levelText=checkingLevel?'Checking level… '+Math.round(levelResult.window.progress*100)+'%':
    levelResult?.note || 'Read-only check with the current offsets.';
  if(view.levelResult.textContent!==levelText)view.levelResult.textContent=levelText;
  view.levelResult.dataset.ok=String(streaming && levelResult?.phase==='verified');
  view.levelResult.dataset.bad=String(levelResult?.phase==='failed');
  view.drift.disabled=!options.canDrift || checkingLevel || checking || run===1 || active || working;
  view.gyroProgress.hidden=!checking && run!==1;
  view.gyroProgress.value=checking?Math.round(drift.window.progress*100):run===1?Math.round(gyroState[1]*100/gyroState[2]):0;
  const gyroText=drift?.mean?'Drift '+drift.mean.map(v=>signed(v,2)).join(' / ')+' °/s':
    streaming&&native?'Bias '+gyroState.slice(5,8).map(v=>signed(v,2)).join(' / ')+' °/s':'';
  if(view.gyroValues.textContent!==gyroText)view.gyroValues.textContent=gyroText;
  view.quality.hidden = !sensor.quality;
  if (sensor.quality) {
    write('error',unitValue(sensor.quality.maxError,3)+' g');
    write('residual',sensor.gyro?.map(value=>signed(value,2)).join(' / ')+' °/s');
  }
}
