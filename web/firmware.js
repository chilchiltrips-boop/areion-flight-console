import {active, copyReport, node, put} from './analysis-common.js';

const supportedVersions=['3.1.0','3.2.0'];
const labels=['Flight controller','FC firmware','Compatible firmware','Link protocol','Loop target','PWM outputs','PPM input'];

export function mount(root){
  root.classList.add('ac-surface');
  root.innerHTML='<section class="ac-box"><h3>Version information</h3><dl class="ac-details"></dl><p class="ac-compat"></p><p class="ac-sub">Upload with Arduino IDE. Disconnect LiPo before flashing.</p><div class="ac-actions"><button data-read disabled>Read kit information</button><button disabled title="Firmware uploading is unavailable in this release.">Flash · unavailable</button><button data-copy>Copy diagnostics</button></div><div class="ac-note" role="status"></div></section>';
  const details=root.querySelector('dl');
  const values=labels.map(label=>{
    const value=node('dd','—');
    details.append(node('dt',label),value);
    return value;
  });
  const compat=root.querySelector('.ac-compat'), note=root.querySelector('.ac-note');
  const read=root.querySelector('[data-read]');
  let ctx=null, busy=false, generation=0;
  root.querySelector('[data-copy]').onclick=()=>ctx && copyReport(ctx,note);
  read.onclick=async()=>{
    if(!ctx || busy || ctx.replay || ctx.state!=='connected')return;
    const request=++generation;
    busy=true;
    read.disabled=true;
    put(note,'Reading kit information…');
    try{
      const info=await ctx.link.readGroup(125);
      if(request===generation)put(note,'Received firmware '+info[0]+'.');
    }catch(error){
      if(request===generation)put(note,error.message || 'Could not read kit information.');
    }finally{
      if(request===generation){busy=false;update(ctx);}
    }
  };
  function update(next){
    if(!next)return;
    if(ctx && (ctx.model!==next.model || ctx.state!==next.state || ctx.link!==next.link)){
      generation++; busy=false; note.replaceChildren();
    }
    ctx=next;
    read.disabled=busy || ctx.replay || ctx.state!=='connected' || !ctx.link?.readGroup;
    const info=active(ctx)?ctx.group(125):null;
    const entries=['Areion FC A1',info?.[0] || '—',supportedVersions.join(' / '),'2',info?info[1]+' Hz':'—',info?info[7]+' Hz · '+info[8]+' bits':'—',info?'GPIO '+info[2]:'—'];
    entries.forEach((value,index)=>put(values[index],value));
    const match=supportedVersions.includes(info?.[0]);
    put(compat,!info?'Waiting for the kit firmware version.':ctx.replay?'Version reported in this recording.':match?'Compatible with this console.':'Firmware version differs from the supported releases.');
    compat.dataset.state=!info?'Waiting':match?'Live':'Stale';
  }
  return {update,reset(){generation++;busy=false;ctx=null;read.disabled=true;note.replaceChildren();}};
}
