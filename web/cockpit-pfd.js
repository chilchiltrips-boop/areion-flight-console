const rad=Math.PI/180;
export const signed=v=>Number.isFinite(v)?(v>=0?'+':'')+(Math.abs(v)<.05?'0.0':v.toFixed(1))+'°':'—';
export const wrap=n=>((n+180)%360+360)%360-180;
const mix=(old,n,f)=>old+wrap(n-old)*f;
export function tilt(roll,pitch){
  return Math.acos(Math.max(-1,Math.min(1,Math.cos(roll*rad)*Math.cos(pitch*rad))))/rad;
}
function surface(canvas) {
  const w=canvas.clientWidth,h=canvas.clientHeight;
  if(!w||!h)return null;
  const ratio=Math.min(window.devicePixelRatio||1,2);
  const width=Math.round(w*ratio),height=Math.round(h*ratio);
  if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
  const p=canvas.getContext('2d');p.setTransform(ratio,0,0,ratio,0,0);p.clearRect(0,0,w,h);
  return {p,w,h};
}
function line(p,x1,y1,x2,y2){p.beginPath();p.moveTo(x1,y1);p.lineTo(x2,y2);p.stroke();}
function polygon(p,points){p.beginPath();points.forEach(([x,y],i)=>i?p.lineTo(x,y):p.moveTo(x,y));p.closePath();p.fill();}
function tape(canvas,yaw){
  const surfaceData=surface(canvas);if(!surfaceData||yaw==null)return;
  const {p,w,h}=surfaceData,scale=Math.max(2.8,Math.min(7,w/92)),cx=w/2;
  p.strokeStyle='#aac7c9';p.fillStyle='#c1d8da';p.textAlign='center';p.font='600 12px system-ui';
  for(let tick=Math.floor((yaw-w/(2*scale))/5)*5;tick<yaw+w/(2*scale);tick+=5){
    const x=cx+(tick-yaw)*scale,major=tick%10===0;line(p,x,h,x,h-(major?6:3));
    if(major&&Math.abs(x-cx)>36&&x>48){const n=wrap(tick);p.fillText((n>0?'+':'')+n,x,h/2);}
  }
}
function horizon(canvas,pose) {
  const data=surface(canvas);if(!data)return;
  const {p,w,h}=data,cx=w/2,cy=h*.55;
  const radius=Math.min(h*.43,w*.39),span=Math.hypot(w,h)+2;
  if(pose){
    const scale=Math.max(2.4,Math.min(8,h/48)),dy=pose.pitch*scale;
    p.save();p.translate(cx,cy);p.rotate(-pose.roll*rad);
    const sky=p.createLinearGradient(0,dy-h*.8,0,dy);sky.addColorStop(0,'#24608a');sky.addColorStop(.65,'#4e9ebd');sky.addColorStop(1,'#82c3ce');
    const earth=p.createLinearGradient(0,dy,0,dy+h*.95);earth.addColorStop(0,'#a58b57');earth.addColorStop(.54,'#806a45');earth.addColorStop(1,'#4d4939');
    p.fillStyle=sky;p.fillRect(-span,-span*2,span*2,span*2+dy);p.fillStyle=earth;p.fillRect(-span,dy,span*2,span*2);
    p.strokeStyle='#fff5c7';p.lineWidth=2;line(p,-span,dy,span,dy);
    p.strokeStyle='#f6fbf4';p.fillStyle='#f7fcf6';p.textAlign='left';p.font='600 12px system-ui';
    for(let n=-90;n<=90;n+=5){
      if(!n)continue;
      const y=dy-n*scale;
      if(Math.abs(y)>h*.45)continue;
      const major=n%10===0,half=major?Math.min(44,w*.075):18;p.lineWidth=major?1.6:1;
      line(p,-half,y,-5,y);line(p,5,y,half,y);
      if(major)p.fillText(String(n),half+5,y+4);
    }
    p.restore();
  }
  p.save();p.translate(cx,cy);p.strokeStyle=pose?'#f6fbf8':'#526f79';p.lineWidth=1.3;
  for(let deg=-60;deg<=60;deg+=10){
    const a=deg*rad,len=deg%30===0?9:5;line(p,Math.sin(a)*radius,-Math.cos(a)*radius,Math.sin(a)*(radius+len),-Math.cos(a)*(radius+len));
    if(pose&&w>350&&deg!==0&&deg%30===0){p.fillStyle='#f1f8f5';p.textAlign='center';p.font='600 10px system-ui';p.fillText(String(Math.abs(deg)),Math.sin(a)*(radius+18),-Math.cos(a)*(radius+18)+3);}
  }
  if(pose){
    p.save();p.rotate(-pose.roll*rad);p.fillStyle='#ffdd70';polygon(p,[[0,-radius],[-5,-radius+9],[5,-radius+9]]);p.restore();
    p.strokeStyle='#193039';p.lineWidth=6;const wing=Math.min(66,w*.13);
    const draw=()=>{p.beginPath();p.moveTo(-wing,0);p.lineTo(-wing*.42,0);p.lineTo(-wing*.17,8);p.moveTo(wing*.17,8);p.lineTo(wing*.42,0);p.lineTo(wing,0);p.stroke();};
    draw();p.strokeStyle='#ffda68';p.lineWidth=3;draw();p.fillStyle='#ffda68';p.beginPath();p.arc(0,0,3,0,Math.PI*2);p.fill();
  }
  p.restore();
}
export function flightDisplay(root){
  const field=root.querySelector('.pfd-field canvas'),yawTape=root.querySelector('.yaw-tape canvas');
  let prior=null,stamp='';
  return (imu,yaw,dt,reset)=>{
    const f=Math.min(1,Math.max(.12,dt/90));
    if(!imu)prior=null;
    else if(!prior||reset)prior={roll:imu.roll,pitch:imu.pitch,yaw};
    else prior={roll:mix(prior.roll,imu.roll,f),pitch:mix(prior.pitch,imu.pitch,f),yaw:yaw==null?null:prior.yaw==null?yaw:mix(prior.yaw,yaw,f)};
    const key=[field.clientWidth,field.clientHeight,yawTape.clientWidth,yawTape.clientHeight,prior?.roll.toFixed(2),prior?.pitch.toFixed(2),prior?.yaw?.toFixed(2)].join('/');
    if(key!==stamp||reset){horizon(field,prior);tape(yawTape,prior?.yaw);stamp=key;}
    root.querySelector('[data-wait]').hidden=!!imu;
  };
}
