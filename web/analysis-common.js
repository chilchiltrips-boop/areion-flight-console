import {diagnosticFile} from './diagnostic-report.js';
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
export function downloadCsv(ctx, name='areion-telemetry.csv') {
  const url=URL.createObjectURL(new Blob([serialize(ctx.rows)],{type:'text/csv;charset=utf-8'}));
  const link=node('a');link.href=url;link.download=name;
  document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export function diagnostics(ctx, now=performance.now()) {
  // The model receives live packets between paints; replay uses its playhead.
  const clock=ctx.replay ? ctx.clock : Math.max(ctx.clock,now);
  const groups={};
  for(const [id,row] of ctx.model.frames){
    if (!row || row.at>clock || id===138 || id===139) continue;
    groups[id]={values:row.values,age_s:Math.round(clock-row.at)/1000};
  }
  const connected=!ctx.replay && ctx.state==='connected' && !!ctx.link?.fcSession;
  const calibration=connected ? ctx.sensorReport?.() : null;
  return {
    app:'Areion Flight Console Web', protocol:2, source:ctx.replay?'recording':ctx.path?.toLowerCase() || 'usb',
    state:ctx.state, connected, port:ctx.replay?null:ctx.portLabel || null,
    host_session:connected?ctx.link?.session ?? null:null,
    fc_session:connected?ctx.link?.fcSession ?? null:null,
    link_frames:connected&&ctx.link?.stats?{tx:ctx.link.stats.sent,rx:ctx.link.stats.received}:null,
    ...(!ctx.replay && ctx.link?.lastConnection ? {last_connection:ctx.link.lastConnection} : {}),
    ...(calibration ? {imu_calibration:calibration} : {}),
    received_packets:ctx.packetCount ?? ctx.rows.length, retained_packets:ctx.rows.length,
    ...(ctx.browser ? {browser:ctx.browser} : {}),
    groups, events:ctx.events.slice()
  };
}
export async function copyReport(ctx, output) {
  const file=diagnosticFile(ctx.journal,diagnostics(ctx),'json');
  output.textContent='Preparing the diagnostic history…';
  try {
    if(globalThis.ClipboardItem && navigator.clipboard?.write)
      await navigator.clipboard.write([new ClipboardItem({'text/plain':file})]);
    else await navigator.clipboard.writeText(await (await file).text());
    output.textContent='Full diagnostics copied.';
  } catch {
    const blob=await file;
    const box=node('textarea');box.setAttribute('aria-label','Full diagnostics to copy');
    box.readOnly=true;box.value=await blob.text();
    output.replaceChildren(node('span','Copy the selected report.'),box);box.select();
  }
}
export function hookTabs(root,change) {
  const buttons=Array.from(root.querySelectorAll('button[data-tab]'));
  for(const button of buttons) button.addEventListener('click',()=>change(button.dataset.tab));
  return selected=>{for(const button of buttons) button.setAttribute('aria-pressed',String(button.dataset.tab===selected));};
}
