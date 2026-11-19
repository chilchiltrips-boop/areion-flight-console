import {active,copyReport,node,put} from './analysis-common.js';

export function mount(root){
  root.classList.add('ac-surface');
  root.innerHTML='<section class="ac-box"><h3>Version information</h3><dl class="ac-details"></dl><p class="ac-compat"></p><p class="ac-sub">Upload with Arduino IDE. Disconnect LiPo before flashing.</p><div class="ac-actions"><button disabled title="This console has no verified firmware uploader.">Flash · unavailable</button><button data-copy>Copy diagnostics</button></div><div class="ac-note" role="status"></div></section>';
  const names=['Flight controller','FC firmware','Desktop console','Compatible firmware','Link protocol','Loop target','PWM outputs','PPM input'];
  const values=names.map(name=>{const dd=node('dd','—');root.querySelector('dl').append(node('dt',name),dd);return dd;});
  const compat=root.querySelector('.ac-compat'),note=root.querySelector('.ac-note');
  let ctx;
  root.querySelector('[data-copy]').onclick=()=>ctx&&copyReport(ctx,note);
  function update(next){
    ctx=next;const info=active(ctx)?ctx.group(125):null;
    const entries=['Areion FC A1',info?.[0]||'—','3.12.3','3.1.0 / 3.2.0','2',info?info[1]+' Hz':'—',info?info[7]+' Hz · '+info[8]+' bits':'—',info?'GPIO '+info[2]:'—'];
    entries.forEach((v,i)=>put(values[i],v));
    const match=['3.1.0','3.2.0'].includes(info?.[0]);
    put(compat,!info?'Waiting for the kit firmware version.':ctx.replay?'Version reported in this recording.':match?'Compatible with this console.':'Firmware version differs from the supported releases.');
    compat.dataset.state=!info?'Waiting':match?'Live':'Stale';
  }
  return {update,reset(){note.replaceChildren();}};
}
