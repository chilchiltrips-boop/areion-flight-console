// Capture windows and opposite-face estimates follow sensor_calibration.py.
export const poses = [
  ['Flat / level',2,1,[0,0,0]], ['Nose up',0,-1,[0,90,0]], ['Nose down',0,1,[0,-90,0]],
  ['Left side down',1,-1,[-90,0,0]], ['Right side down',1,1,[90,0,0]], ['Upside down',2,-1,[180,0,0]]
];
const mean = col => col.reduce((sum,v)=>sum+v,0)/col.length;
const spread = col => {const m=mean(col); return Math.sqrt(mean(col.map(v=>(v-m)**2)));};
export class SensorCheck {
  constructor(){this.clear();}
  clear() {this.active=null; this.faces=new Map(); this.offsets=null; this.gyro=null; this.note=''; this.baseline=null;}
  begin(which,now,offsets) {
    if(this.active || !offsets || (which !== 'gyro' && this.faces.has(which))) return false;
    if(!this.baseline) this.baseline=[...offsets];
    this.active={which,started:now,frames:[],times:[]};
    this.note='Keep the board still.'; return true;
  }
  stop(note) {this.active=null; this.note=note;}
  get progress() {
    const cap=this.active;
    if(!cap?.times.length) return 0;
    return Math.min(1,(cap.times.at(-1)-cap.times[0])/3000,cap.times.length/20);
  }
  sample(values,at) {
    const cap=this.active;
    if(!cap || at<cap.started || at<=(cap.times.at(-1)??-Infinity)) return;
    if(at-cap.started>12000 || cap.times.length && at-cap.times.at(-1)>500) return this.stop('Signal interrupted. Retry this capture.');
    const a=values.slice(3,6), g=values.slice(0,3), mag=Math.hypot(...a);
    if(![...a,...g].every(Number.isFinite) || Math.max(...g.map(Math.abs))>5 || mag<.6 || mag>1.5)
      return this.stop('Movement detected. Steady the board and retry.');
    if(cap.which !== 'gyro'){
      const [,axis,sign]=poses[cap.which];
      if(a[axis]*sign<.65 || a.some((v,i)=>i!==axis&&Math.abs(v)>.35)) return this.stop('Orientation differs from the target. Reposition the board and retry.');
    }
    cap.frames.push([...g,...a]); cap.times.push(at);
    if(this.progress<1) return;
    const cols=Array.from({length:6},(_,i)=>cap.frames.map(f=>f[i]));
    if(cols.some((col,i)=>spread(col)>(i<3?.8:.025))) return this.stop('Samples varied. Remove vibration and retry.');
    if(cap.which==='gyro') {this.gyro=cols.slice(0,3).map(mean);return this.stop('Stationary gyro residual captured locally.');}
    this.faces.set(cap.which,cols.slice(3).map((col,i)=>mean(col)-this.baseline[i]));
    this.stop('Position captured locally.');
    if(this.faces.size===6){
      const bias=[],scale=[];
      for(let i=0;i<3;i++) {
        const face=sign=>this.faces.get(poses.findIndex(([,axis,s])=>axis===i&&s===sign))[i];
        const high=face(1),low=face(-1);
        bias.push(-(high+low)/2); scale.push(2/(high-low));
      }
      const invalid=bias.some((b,i)=>!Number.isFinite(b)||Math.abs(b)>.5||scale[i]<.8||scale[i]>1.2);
      const aligned=poses.every(([,axis,sign],idx)=>Math.hypot(...this.faces.get(idx).map((v,i)=>(v+bias[i])*scale[i]-(axis===i?sign:0)))<=.25);
      if(invalid||!aligned)return this.stop('Six positions disagree. Reset captures and repeat.');
      this.offsets=bias; this.note='Six-face estimate complete. Candidate offsets below.';
    }
  }
}
