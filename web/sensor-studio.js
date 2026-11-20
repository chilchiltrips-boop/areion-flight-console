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
const faceLabels = {captured:'Captured',holding:'Capturing',next:'Suggested',waiting:'Waiting'};
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
    '<div><strong>'+name+'</strong>'+field('face'+i,'Waiting')+'</div></li>').join('');
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
    '<section class="imu-card imu-capture"><header class="imu-heading"><h3>Six-position capture</h3>'+
    '<span class="imu-count">'+field('count','0 / 6')+'</span></header>'+
    '<ol class="imu-faces" aria-label="Calibration positions">'+checkpoints+'</ol>'+
    '<div class="imu-instruction" role="status" aria-live="polite" aria-atomic="true"><strong>'+field('instruction','Start calibration')+'</strong>'+
    '<span>'+field('detail','Hold the frame still on each side.')+'</span></div>'+
    '<div class="imu-progress"><progress aria-label="Current position capture" max="100" value="0"></progress>'+field('percent','0%')+'</div>'+
    '<div class="imu-actions"><button class="cfg-btn cfg-primary" type="button" data-act="start-sensor" disabled>Start calibration</button>'+
    '<button class="cfg-btn" type="button" data-act="cancel-sensor" hidden>Cancel</button>'+
    '<button class="cfg-btn cfg-primary" type="button" data-kit="imu" hidden disabled>Save calibration to kit</button></div></section></div>'+
    '<section class="imu-card imu-readings"><header class="imu-heading"><h3>Sensor readings</h3>'+field('result','Awaiting calibration')+'</header>'+
    '<div class="imu-table"><table><thead><tr><th scope="col">Axis</th><th scope="col">FC offset <small>(g)</small></th>'+
    '<th scope="col">Proposed offset <small>(g)</small></th><th scope="col">Corrected accel <small>(g)</small></th>'+
    '<th scope="col">Gyro rate <small>(°/s)</small></th></tr></thead><tbody>'+rows+'</tbody></table></div>'+
    '<div class="imu-quality" hidden><span>Max gravity error <b>'+field('error')+'</b></span>'+
    '<span>Stationary gyro residual <b>'+field('residual')+'</b></span></div>'+
    '<p class="imu-gyro-note">The kit sets its gyro bias at startup. This calibration checks the remaining drift.</p></section></section>';
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
    faces: Array.from(panel.querySelectorAll('[data-sensor-face]')),
    guide: node('[data-sensor-guide]'), live: node('[data-sensor-live]'),
    placeholder: node('[data-sensor-placeholder]'), signal: node('[data-sensor-signal]'),
    start: node('[data-act="start-sensor"]'), cancel: node('[data-act="cancel-sensor"]'),
    save: node('[data-kit="imu"]'), progress: node('progress'), quality: node('.imu-quality')
  };
  bindings.set(panel,view);
  return view;
}

function captureMessage(sensor, options, next) {
  if (options.working) return ['Kit operation in progress', 'Waiting for the controller’s reply.'];
  if (options.saved) return ['Calibration saved', 'The kit confirmed the offsets and sensor check.'];
  if (sensor.phase === 'error') return ['Calibration needs a new run', sensor.note];
  if (sensor.ready) return ['Calibration ready to save', 'Review the readings, then save the offsets to the kit.'];
  if (sensor.phase === 'stopped') return ['Calibration stopped',sensor.note || options.disabledReason];
  if (!sensor.active) return ['Six-position calibration', options.disabledReason || 'Start once, then hold the frame still on each of its six sides.'];
  if (sensor.phase === 'holding') return ['Hold still · '+shortNames[sensor.detected], 'Keep the frame still for three seconds while samples are collected.'];
  if (Number.isInteger(sensor.detected) && sensor.faces.has(sensor.detected)) {
    return [shortNames[sensor.detected]+' captured', instructions[next] || 'All positions captured.'];
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
  const holding = sensor.phase==='holding';
  const done = sensor.faces.size;
  const target = holding && Number.isInteger(sensor.detected) ? sensor.detected : sensor.nextPose;
  const targetIndex = Number.isInteger(target) && poses[target] ? target : 0;
  const finished = sensor.ready || saved;
  const current = sensor.detected;
  const reason = options.disabledReason || options.gateMessage || '';
  panel.dataset.phase = saved ? 'saved' : sensor.phase;
  write('count',done+' / 6');
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
    const state = sensor.faces.has(i) ? 'captured' : holding && current===i ? 'holding' : active && target===i ? 'next' : 'waiting';
    if (view.faces[i].dataset.state !== state) {
      view.faces[i].dataset.state = state;
      write('face'+i,faceLabels[state]);
    }
  }
  const [instruction,detail] = captureMessage(sensor,{working,saved,disabledReason:reason},targetIndex);
  write('instruction',instruction);
  write('detail',detail||'');
  const percent = finished ? 100 : holding ? Math.min(100,Math.round(sensor.progress*100)) : 0;
  if (view.progress.value !== percent) view.progress.value = percent;
  write('percent',percent+'%');
  view.start.hidden = active;
  view.start.disabled = working || !canStart;
  const startLabel = sensor.phase==='idle' && !saved ? 'Start calibration':'Restart calibration';
  if (view.start.textContent!==startLabel) view.start.textContent=startLabel;
  view.start.classList.toggle('cfg-primary',!sensor.ready || saved);
  view.cancel.hidden = !active;
  view.save.hidden = !sensor.ready || saved;
  if ('canSave' in options) view.save.disabled = !options.canSave || working;
  const stored = options.stored ?? ctx?.group(130)?.[5];
  write('result', saved?'Saved on kit':sensor.ready?'Proposed offsets':stored?'Kit calibration recorded':'Awaiting calibration');
  for (let i=0;i<3;i++) {
    const offset = sensor.offsets?.[i], reported = accel?.[i], currentOffset=base?.[i];
    const corrected = Number.isFinite(offset)&&Number.isFinite(currentOffset) ? reported-currentOffset+offset : reported;
    write('fc'+i,signed(currentOffset,4)); write('offset'+i,signed(offset,4));
    write('corrected'+i,signed(corrected,4)); write('gyro'+i,signed(gyro?.[i],2));
  }
  view.quality.hidden = !sensor.quality;
  if (sensor.quality) {
    write('error',unitValue(sensor.quality.maxError,3)+' g');
    write('residual',sensor.gyro?.map(value=>signed(value,2)).join(' / ')+' °/s');
  }
}
