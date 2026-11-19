// Mirror the desktop 10-second rate/angle response view, including setup gating.
export function responseTraces(rows, now, axis, angle) {
  const start=now-10000, result={measure:[],target:[]};
  let status=null,setup=null;
  let first=rows.length-1;
  for(;first>=0 && rows[first].at>=start-500;first--){}
  for(let i=first+1;i<rows.length;i++){
    const r=rows[i], v=r.values;
    if(r.at>now)break;
    if(r.group===120){status=r;continue;}
    if(r.group===130){setup=r;continue;}
    if(r.at<start)continue;
    const valid=status && r.at-status.at<=500 && status.values[2] && status.values[4]>0 && status.values[5]>0;
    if(r.group===21)result.measure.push([r.at,valid?v[(angle?8:0)+axis]:null]);
    if(r.group===23){
      const ready=valid && (!angle||status.values[1]) && setup && r.at-setup.at<=500 && !setup.values[0];
      result.target.push([r.at,ready?v[(angle?10:7)+axis]:null]);
    }
  }
  return result;
}
export function drawResponse(canvas,ctx,axis,angle) {
  const {clock,rows}=ctx, trace=responseTraces(rows,clock,axis,angle);
  const value=Math.max(1,...Object.values(trace).flat().map(p=>Math.abs(p[1]??0)));
  const w=canvas.clientWidth||290,h=canvas.clientHeight||140,dpi=Math.min(2,window.devicePixelRatio||1);
  canvas.width=Math.round(w*dpi);canvas.height=Math.round(h*dpi);
  const c=canvas.getContext('2d');c.scale(dpi,dpi);c.fillStyle='#132632';c.fillRect(0,0,w,h);
  const left=40,right=8,top=10,bottom=18;
  c.font='12px system-ui';c.fillStyle='#b0c2cd';c.lineWidth=1;
  for(let i=0;i<3;i++){
    const y=top+i*(h-top-bottom)/2;
    c.strokeStyle='#38505c';c.beginPath();c.moveTo(left,y);c.lineTo(w-right,y);c.stroke();
    const n=value*(1-i);c.fillText(Math.abs(n)>=10?n.toFixed(0):n.toFixed(1),1,y+3);
  }
  c.fillText('−10 s',left,h-2);c.fillText('now',w-27,h-2);
  for(const [series,color] of [[trace.measure,'#71dac4'],[trace.target,'#ffb66b']]){
    let prior=null;c.beginPath();c.lineWidth=1.75;c.strokeStyle=color;
    for(const [at,n] of series){
      if(!Number.isFinite(n)){prior=null;continue;}
      const x=w-right-(clock-at)/10000*(w-left-right),y=top+(1-n/value)*.5*(h-top-bottom);
      if(prior==null||at-prior>500)c.moveTo(x,y);else c.lineTo(x,y);
      prior=at;
    }
    c.stroke();
  }
}
