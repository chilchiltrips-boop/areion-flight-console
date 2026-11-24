import {diagnosticFile} from './diagnostic-report.js';
import {active, copyReport, diagnostics, downloadBlob, downloadCsv, hookTabs, node, numeric, put} from './analysis-common.js';
import {fields} from './telemetry-fields.js';

const cached=new Set([2,3,4,6,7,110,112,121,125,132,134]);
function label(name){
  const gain=/^([PID])(?:Rate|Angle)(Roll|Pitch|Yaw)$/.exec(name);
  return gain ? gain[1]+' · '+gain[2] : name.replaceAll('_',' ').replace(/([a-z0-9])([A-Z])/g,'$1 $2');
}

export function connectionReadout(ctx) {
  const report=ctx.model.frames.get(120);
  const wifi=ctx.group(121);
  const path=ctx.path || 'USB';
  const endpoint=ctx.replay?'—':ctx.portLabel || '—';
  const age=report && ctx.clock>=report.at ? Math.round(ctx.clock-report.at)+' ms ago' : '—';
  return [
    ['Transport',ctx.replay?'CSV playback':path==='AP'?'AP Wi-Fi':'USB serial'],
    ['Link',ctx.state],
    ['Endpoint',endpoint],
    ['USB baud',!ctx.replay && path==='USB'?'115200':'—'],
    ['Flight input',ctx.snapshot.source || '—'],
    ['Latest FC report',age],
    ['Received packets',(ctx.packetCount ?? ctx.rows.length).toLocaleString()],
    ['FC access point',wifi?(wifi[0]?wifi[1]+':'+wifi[2]+' · UDP':'Offline'):'—'],
    ...(ctx.browser ? [
      ['Window',ctx.browser.embedded ? 'Embedded console' : 'Standalone console'],
      ['Offline console',ctx.browser.offline.detail],
      ['USB access',ctx.browser.usb || 'Available on request'],
      ['AP gateway',ctx.browser.ap || 'Find or connect from the header']
    ] : [])
  ];
}

