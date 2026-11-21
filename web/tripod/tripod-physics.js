import {stepRatePid} from './rate-pid.js';
import {banks, terms, unpackGains, validGains} from './gains.js';
import {defaults} from '../config-commands.js';
/* F450 tripod educational dynamics. 250 Hz deterministic, physical motor thrust and
 * three-axis rigid-body rotational equations. No hardware/browser dependencies.
 * Teaching approximation: no aerodynamic measurement-based calibration claimed.
 */
export const STEP=.004;
export const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
export const degToRad=d=>d*Math.PI/180;
const DEG=180/Math.PI;
const wrap=a=>((a+180)%360+360)%360-180;
const clone=x=>JSON.parse(JSON.stringify(x));
export const DEFAULT_PID=unpackGains(defaults[2], defaults[3]);
export function controlSettings(flight=defaults[7], arming=defaults[4], setup=defaults[134]) {
 return {angleScale:flight[1],rateScale:flight[2],yawScale:flight[3],throttleLow:arming[0],idles:setup.slice(7,11)};
}
export const DEFAULT_ENV={batteryV:12.2,payloadG:0,cgX:0,cgY:0,wind:0,lag:0.04,gyroNoise:.07,noiseSeed:7919};
// SI-unit educational estimates, not measured aircraft calibration.
export const PLANT=Object.freeze({mass:1.12,g:9.81,maxRPM:8500,kT:11/(8500*Math.PI/30)**2,kQ:.020*11/(8500*Math.PI/30)**2,spring:100,damper:14,travel:.12});
export const MOTOR_GEOMETRY=[
 {x:-.325,z:.325,spin:1},{x:.325,z:.325,spin:-1},
 {x:.325,z:-.325,spin:1},{x:-.325,z:-.325,spin:-1}
];
const newPID=()=>({sum:0,last:0,ready:false,p:0,i:0,d:0,error:0,target:0,actual:0,output:0,derivative:0,saturated:false});
export function resetMetrics(s){s.metrics={rmsError:0,peakRate:0,motorSpread:0,ringing:0,liveError:0,samples:0,previousSign:0,lastCross:0,outputVariance:0,saturation:0,integral:0,overshoot:0}}
export function createSimulator(){
 const s={running:false,mode:'angle',throttle:1000,cmdRoll:0,cmdPitch:0,cmdYaw:0,pendingPID:{},settings:controlSettings(),primeGains:false,modeChanged:false,
 roll:0,pitch:0,yaw:0,rollRate:0,pitchRate:0,yawRate:0,
 gyroRoll:0,gyroPitch:0,gyroYaw:0,trimRoll:0,trimPitch:0,
 targetRoll:0,targetPitch:0,targetRollRate:0,targetPitchRate:0,targetYawRate:0,
 environment:clone(DEFAULT_ENV),pid:clone(DEFAULT_PID),memory:Object.fromEntries(Object.keys(DEFAULT_PID).map(k=>[k,newPID()])),
 motors:[0,0,0,0],motorCommands:[0,0,0,0],motorRPM:[0,0,0,0],motorRequestedRPM:[0,0,0,0],motorOmega:[0,0,0,0],motorThrust:[0,0,0,0],motorTorque:[0,0,0],motorSaturated:[false,false,false,false],
 vertical:{z:0,velocity:0,acceleration:0,thrust:0,weight:PLANT.mass*PLANT.g,ratio:0,support:PLANT.mass*PLANT.g,stop:'BOTTOM'},
 lift:0,anglePID:{roll:0,pitch:0},ratePID:{roll:0,pitch:0,yaw:0},
 inertia:[.045,.085,.048],pulse:null,time:0,accumulator:0,live:{bank:'angleRoll',...newPID()},metrics:{},profile:'F450 educational 3S'};
 resetMetrics(s);return s;
}
export function clearPID(s){for(const key of Object.keys(s.memory))s.memory[key]=newPID();s.live={bank:'angleRoll',...newPID()}}
export function resetIntegrators(s){for(const m of Object.values(s.memory)){m.sum=0;m.i=0}resetMetrics(s)}
export function releaseInputs(s){s.cmdRoll=s.cmdPitch=s.cmdYaw=0}
export function stopSimulator(s){
 s.running=false;s.throttle=1000;s.pulse=null;releaseInputs(s);clearPID(s);
 for(const field of ['motors','motorCommands','motorRPM','motorRequestedRPM','motorOmega','motorThrust','motorTorque'])s[field].fill(0);
 s.pendingPID={};s.primeGains=s.modeChanged=false;s.vertical.thrust=s.vertical.ratio=0;
 s.motorSaturated.fill(false);s.lift=s.accumulator=0;s.rollRate=s.pitchRate=s.yawRate=0;s.gyroRoll=s.gyroPitch=s.gyroYaw=0;
 s.targetRoll=s.trimRoll;s.targetPitch=s.trimPitch;s.targetRollRate=s.targetPitchRate=s.targetYawRate=0;
}
export function startSimulator(s,virtualStartPulse){
 if(s.running)return true;
 if(virtualStartPulse===undefined && s.throttle>1025)return false;
 if(virtualStartPulse!==undefined){
  if(!Number.isFinite(virtualStartPulse)||virtualStartPulse<1000||virtualStartPulse>2000)return false;
  s.throttle=virtualStartPulse;
 }
 s.running=true;clearPID(s);resetMetrics(s);return true;
}
export function resetSimulator(s){Object.assign(s.pid,s.pendingPID);stopSimulator(s);s.vertical.z=s.vertical.velocity=s.vertical.acceleration=0;s.vertical.stop='BOTTOM';s.roll=s.pitch=s.yaw=s.trimRoll=s.trimPitch=s.time=0;s.targetRoll=s.targetPitch=0;resetMetrics(s)}
export function setFlightMode(s,mode){
 if(!['angle','acro'].includes(mode))return false;
 if(s.mode!==mode){
  // The A1 primes roll/pitch rate errors on a mode change and clears the outer loop.
  s.modeChanged=s.running;
  s.mode=mode;s.pulse=null;
  for(const bank of ['angleRoll','anglePitch'])s.memory[bank]=newPID();
  if(!s.running)clearPID(s);
  resetMetrics(s);
 }
 return true;
}
export function setPID(s,bank,params){
 if(!Object.hasOwn(s.pid,bank)||!validGains(params))return false;
 if(s.running){s.pendingPID[bank]={...params};return true;}
 s.pid[bank]={...params};return true;
}
export function setSimulatorGains(s,values){
 if(!banks.every(bank=>validGains(values?.[bank])))return false;
 for(const bank of banks)setPID(s,bank,values[bank]);
 return true;
}
export function calibrateLevel(s){s.trimRoll=clamp(s.roll,-45,45);s.trimPitch=clamp(s.pitch,-45,45);clearPID(s)}
export function disturb(s,roll,pitch){s.roll=clamp(roll,-38,38);s.pitch=clamp(pitch,-38,38);s.rollRate=s.pitchRate=s.gyroRoll=s.gyroPitch=0;clearPID(s)}
export function startTuningPulse(s,axis='roll',amplitude=14){
 if(!s.running||s.throttle<1250||!['roll','pitch','yaw'].includes(axis))return false;
 s.pulse={axis,start:s.time,until:s.time+.56,amplitude:clamp(amplitude,3,25)};resetMetrics(s);return true;
}
function controlOutput(s,bank,target,measured){
 const memory=s.memory[bank];
 if(s.primeGains || (s.modeChanged && (bank==='rateRoll'||bank==='ratePitch'))) memory.error=target-measured;
 return stepRatePid(memory,s.pid[bank],target,measured,STEP)?.output??0;
}
// Quad X output order and pulse limits from the Areion FC A1 sketch, in µs.
export function motorMix(base,roll,pitch,yaw){
 return [base+roll-pitch+yaw,base-roll-pitch-yaw,base-roll+pitch+yaw,base+roll+pitch-yaw];
}
export function thrustTorque(forces){
 let pitch=0,roll=0,yaw=0;
 for(let i=0;i<4;i++){const m=MOTOR_GEOMETRY[i],f=forces[i];pitch-=m.z*f;roll-=m.x*f;yaw+=m.spin*.020*f;}
 return [roll,pitch,yaw];
}
function verticalStep(s){
 const v=s.vertical,mass=PLANT.mass+Math.max(0,s.environment.payloadG)/1000;
 v.weight=mass*PLANT.g;
 v.thrust=s.motorThrust.reduce((a,b)=>a+b,0)*Math.max(0,Math.cos(degToRad(s.roll))*Math.cos(degToRad(s.pitch)));
 v.ratio=v.thrust/v.weight;
 const force=v.thrust-v.weight-PLANT.spring*v.z-PLANT.damper*v.velocity;
 v.acceleration=force/mass;v.velocity+=v.acceleration*STEP;v.z+=v.velocity*STEP;v.support=0;v.stop='MOVING';
 if(v.z<=0){v.z=0;if(v.velocity<0)v.velocity=0;v.support=Math.max(0,-force);if(force<=0)v.acceleration=0;v.stop='BOTTOM';}
 if(v.z>=PLANT.travel){v.z=PLANT.travel;if(v.velocity>0)v.velocity=0;v.support=-Math.max(0,force);if(force>=0)v.acceleration=0;v.stop='UPPER STOP';}
 s.lift=v.ratio;
}
export function stepSimulator(s){
 if(!s.running){verticalStep(s);return s;}
 const edits=Object.entries(s.pendingPID);
 if(edits.length){
  if(edits.some(([bank,values])=>terms.some(key=>s.pid[bank][key]!==values[key]))){clearPID(s);s.primeGains=true;}
  Object.assign(s.pid,s.pendingPID);s.pendingPID={};
 }
 const dt=STEP;s.time+=dt;
 const e=s.environment,settings=s.settings,enabled=s.throttle>=settings.throttleLow;
 const p=s.pulse&&s.time<s.pulse.until?s.pulse:null;
 if(s.pulse&&s.time>=s.pulse.until)s.pulse=null;
 const anglePulse=axis=>p?.axis===axis?p.amplitude:0,ratePulse=axis=>p?.axis===axis?p.amplitude*(axis==='yaw'?5:4):0;
 // Both ANGLE and ACRO share exactly one inner rate controller per axis.
 const bankR='rateRoll',bankP='ratePitch',bankY='rateYaw';
 s.targetRoll=s.trimRoll+s.cmdRoll*500*settings.angleScale+(s.mode==='angle'?anglePulse('roll'):0);
 s.targetPitch=s.trimPitch+s.cmdPitch*500*settings.angleScale+(s.mode==='angle'?anglePulse('pitch'):0);
 s.targetRollRate=s.mode==='acro'?s.cmdRoll*500*settings.rateScale+ratePulse('roll'):controlOutput(s,'angleRoll',s.targetRoll,s.roll);
 s.targetPitchRate=s.mode==='acro'?s.cmdPitch*500*settings.rateScale+ratePulse('pitch'):controlOutput(s,'anglePitch',s.targetPitch,s.pitch);
 s.targetYawRate=s.cmdYaw*500*settings.yawScale+ratePulse('yaw');
 const gyroAlpha=1-Math.exp(-dt/.02);
 s.gyroRoll+=(s.rollRate-s.gyroRoll)*gyroAlpha;
 s.gyroPitch+=(s.pitchRate-s.gyroPitch)*gyroAlpha;
 s.gyroYaw+=(s.yawRate-s.gyroYaw)*gyroAlpha;
 const noise=clamp(e.gyroNoise??.07,0,2)+e.wind*.001,clock=s.time*89.17+(e.noiseSeed??7919)*.001;
 const uR=controlOutput(s,bankR,s.targetRollRate,s.gyroRoll+noise*Math.sin(clock));
 const uP=controlOutput(s,bankP,s.targetPitchRate,s.gyroPitch+noise*Math.cos(clock*.87));
 const uY=controlOutput(s,bankY,s.targetYawRate,s.gyroYaw+noise*.45*Math.sin(clock*1.13));
 s.primeGains=s.modeChanged=false;
 s.anglePID.roll=s.memory.angleRoll.output;s.anglePID.pitch=s.memory.anglePitch.output;
 s.ratePID.roll=uR;s.ratePID.pitch=uP;s.ratePID.yaw=uY;
 const mix=motorMix(Math.min(1800,s.throttle),uR,uP,uY);
 const alpha=1-Math.exp(-dt/clamp(e.lag,.04,.30)),battery=clamp(e.batteryV/12.6,.65,1);
 for(let i=0;i<4;i++){
  s.motorSaturated[i]=enabled && (mix[i]<settings.idles[i]||mix[i]>1999);
  s.motorCommands[i]=enabled?(clamp(mix[i],settings.idles[i],1999)-1000)/10:0;
  s.motorRequestedRPM[i]=PLANT.maxRPM*battery*s.motorCommands[i]/100;
  const requestedOmega=s.motorRequestedRPM[i]*Math.PI/30;
  s.motorOmega[i]+=alpha*(requestedOmega-s.motorOmega[i]);
  s.motorRPM[i]=s.motorOmega[i]*30/Math.PI;
  s.motors[i]=100*s.motorRPM[i]/PLANT.maxRPM;
  s.motorThrust[i]=PLANT.kT*s.motorOmega[i]**2;
 }
 // Torque from real individual motor forces at X-frame arm coordinates.
 let [tZ,tX,tY]=thrustTorque(s.motorThrust);
 if(!enabled)clearPID(s);
 const roll=s.rollRate/DEG,pitch=s.pitchRate/DEG,yaw=s.yawRate/DEG;
 const Ixx=.045*(1+e.payloadG/900),Iyy=.085*(1+e.payloadG/850),Izz=.048*(1+e.payloadG/900);
 // ω×Iω cross-coupling for axes X=pitch, Y=yaw, Z=roll.
 const crossX=(Izz-Iyy)*yaw*roll,crossY=(Ixx-Izz)*roll*pitch,crossZ=(Iyy-Ixx)*pitch*yaw;
 const wind=e.wind/100;
 const weight=(PLANT.mass+e.payloadG/1000)*PLANT.g;
 const biasX=e.cgY*.001*weight,biasZ=e.cgX*.001*weight;
 tX+=biasX+wind*.060*Math.cos(.87*s.time);
 tZ+=biasZ+wind*.060*Math.sin(1.17*s.time);
 tY+=wind*.016*Math.cos(1.51*s.time);
 const pitchAccel=(tX+crossX-0.12*pitch)/Ixx,rollAccel=(tZ+crossZ-0.12*roll)/Izz,yawAccel=(tY+crossY-.028*yaw)/Iyy;
 s.pitchRate=clamp(s.pitchRate+pitchAccel*DEG*dt,-720,720);
 s.rollRate=clamp(s.rollRate+rollAccel*DEG*dt,-720,720);
 s.yawRate=clamp(s.yawRate+yawAccel*DEG*dt,-720,720);
 // Tripod is gimbaled: mechanical travel limits; it does not spring-level ACRO.
 // In the pilot frame the nose is -Z. Positive RC commands lower the right wing,
 // lower the nose and turn the nose right. The YXZ display angles are all negated.
 const cr=Math.cos(degToRad(s.roll)),sr=Math.sin(degToRad(s.roll)),sp=Math.sin(degToRad(s.pitch));
 const yawDot=(-sr*s.pitchRate+cr*s.yawRate)/Math.cos(degToRad(s.pitch));
 const pitchDot=cr*s.pitchRate+sr*s.yawRate,rollDot=s.rollRate-sp*yawDot;
 s.roll=clamp(s.roll+rollDot*dt,-45,45);
 s.pitch=clamp(s.pitch+pitchDot*dt,-45,45);
 s.yaw=wrap(s.yaw+yawDot*dt);
 if(Math.abs(s.roll)>=45&&Math.sign(s.roll)===Math.sign(s.rollRate))s.rollRate=0;
 if(Math.abs(s.pitch)>=45&&Math.sign(s.pitch)===Math.sign(s.pitchRate))s.pitchRate=0;
 s.motorTorque=[tZ,tX,tY];
 verticalStep(s);
 const selected=s.mode==='angle'?'angleRoll':bankR;s.live={bank:selected,...s.memory[selected]};
 const target=s.mode==='acro'?s.targetRollRate:s.targetRoll,actual=s.mode==='acro'?s.rollRate:s.roll,error=target-actual;
 const m=s.metrics;m.samples++;
 m.rmsError=Math.sqrt(.993*m.rmsError*m.rmsError+.007*error*error);
 m.liveError=error;m.peakRate=Math.max(m.peakRate*.9995,Math.abs(s.rollRate),Math.abs(s.pitchRate));
 m.motorSpread=Math.max(...s.motors)-Math.min(...s.motors);m.integral=s.memory[bankR].sum;
 m.outputVariance=.985*m.outputVariance+.015*(uR*uR+uP*uP)/2;
 m.saturation+=s.motorSaturated.some(Boolean)?1:0;
 const sign=Math.abs(error)>1?Math.sign(error):0;
 if(sign&&m.previousSign&&sign!==m.previousSign&&s.time-m.lastCross>.15){m.ringing++;m.lastCross=s.time}
 if(sign)m.previousSign=sign;
 return s;
}
export function advanceSimulator(s,dt){
 s.accumulator=Math.min(.25,s.accumulator+clamp(dt,0,.25));
 while(s.accumulator+1e-10>=STEP){stepSimulator(s);s.accumulator-=STEP}
 return s;
}
export function getSnapshot(s){
 return {running:s.running,mode:s.mode,throttle:s.throttle,time:s.time,
 roll:s.roll,pitch:s.pitch,yaw:s.yaw,rollRate:s.rollRate,pitchRate:s.pitchRate,yawRate:s.yawRate,
 targetRoll:s.targetRoll,targetPitch:s.targetPitch,targetRollRate:s.targetRollRate,targetPitchRate:s.targetPitchRate,targetYawRate:s.targetYawRate,
 motors:[...s.motors],motorRPM:[...s.motorRPM],motorRequestedRPM:[...s.motorRequestedRPM],motorThrust:[...s.motorThrust],motorCommands:[...s.motorCommands],motorTorque:[...s.motorTorque],vertical:{...s.vertical},
 lift:s.lift,environment:{...s.environment},pulse:s.pulse?{...s.pulse}:null,live:{...s.live},metrics:{...s.metrics},
 controllers:Object.fromEntries(Object.entries(s.memory).map(([k,m])=>[k,{...m}]))};
}
