import {active, copyReport, downloadCsv, hookTabs, node, numeric, put} from './analysis-common.js';
import {fields} from './telemetry-fields.js';

const cached=new Set([2,3,4,6,7,110,112,121,125,132,134]);
const label=name=>name.replaceAll('_',' ').replace(/([a-z0-9])([A-Z])/g,'$1 $2');

export function mount(root){
  root.classList.add('ac-surface');
  root.innerHTML='<div class="ac-toolbar"><div class="ac-tabs"><button data-tab="values">All values</button><button data-tab="events">Event log</button><button data-tab="connections">Connections</button></div><div class="ac-actions"><button data-csv>Export CSV</button><button data-copy>Copy diagnostics</button></div></div><div class="ac-box" data-values><div class="ac-filter"><input type="search" aria-label="Filter telemetry fields" placeholder="Filter group or field"><span data-count></span></div><div class="ac-table-wrap ac-values"><table class="ac-table"><thead><tr><th>Section</th><th>Field</th><th>Value</th><th>Age</th><th>State</th></tr></thead><tbody></tbody></table></div></div><div class="ac-box" data-events hidden><h3>Session events</h3><ol class="ac-log"></ol></div><div class="ac-box" data-connections hidden><h3>Kit communication</h3><dl class="ac-details"></dl><div class="ac-actions"><button data-usb>Connect USB</button><button data-full>Open full console</button></div></div><div class="ac-note" role="status"></div>';
  const valuesPane=root.querySelector('[data-values]'), eventsPane=root.querySelector('[data-events]'), connectionsPane=root.querySelector('[data-connections]'),body=root.querySelector('tbody'),info=root.querySelector('.ac-note'),search=root.querySelector('input'),count=root.querySelector('[data-count]'),csv=root.querySelector('[data-csv]'),usb=root.querySelector('[data-usb]'),events=root.querySelector('.ac-log');
  const rows=[];
  for(const [id,[group,names]] of fields){
    for(const [index,name] of names.entries()){
      const tr=body.insertRow(),section=id+' · '+group,display=label(name);
      tr.insertCell().textContent=section;
      tr.insertCell().textContent=display;
      for(let i=0;i<3;i++)tr.insertCell().textContent='—';
      rows.push({id,index,tr,search:(section+' '+name+' '+display).toLowerCase()});
    }
  }
  let view='values',ctx=null,visible=rows,eventsKey=null;
  const details=['Transport','Link','USB baud','Flight input','Latest FC report','Received packets','FC access point'];
  const values=details.map(name=>{ const value=node('dd','—');root.querySelector('dl').append(node('dt',name),value);return value; });
  const setTab=hookTabs(root.querySelector('.ac-tabs'),select);
  function select(name){
    view=['values','events','connections'].includes(name)?name:'values';
    setTab(view);valuesPane.hidden=view!=='values';eventsPane.hidden=view!=='events';connectionsPane.hidden=view!=='connections';
    if(ctx)update(ctx);
  }
  function filter(){
    const q=search.value.trim().toLowerCase();visible=[];
    for(const row of rows){row.tr.hidden=!row.search.includes(q);if(!row.tr.hidden)visible.push(row);}
    put(count,visible.length+' fields');if(ctx)update(ctx);
  }
  search.oninput=filter;
  root.querySelector('[data-copy]').onclick=()=>ctx&&copyReport(ctx,info);
  root.querySelector('[data-full]').onclick=()=>ctx?.fullConsole?.();
  usb.onclick=()=>ctx?.toggleUsb?.();
  csv.onclick=()=>{if(!ctx)return;try{downloadCsv(ctx);}catch(e){put(info,e.message);}};
  function update(next){
    ctx=next;csv.disabled=!ctx.rows.length;
    if(view==='values'){
      const time=ctx.clock;
      for(const {id,index,tr} of visible){
        const row=ctx.model.frames.get(id),age=row&&(time-row.at),has=row && age>=0;
        const state=!has?'Waiting':!active(ctx)?'Offline':cached.has(id)?'Snapshot':age<=500?'Live':'Stale';
        put(tr.cells[2],has?numeric(row.values[index]):'—');
        put(tr.cells[3],has?(age/1000).toFixed(1)+' s':'—');
        put(tr.cells[4],state);
        if(tr.cells[4].dataset.state!==state)tr.cells[4].dataset.state=state;
      }
    }else if(view==='events'){
      const last=ctx.events.at(-1),key=ctx.events.length+'|'+last?.time+'|'+last?.message;
      if(eventsKey!==key){
        eventsKey=key;events.replaceChildren();
        for(const event of ctx.events.slice(-200).reverse()){const li=node('li');li.append(node('time',new Date(event.time).toLocaleTimeString()),node('span',event.message));events.append(li);}
        if(!events.children.length)events.append(node('li','No session events.'));
      }
    }else {
      const row=ctx.model.frames.get(120),link=ctx.group(121);
      const online=['opening','handshake','connected','stale'].includes(ctx.state);
      const data=[ctx.replay?'CSV playback':'USB serial',ctx.state,ctx.replay?'—':'115200',ctx.snapshot.source||'—',row?Math.max(0,ctx.clock-row.at).toFixed(0)+' ms ago':'—',ctx.rows.length,link?(link[0]?link[1]+':'+link[2]:'Offline'):'—'];
      data.forEach((v,i)=>put(values[i],v));put(usb,online?'Disconnect USB':'Connect USB');usb.disabled=ctx.replay;
    }
  }
  filter();select('values');
  return {show:select,update,reset(){eventsKey=null;info.replaceChildren();}};
}
