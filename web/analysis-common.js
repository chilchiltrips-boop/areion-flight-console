import {serialize} from './records.js';

export function node(tag, text, cls) {
  const el=document.createElement(tag);
  if(text!=null) el.textContent=text;
  if(cls) el.className=cls;
  return el;
}
export const put=(el,text)=>{ if(el.textContent!==String(text)) el.textContent=text; };
export const numeric=v=>typeof v==='number' && Number.isFinite(v) ? Number(v.toPrecision(6)).toString() : v==null ? '—' : String(v);
export const active=ctx=>ctx?.state==='connected'||Boolean(ctx?.replay);
export function downloadCsv(ctx) {
  const url=URL.createObjectURL(new Blob([serialize(ctx.rows)],{type:'text/csv;charset=utf-8'}));
  const link=node('a');link.href=url;link.download='areion-telemetry.csv';
  document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export function diagnostics(ctx) {
  const groups={};
  for(const [id,row] of ctx.model.frames){
    if (!row || row.at>ctx.clock) continue;
    groups[id]={values:row.values,age_s:Math.round(ctx.clock-row.at)/1000};
  }
  const connected=!ctx.replay && ctx.state==='connected';
  return {
    app:'Areion Flight Console Web', protocol:2, source:ctx.replay?'recording':ctx.path?.toLowerCase() || 'usb',
    state:ctx.state, connected, port:ctx.replay?null:ctx.portLabel || null,
    host_session:connected?ctx.link?.session ?? null:null,
    fc_session:connected?ctx.link?.fcSession ?? null:null,
    link_frames:connected&&ctx.link?.stats?{tx:ctx.link.stats.sent,rx:ctx.link.stats.received}:null,
    received_packets:ctx.packetCount ?? ctx.rows.length, retained_packets:ctx.rows.length,
    groups, events:ctx.events.slice(-30)
  };
}
export async function copyReport(ctx, output) {
  const text=JSON.stringify(diagnostics(ctx),null,2);
  try {
    await navigator.clipboard.writeText(text);
    output.replaceChildren(document.createTextNode('Diagnostics copied.'));
  } catch {
    const box=node('textarea');
    box.setAttribute('aria-label','Diagnostics to copy');box.readOnly=true;box.value=text;
    output.replaceChildren(box);box.select();
  }
}
export function hookTabs(root,change) {
  const buttons=Array.from(root.querySelectorAll('button[data-tab]'));
  for(const button of buttons) button.addEventListener('click',()=>change(button.dataset.tab));
  return selected=>{for(const button of buttons) button.setAttribute('aria-pressed',String(button.dataset.tab===selected));};
}