export function mount(root){
  root.classList.add('ac-surface');
  root.innerHTML=`
    <nav class="ac-sectionbar ac-tabs" data-section aria-label="System sections">
      <button data-tab="values">Live values</button><button data-tab="connections">Connection</button><button data-tab="diagnostics">Diagnostics</button>
    </nav>
    <h1 class="ac-title">System</h1>
    <div class="ac-toolbar">
        <div class="ac-filter"><input type="search" aria-label="Filter telemetry fields" placeholder="Filter fields"><span data-count></span></div>
        <div class="ac-actions"><button data-csv>Telemetry CSV</button><button data-copy>Copy all diagnostics</button><button data-history-csv>Export diagnostics CSV</button></div>
    </div>
    <div data-live>
      <nav class="ac-tabs ac-subtabs" data-logtabs aria-label="Live values views">
        <button data-tab="values">All values</button><button data-tab="events">Event log</button>
      </nav>
      <div class="ac-table-wrap ac-values" data-values>
        <table class="ac-table"><thead><tr><th>Section</th><th>Field</th><th>Value</th><th>Age</th><th>State</th></tr></thead><tbody></tbody></table>
      </div>
      <div class="ac-box" data-events hidden><ol class="ac-log" aria-label="Session events"></ol></div>
    </div>
    <section class="ac-box" data-connections hidden>
      <h2>Kit communication</h2><dl class="ac-details"></dl>
      <div class="ac-actions"><button data-connect>Connect</button></div>
    </section>
    <section data-diagnostic-pane hidden>
      <div class="ac-box"><h2>Diagnostic history</h2><p data-history-count></p>
        <h3>Last ESC result</h3><p data-last-esc></p>
        <h3>Latest reported issue</h3><p data-last-issue></p>
        <div class="ac-actions"><button data-clear>Clear history</button><span data-clear-confirm hidden>Clear diagnostic records saved in this browser? <button data-clear-yes>Clear records</button> <button data-clear-no>Cancel</button></span></div>
      </div>
      <div class="ac-box"><h3>Recent results</h3><ol class="ac-log" data-result-log></ol></div>
    </section>
    <div class="ac-note" role="status"></div>`;
  const find=selector=>root.querySelector(selector);
  const livePane=find('[data-live]'), valuesPane=find('[data-values]'), eventsPane=find('[data-events]'), connectionsPane=find('[data-connections]'), body=find('tbody');
  const info=find('.ac-note'), search=find('input'), count=find('[data-count]'), csv=find('[data-csv]'), connect=find('[data-connect]'), events=find('.ac-log');
  const historyPane=find('[data-diagnostic-pane]'), clearConfirm=find('[data-clear-confirm]');
  let historyKey='',lastHistoryRead=-Infinity,reading=false,working=false;
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
  const details=root.querySelector('dl'), detailCells=new Map();
  const setSection=hookTabs(find('[data-section]'),route);
  const setDetail=hookTabs(find('[data-logtabs]'),route);
  function route(name){if(ctx?.navigate)ctx.navigate('system/'+name);else select(name);}
  function select(name){
    view=['values','events','connections','diagnostics'].includes(name)?name:'values';
    const connection=view==='connections';
    const history=view==='diagnostics';
    setSection(history?'diagnostics':connection?'connections':'values');setDetail(view);
    historyPane.hidden=!history;clearConfirm.hidden=true;lastHistoryRead=-Infinity;
    find('h1').textContent=history?'Diagnostics':connection?'Connection':'System';
    livePane.hidden=connection||history; valuesPane.hidden=view!=='values'; eventsPane.hidden=view!=='events'; connectionsPane.hidden=!connection;
    find('.ac-filter').hidden=view!=='values';
    if(ctx)update(ctx);
  }
  function filter(){
    const q=search.value.trim().toLowerCase();visible=[];
    for(const row of rows){row.tr.hidden=!row.search.includes(q);if(!row.tr.hidden)visible.push(row);}
    put(count,visible.length+' fields');if(ctx)update(ctx);
  }
  search.oninput=filter;
  const reportTask=fn=>async()=>{
    if(!ctx||working)return;
    working=true;
    try{await fn();}catch(error){put(info,'Diagnostics: '+error.message);}finally{working=false;}
  };
  find('[data-copy]').onclick=reportTask(()=>copyReport(ctx,info));
  find('[data-history-csv]').onclick=reportTask(async()=>{
    put(info,'Preparing diagnostics CSV…');
    const file=await diagnosticFile(ctx.journal,diagnostics(ctx),'csv');
    await downloadBlob(file,'areion-diagnostics-'+new Date().toISOString().replaceAll(':','-')+'.csv');
    put(info,'Diagnostics CSV prepared.');
  });
  find('[data-clear]').onclick=()=>{clearConfirm.hidden=false;};
  find('[data-clear-no]').onclick=()=>{clearConfirm.hidden=true;};
  find('[data-clear-yes]').onclick=reportTask(async()=>{
    await ctx.journal.clear();ctx.clearDiagnosticEvents();clearConfirm.hidden=true;put(info,'Diagnostic history cleared.');update(ctx);
  });
  function updateHistory(){
    const journal=ctx.journal;
    if(!journal)return;
    const now=performance.now();
    if(!reading && now-lastHistoryRead>=3000){
      reading=true;lastHistoryRead=now;journal.refresh().catch(error=>put(info,error.message)).finally(()=>{reading=false;});
    }
    const summary=journal.summary(),where=r=>[r.source?.toUpperCase(),r.page,r.step].filter(Boolean).join(' · ');
    const describe=r=>[where(r),r.name,r.detail].filter(Boolean).join(' · ');
    const issue=summary.issue,esc=summary.esc;
    put(find('[data-last-esc]'),esc?new Date(esc.time).toLocaleString()+' · '+describe(esc):'No ESC result recorded.');
    find('[data-last-issue]').dataset.severity=issue?.status??'';

    put(find('[data-history-count]'),summary.count.toLocaleString()+' records · '+(summary.storage?'Temporary memory · '+summary.storage:'Saved in this browser')+(summary.lost?' · '+summary.lost+' records lost':''));
    put(find('[data-last-issue]'),issue?new Date(issue.time).toLocaleString()+' · '+describe(issue):'No issue recorded.');
    const signature=JSON.stringify(summary.recent.map(r=>[r.time,r.kind,r.name,r.status,r.detail]));
    if(historyKey===signature)return;
    historyKey=signature;
    const log=find('[data-result-log]');log.replaceChildren();
    for(const entry of summary.recent){
      const li=node('li');li.dataset.severity=entry.status;li.append(node('time',new Date(entry.time).toLocaleTimeString()),node('span',entry.status.toUpperCase()+' · '+describe(entry)));log.append(li);
    }
    if(!log.children.length)log.append(node('li','No results recorded yet.'));
  }
  connect.onclick=()=>ctx?.toggleUsb?.();
  csv.onclick=async()=>{if(!ctx)return;try{await downloadCsv(ctx);}catch(e){put(info,e.message);}};
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
    }else if(view==='diagnostics'){updateHistory();}else {
      for(const [name,value] of connectionReadout(ctx)){
        let cell=detailCells.get(name);
        if(!cell){cell=node('dd');details.append(node('dt',name),cell);detailCells.set(name,cell);}
        put(cell,value);
      }
      const open=['opening','handshake','connected','stale'].includes(ctx.state);
      put(connect,open?'Disconnect':'Connect '+(ctx.path || 'USB'));
      connect.disabled=ctx.replay || (!open && !!(ctx.path === 'AP' ? ctx.browser?.ap : ctx.browser?.usb));
    }
  }
  filter();select('values');
  return {show:select,update,reset(){eventsKey=null;info.replaceChildren();}};
}
