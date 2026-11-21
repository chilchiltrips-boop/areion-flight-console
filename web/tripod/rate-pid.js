// Shared Rate PID contract: deg/s in, microsecond correction out, seconds dt.
import {validGains} from './gains.js';
const clip=(value,lo,hi)=>Math.max(lo,Math.min(hi,value));

export function stepRatePid(state,gains,target,actual,dt){
 const error=target-actual;
 if(!Number.isFinite(dt)||dt<.001||dt>.008||!Number.isFinite(error)||
    !validGains(gains))return null;
 // Matches pid_equation in the supplied working sketch, including reset history.
 const p=gains.p*error;
 const i=clip(state.sum+gains.i*(error+(state.error||0))*dt/2,-400,400);
 const derivative=(error-(state.error||0))/dt,d=gains.d*derivative;
 const total=p+i+d;
 if(!Number.isFinite(total))return null;
 Object.assign(state,{sum:i,error,target,actual,last:actual,derivative,ready:true,p,i,d,
  output:clip(total,-400,400),saturated:Math.abs(total)>400});
 return state;
}
