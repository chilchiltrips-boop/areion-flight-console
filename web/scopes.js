import {node, put, numeric, active, downloadCsv, hookTabs} from './analysis-common.js';
import {scopeHistory, trace, spectrum} from './scope-data.js';

const color=['#62ddc2','#ffbd75','#99baff','#d495f8'];
const curve=(title,group,index)=>({title,group,index});
const def=(title,unit,group,labels,indices)=>({title,unit,curves:labels.map((name,i)=>curve(name,group,indices[i]))});
const motion=[
  def('Gyroscope','°/s',21,['Roll','Pitch','Yaw'],[0,1,2]),def('Accelerometer','g',21,['X','Y','Z'],[3,4,5]),
  def('Roll attitude','°',21,['Accel','Kalman'],[6,8]),def('Pitch attitude','°',21,['Accel','Kalman'],[7,9])
];
const control=['Roll','Pitch','Yaw'].map((axis,i)=>({title:axis+' rate',unit:'°/s',curves:[curve('Measured',21,i),curve('Target',23,7+i)]}));
control.push(def('Motor commands','µs',23,['M1','M2','M3','M4'],[3,4,5,6]));
const modes=['Motion','Control','Spectrum','Receiver'];
const channelNames=['Roll','Pitch','Throttle','Yaw','Auxiliary','Auxiliary','Auxiliary','Auxiliary'];
const charts={
  motion,control,
  spectrum:[def('Accelerometer spectrum','g',21,['X','Y','Z'],[3,4,5]),def('Gyroscope spectrum','°/s',21,['Roll','Pitch','Yaw'],[0,1,2])],
  receiver:[def('Stick channels','µs',22,['CH1','CH2','CH3','CH4'],[0,1,2,3]),def('Auxiliary channels','µs',22,['CH5','CH6','CH7','CH8'],[4,5,6,7])]
};

