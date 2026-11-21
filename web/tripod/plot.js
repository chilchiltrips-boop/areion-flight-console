const colors = ['#70e3cb','#ffbd77','#a8b8ff','#e98faa'];
export const plotColors = colors;
export function drawPlot(canvas, traces, {start, end, unit, empty='Run the simulator to see its response'}) {
  const w=canvas.clientWidth,h=canvas.clientHeight;
  if(!w||!h) return;
  const dpi=Math.min(2,window.devicePixelRatio||1);
  if(canvas.width!==Math.round(w*dpi)||canvas.height!==Math.round(h*dpi)){
    canvas.width=Math.round(w*dpi);canvas.height=Math.round(h*dpi);
  }
  const c=canvas.getContext('2d');c.setTransform(dpi,0,0,dpi,0,0);
  c.fillStyle='#0d2230';c.fillRect(0,0,w,h);
  const left=48,right=w-12,top=13,bottom=h-25;
  let lo=0,hi=0,hasData=false;
  for(const trace of traces)for(const [t,v] of trace.points){
    if(t<start||t>end||!Number.isFinite(v))continue;
    lo=Math.min(lo,v);hi=Math.max(hi,v);hasData=true;
  }
  const pad=Math.max(.5,(hi-lo)*.09);lo-=pad;hi+=pad;
  const x=t=>left+(t-start)/Math.max(.001,end-start)*(right-left);
  const y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
  c.font='12px system-ui';c.lineWidth=1;c.fillStyle='#a8c1ca';
  for(let i=0;i<=4;i++){
    const t=start+(end-start)*i/4;
    c.strokeStyle='#27434e';c.beginPath();c.moveTo(x(t),top);c.lineTo(x(t),bottom);c.stroke();
    c.textAlign=i===4?'right':i===0?'left':'center';
    c.fillText((Math.round(t*10)/10)+' s',x(t),h-7);
  }
  for(let i=0;i<3;i++){
    const v=lo+(hi-lo)*i/2;
    c.beginPath();c.moveTo(left,y(v));c.lineTo(right,y(v));c.stroke();
    c.textAlign='right';c.fillText((Math.abs(v)<10?v.toFixed(1):Math.round(v))+'',left-5,y(v)+4);
  }
  c.textAlign='left';c.fillText(unit,4,13);
  if(!hasData){c.textAlign='center';c.fillText(empty,(left+right)/2,(top+bottom)/2);return;}
  c.save();c.beginPath();c.rect(left,top,right-left,bottom-top);c.clip();
  traces.forEach((trace,i)=>{
    c.strokeStyle=trace.color??colors[i%colors.length];c.setLineDash(trace.dash??[]);c.lineWidth=2;c.beginPath();let previous=null;
    for(const [t,v] of trace.points){
      if(t<start||t>end||!Number.isFinite(v)){previous=null;continue;}
      if(previous===null||t-previous>.6)c.moveTo(x(t),y(v));else c.lineTo(x(t),y(v));
      previous=t;
    }
    c.stroke();
  });
  c.restore();
}
