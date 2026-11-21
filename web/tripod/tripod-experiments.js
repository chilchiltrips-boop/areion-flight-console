import {createSimulator, setFlightMode, setSimulatorGains, startSimulator, stepSimulator, STEP} from './tripod-physics.js';

export const exercises = {
  step: {label:'Stick and release', hint:'Increase P and compare how closely the axis tracks the stick, then watch the release.'},
  load: {label:'Hold against a load', hint:'Change I and compare the steady error while the stand is pushed continuously.'},
  bump: {label:'Recover from a bump', hint:'Change D and compare peak movement and recovery after the same short push.'}
};
const seconds = 5, begin = .5, release = 1.5, pushDuration = .16;

export const practiceTicks=Math.round(seconds/STEP);

// The graph and the animated stand use exactly the same input at each control tick.
export function practiceStep(sim, axis, exercise, index) {
  const t=index*STEP;
  const name=axis[0].toUpperCase()+axis.slice(1);
  if (exercise==='step') sim['cmd'+name]=(t>=begin && t<release) ? .26 : 0;
  else if (t>=begin && (exercise==='load' || t<begin+pushDuration)) {
    const acceleration=exercise==='load'?18:180; // External push in °/s².
    sim[axis+'Rate']+=acceleration*STEP;
  }
  stepSimulator(sim);
}

export function practiceTrial({gains, mode, axis, exercise, environment, settings}) {
  if (!['angle','acro'].includes(mode) || !['roll','pitch','yaw'].includes(axis) || !Object.hasOwn(exercises,exercise))
    throw Error('Choose a flight mode, axis and exercise.');
  const sim = createSimulator();
  if (!setSimulatorGains(sim,gains)) throw Error('Invalid practice gains.');
  Object.assign(sim.environment,environment);
  if (settings) sim.settings = {...settings,idles:[...settings.idles]};
  setFlightMode(sim,mode);
  startSimulator(sim,1500);

  const name = axis[0].toUpperCase()+axis.slice(1);
  const isRate = mode==='acro' || axis==='yaw';
  const unit = isRate?'°/s':'°';
  const targetKey = 'target'+name+(isRate?'Rate':'');
  const measuredKey = axis+(isRate?'Rate':'');
  const releaseAt = exercise==='step'?release:begin+pushDuration;
  const tolerance = isRate?1:.5;
  const samples = [];
  let squareError=0, count=0, tailError=0, tailCount=0, peak=0;
  let lastOutside=releaseAt, limit=false;
  for (let i=0; i<practiceTicks; i++) {
    const t=i*STEP;
    practiceStep(sim,axis,exercise,i);
    const target=sim[targetKey], measured=sim[measuredKey], error=Math.abs(target-measured);
    if (i%5===0 || i===practiceTicks-1)
      samples.push({t:(i+1)*STEP,target,measured});
    if (t<begin) continue;
    peak=Math.max(peak,Math.abs(measured));
    squareError+=error*error; count++;
    if (t>=seconds-.5) {tailError+=error;tailCount++;}
    if (t>=releaseAt && error>tolerance) lastOutside=t+STEP;
    if (Math.abs(sim.roll)>=45 || Math.abs(sim.pitch)>=45) limit=true;
  }
  // Require a continuous quarter second in band at the end. Stand contact can mask rate error.
  const settling=exercise!=='load' && !limit && seconds-lastOutside>=.25 ? Math.max(0,lastOutside-releaseAt):null;
  return {samples, unit, duration:seconds, rms:Math.sqrt(squareError/count), tail:tailError/tailCount,
    peak, settling, finalAngle:sim[axis], limit};
}