function makeChart(definition) {
  const panel=node('section',null,'ac-plot'), header=node('header'), legend=node('div',null,'ac-legend'), plot=node('canvas');
  plot.setAttribute('aria-label',definition.title+' in '+definition.unit);
  plot.setAttribute('role','img');
  header.append(node('h3',definition.title),node('span',definition.unit));panel.append(header,plot,legend);
  const hidden=new Set(), buttons=[];
  for(const [index,c] of definition.curves.entries()){
    const button=node('button',c.title);
    button.type='button';button.style.setProperty('--series',color[index]);button.setAttribute('aria-pressed','true');
    button.addEventListener('click',()=>{ if(hidden.has(index)) hidden.delete(index);else hidden.add(index);button.setAttribute('aria-pressed',String(!hidden.has(index)));lastDraw?.(); });
    buttons.push(button);legend.append(button);
  }
  let lastDraw, pointer, pendingPaint = false;
  function repaint(){
    if(pendingPaint)return;
    pendingPaint=true;
    requestAnimationFrame(()=>{pendingPaint=false;lastDraw?.();});
  }
  plot.addEventListener('pointermove',event=>{const bounds=plot.getBoundingClientRect();pointer=[event.clientX-bounds.left,event.clientY-bounds.top];repaint();});
  plot.addEventListener('pointerleave',()=>{pointer=null;repaint();});
  function draw(series,axis,message=''){
    lastDraw=()=>draw(series,axis,message);
    const width=plot.clientWidth,height=plot.clientHeight;
    if(!width||!height) return;
    const dpr=Math.min(3,devicePixelRatio||1), w=Math.round(width*dpr), h=Math.round(height*dpr);
    if(plot.width!==w || plot.height!==h){plot.width=w;plot.height=h;}
    const g=plot.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,width,height);
    const l=48,r=width-14,t=9,b=height-23;
    let min=Infinity,max=-Infinity;
    for(const [i,segs] of series.entries()){
      let low=Infinity,high=-Infinity,total=0,count=0;
      for(const seg of segs) for(const [,y] of seg) {low=Math.min(low,y);high=Math.max(high,y);total+=y;count++;}
      buttons[i].title=low===Infinity?'Waiting for samples':'Min '+numeric(low)+' · Max '+numeric(high)+' · Mean '+numeric(total/count)+' '+definition.unit;
      if(!hidden.has(i)){min=Math.min(min,low);max=Math.max(max,high);}
    }
    const empty=!Number.isFinite(min);
    if(empty){min=0;max=1;}
    else if(min===max){const pad=Math.max(.01,Math.abs(min)*.02);min-=pad;max+=pad;}
    else{const pad=(max-min)*.08;min-=pad;max+=pad;}
    g.lineWidth=1;g.font='11px system-ui, sans-serif';g.textBaseline='middle';
    const xAt=x=>l+(x-axis.lo)/(axis.hi-axis.lo)*(r-l);
    const yAt=y=>b-(y-min)/(max-min)*(b-t);
    for(let i=0;i<5;i++){
      const x=l+(r-l)*i/4,y=t+(b-t)*i/4;
      g.beginPath();g.strokeStyle='#304451';g.moveTo(l,y);g.lineTo(r,y);g.moveTo(x,t);g.lineTo(x,b);g.stroke();
      g.fillStyle='#b3c7d0';g.textAlign='right';
      if(!empty)g.fillText(Number((max-(max-min)*i/4).toPrecision(3)).toString(),l-5,y);
      g.textAlign=i===0?'left':i===4?'right':'center';g.fillText(axis.label(i/4),x,b+13);
    }
    for(const [i,segs] of series.entries()){
      if(hidden.has(i))continue;
      g.strokeStyle=g.fillStyle=color[i];g.lineWidth=1.7;
      g.beginPath();
      for(const line of segs){
        if(line.length===1){g.fillRect(xAt(line[0][0])-1,yAt(line[0][1])-1,2.5,2.5);continue;}
        line.forEach(([x,y],idx)=>{ if(idx)g.lineTo(xAt(x),yAt(y));else g.moveTo(xAt(x),yAt(y)); });
      }
      g.stroke();
    }
    let nearest, distance=20;
    if(pointer && !empty){
      for(const [i,segs] of series.entries()){
        if(hidden.has(i))continue;
        for(const seg of segs)for(const [x,y] of seg){
          const px=xAt(x),py=yAt(y),d=Math.hypot(pointer[0]-px,pointer[1]-py);
          if(d<distance){distance=d;nearest={i,x,y,px,py};}
        }
      }
    }
    if(nearest){
      const {i,x,y,px,py}=nearest;
      g.strokeStyle='#8ca5b4';g.setLineDash([3,3]);g.beginPath();g.moveTo(px,t);g.lineTo(px,b);g.stroke();g.setLineDash([]);
      g.fillStyle=color[i];g.beginPath();g.arc(px,py,3,0,2*Math.PI);g.fill();
      const fraction=(x-axis.lo)/(axis.hi-axis.lo), text=definition.curves[i].title+'  '+numeric(y)+' '+definition.unit+'  ·  '+axis.label(fraction);
      g.font='12px system-ui';g.textAlign='left';const size=Math.min(g.measureText(text).width+10,r-l), boxX=Math.max(l,Math.min(px+8,r-size)),boxY=py<t+24?py+7:py-23;
      g.fillStyle='#11212d';g.fillRect(boxX,boxY,size,19);g.fillStyle='#f4faf9';g.fillText(text,boxX+5,boxY+10,size-8);
    }
    if(empty){g.fillStyle='#b3c7d0';g.textAlign='center';g.font='13px system-ui, sans-serif';g.fillText(message||'Waiting for telemetry',(l+r)/2,(t+b)/2,Math.max(10,r-l-8));}
  }
  return {panel,draw};
}

function channelMonitor(target,read,raw,ctx) {
  const inputs=read(122,500), settings=read(134), modes=read(7), calibration=read(132);
  let values=ctx.snapshot?.channels;
  if(raw){
    const packet=read(131,500);
    values=packet?.[9] && packet[10]<(read(112)?.[0]??250) && packet[8]>=4 && packet[8]<=8 ? packet.slice(0,packet[8]):null;
  }
  const cells=target.querySelectorAll('tr[data-channel]');
  for(const [i,row] of Array.from(cells).entries()){
    const slots=settings?.slice(2,6);
    let title=raw?(slots?channelNames[slots.indexOf(i+1)]||'Auxiliary':'—'):channelNames[i];
    const value=values?.[i],valid=Number.isFinite(value)&&value>=900&&value<=2100;
    if(modes && (raw || i>=4 || inputs?.[0]>0) && i+1===modes[0]){
      const mode=valid?['Angle','Rate / Acro'][modes[value<1500?4:5]]:null;
      title=mode?'Mode · '+mode:'Flight mode';
    }
    const [role,bar,live,limits] = Array.from(row.cells).slice(1);
    put(role,title); put(live, valid?value+' µs':'—');
    bar.firstChild.style.setProperty('--val',valid?((value-900)/12)+'%':'0%');
    put(limits,raw && calibration?calibration.slice(4*i,4*i+3).join(' / ')+' · '+(calibration[4*i+3]?'rev':'normal'):'—');
  }
}

export function mount(root) {
  root.classList.add('ac-surface');
  root.innerHTML='<div class="ac-toolbar"><div class="ac-tabs" data-top></div><div class="ac-actions"><label>Window <select aria-label="Scope time window"><option>5</option><option selected>15</option><option>30</option></select> s</label><button data-freeze>Freeze</button><button data-export>Export session CSV</button></div></div><div class="ac-rx-tabs ac-tabs"></div><div class="ac-grid"></div><div class="ac-scope-health"></div><p class="ac-note" aria-live="polite"></p>';
  const top=root.querySelector('[data-top]'),grid=root.querySelector('.ac-grid'),sub=root.querySelector('.ac-rx-tabs'),note=root.querySelector('.ac-note'),window=root.querySelector('select'),freeze=root.querySelector('[data-freeze]'),save=root.querySelector('[data-export]');
  const health=root.querySelector('.ac-scope-health');
  const flags=['Link','IMU','Input','Output'].map(title=>{const flag=node('span');health.append(flag);return [title,flag];});
  function addTab(parent,key,title){const b=node('button',title);b.dataset.tab=key;parent.append(b);}
  for(const title of modes)addTab(top,title.toLowerCase(),title);
  for(const [key,title] of [['accepted','Accepted channels'],['raw','Raw PPM'],['history','Channel history']])addTab(sub,key,title);
  let mode='motion',rx='accepted',held=null,panels=[],ctx=null,renderKey='',previousClock=-1,lastMessage='';
  const setTab=hookTabs(top,k=>{mode=k;build();}),setRx=hookTabs(sub,k=>{rx=k;build();});
  function build(){
    grid.replaceChildren();panels=[];renderKey='';lastMessage='';setTab(mode);setRx(rx);
    sub.hidden=mode!=='receiver';
    if(mode==='receiver' && rx!=='history'){
      const scroller=node('div',null,'ac-table-wrap'),table=node('table',null,'ac-table');
      table.innerHTML='<thead><tr><th>Channel</th><th>Function</th><th>Pulse</th><th>Value</th><th>Min / centre / max</th></tr></thead><tbody></tbody>';
      for(let i=0;i<8;i++){const tr=table.tBodies[0].insertRow();tr.dataset.channel=i;tr.insertCell().textContent='CH'+(i+1);tr.insertCell();tr.insertCell().append(node('i',null,'ac-bar'));tr.insertCell();tr.insertCell();}
      scroller.append(table);grid.append(scroller);
    }else for(const definition of charts[mode]){const c=makeChart(definition);panels.push(c);grid.append(c.panel);}
    if(ctx) update(ctx);
  }
  function update(next) {
    if(previousClock>next.clock && !held)renderKey='';
    previousClock=next.clock;ctx=next;
    const data=held||ctx, seconds=Number(window.value);
    const records=data.rows;
    const ss=data.snapshot?.health||{};
    const states=[{label:data.replay?'Recording':data.state,level:active(data)?'good':'idle'},ss.sensor,ss.input,ss.output];
    for(const [i,[title,flag]] of flags.entries()){
      const state=states[i],show=i===0||active(data);
      put(flag,title+' · '+(show?(state?.label||'Waiting'):'Offline'));
      flag.dataset.level=show?(state?.level||'idle'):'idle';
    }
    freeze.disabled=!held&&(!records.length||!active(data));save.disabled=!ctx.rows.length;
    put(freeze,held?'Resume':'Freeze');freeze.setAttribute('aria-pressed',String(Boolean(held)));
    if(mode==='receiver'&&rx!=='history'){
      channelMonitor(grid,data.group,rx==='raw',data);
      put(note,held?'Frozen':rx==='raw'?'Physical PPM · streamed by the controller during setup':(data.snapshot?.input.label||'Waiting for receiver'));
      return;
    }
    const sig=[Math.round(data.clock/100),seconds,records.length,records.at(-1)?.at,data.state,grid.clientWidth].join(':');
    if(renderKey===sig)return;renderKey=sig;
    const groups=scopeHistory(active(data)?records:[],data.clock,seconds,data.group(112));
    let axis={lo:data.clock-seconds*1000,hi:data.clock,label:k=>Number(((k-1)*seconds).toFixed(1))+' s'},fft=null;
    if(mode==='spectrum'){
      fft=spectrum(groups.get(21),data.clock,data.group(125)?.[0]);
      if (!data.snapshot?.imu) fft={message:'Waiting for current IMU telemetry'};
      const max=fft.fs?fft.fs/2:1;axis={lo:0,hi:max,label:k=>fft.fs?Number((max*k).toFixed(2))+' Hz':''};
    }
    for(const [i,definition] of charts[mode].entries()){
      const dataSeries=definition.curves.map(c=>fft?(fft.bins?[fft.bins[c.index]]:[]):trace(groups.get(c.group),c.index));
      panels[i].draw(dataSeries,axis,fft?.message||(!active(data)?'Offline':'Waiting for telemetry'));
    }
    const parts=[held?'Frozen':data.replay?'Recording':active(data)?'Live':'Offline'];
    if(fft?.fs)parts.push(fft.n+' samples',fft.fs.toFixed(2)+' Hz telemetry','Δf '+(fft.fs/fft.n).toFixed(2)+' Hz');
    put(note,lastMessage||parts.join(' · '));
  }
  window.onchange=()=>{renderKey='';if(ctx)update(ctx);};
  freeze.onclick=()=>{
    if(!ctx)return;
    if(held)held=null;
    else {
      const groups=new Map(ctx.model.frames),clock=ctx.clock;
      const idx=firstRecentRow(ctx.rows,clock-31000);
      held={...ctx,clock,rows:ctx.rows.slice(idx),group:(id,age=Infinity)=>{const r=groups.get(id);return r&&r.at<=clock&&clock-r.at<=age?r.values:null;}};
    }
    renderKey='';update(ctx);
  };
  save.onclick=()=>{try{downloadCsv(ctx);}catch(e){lastMessage=e.message;put(note,lastMessage);}};
  build();
  return {show(route){if(Object.hasOwn(charts,route)) mode=route;build();},update,reset(){held=null;ctx=null;renderKey='';previousClock=-1;}};
}
function firstRecentRow(rows,start){let lo=0,hi=rows.length;while(lo<hi){const i=(lo+hi)>>>1;if(rows[i].at<start)lo=i+1;else hi=i;}return lo;}
