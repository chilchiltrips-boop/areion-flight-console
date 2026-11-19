const get = id => document.getElementById(id);
const titles = {welcome:'Welcome', flight:'Flight Data',record:'Recordings',configuration:'Configuration',system:'System',scopes:'Scopes',firmware:'Firmware'};
const loaders = {
  configuration: () => import('./configuration.js'),
  system: () => import('./system.js'),
  scopes: () => import('./scopes.js'),
  firmware: () => import('./firmware.js'),
};
function write(id, label) {
  const el=get(id);
  if(el.textContent!==label)el.textContent=label;
}
function routeName(path) {
  const [name, sub=''] = String(path).replace(/^#\/?/, '').split('/');
  if(name==='recordings')return ['record',''];
  return Object.hasOwn(titles,name) ? [name, sub] : ['welcome',''];
}
function mark(el, active) {
  el.classList.toggle('active',active);
  if(active)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');
}
export class ConsoleShell {
  constructor({select,toggleUsb,disconnectUsb}) {
    this.select=select;
    this.toggleUsb=toggleUsb;
    this.disconnectUsb=disconnectUsb;
    this.modules=new Map();
    this.pending=new Map();
    this.events=[];
    this.page='';
    this.sub='';
    this.context=null;
    this.lastEvent=null;
    this.homeEvents=-1;
    this.navHandler=()=>this.show(location.hash);
  }
  start(){
    document.addEventListener('click',event=>{
      const el=event.target.closest('[data-route]');
      if(el&&!el.disabled){event.preventDefault();this.navigate(el.dataset.route);}
    });
    get('full-console').addEventListener('click',()=>this.fullConsole());
    get('release-usb').addEventListener('click',async()=>{
      const control=get('release-usb');
      control.disabled=true;
      try{await this.disconnectUsb();}catch(error){write('release-status',error.message || 'USB disconnect failed.');}
      finally{control.disabled=false;}
    });
    window.addEventListener('hashchange',this.navHandler);
    this.show(location.hash);
  }
  navigate(path) {
    const [page,sub]=routeName(path);
    const hash='#'+page+(sub?'/'+sub:'');
    if(location.hash===hash){this.show(hash);return;}
    location.hash=hash;
  }
  show(path){
    const [page,sub]=routeName(path);
    const old=this.page;
    this.page=page;this.sub=sub;
    for(const key of Object.keys(titles))get(key+'-page').hidden=key!==page;
    document.querySelectorAll('.mast .nav[data-route]').forEach(btn=>mark(btn,btn.dataset.route===(page==='record'?'flight':page)));
    get('workspace-heading').hidden=page==='welcome';
    get('flight-subnav').hidden=page!=='flight'&&page!=='record';
    mark(get('live-tab'),page==='flight');mark(get('record-tab'),page==='record');
    write('page-title',titles[page]);
    document.title=page==='welcome'?'Areion Flight Console':titles[page]+' · Areion Flight Console';
    if(old!==page){window.scrollTo(0,0);}
    if(this.modules.has(page))this.modules.get(page).show?.(sub);
    else if(loaders[page]&&!this.pending.has(page))this.load(page);
    this.select(page);
  }
  async load(page){
    const container=get(page+'-page');
    this.pending.set(page,true);container.setAttribute('aria-busy','true');
    try{
      const module=await loaders[page]();
      const pane=module.mount(container);
      this.modules.set(page,pane);
      if(this.page===page){pane.show?.(this.sub);if(this.context)pane.update?.(this.context);}
    }catch(error){
      container.replaceChildren();
      const status=document.createElement('p');status.setAttribute('role','status');status.textContent=titles[page]+' could not open.';
      const retry=document.createElement('button');retry.textContent='Retry';retry.onclick=()=>{container.replaceChildren();this.load(page);};
      container.append(status,retry);console.error(error);
    }finally{this.pending.delete(page);container.removeAttribute('aria-busy');}
  }
  fullConsole(){
    const modal=get('full-dialog');
    write('release-status','');
    this.showUsbOwnership(this.context?.state);
    if(!modal.open)modal.showModal();
  }
  showUsbOwnership(state){
    get('port-in-use').hidden=!['opening','handshake','connected','stale'].includes(state);
  }
  log(message){
    if(this.lastEvent===message)return;
    this.lastEvent=message;this.events.push({time:Date.now(),message});
    if(this.events.length>200)this.events.shift();
  }
  reset(source){for(const pane of this.modules.values())pane.reset?.(source);}
  onPacket(row,source){for(const pane of this.modules.values())pane.onPacket?.(row,source);}
  update(ctx){
    this.context=ctx;
    if(get('full-dialog').open)this.showUsbOwnership(ctx.state);
    const s=ctx.snapshot;
    write('top-arm',s.status?(s.status[0]?'Armed':'Disarmed'):'Arm unknown');
    get('top-arm').dataset.armed=s.status?String(s.status[0]):'';
    this.modules.get(this.page)?.update?.(ctx);
    if(this.page!=='welcome')return;
    const connected=ctx.state==='connected';
    const setup=ctx.group(130);
    const isVerified=setup?.[1]&&!setup[0];
    const report=ctx.group(122,500);
    const chosen=report?.[0]??ctx.group(110)?.[0];
    const reading=ctx.replay||connected;
    const linkLabels={opening:'Opening',handshake:'Connecting',stale:'Link stale',error:'USB error',connected:'Connected',replay:'Replay'};
    write('welcome-link',linkLabels[ctx.state]||'Offline');
    get('welcome-link').dataset.state=ctx.state;
    write('welcome-transport',ctx.replay?'CSV recording':connected?'USB':'—');
    write('welcome-firmware',reading&&s.firmware?String(s.firmware):'—');
    write('welcome-input',reading&&chosen!=null?['PPM','AP','USB'][chosen]||'—':'—');
    write('welcome-setup',reading&&setup?isVerified?'Saved':setup[0]?'In progress':'Incomplete':'—');
    write('welcome-wizard-title',connected&&isVerified?'Edit setup':'Vehicle setup wizard');
    const seq=this.events.at(-1);
    if(this.homeEvents===seq)return;
    this.homeEvents=seq;
    const list=get('welcome-events');
    if(seq){
      list.replaceChildren(...this.events.slice(-3).reverse().map(ev=>{
        const li=document.createElement('li');const stamp=document.createElement('time');
        stamp.dateTime=new Date(ev.time).toISOString();stamp.textContent=new Date(ev.time).toLocaleTimeString([],{hour12:false});
        const label=document.createElement('span');label.textContent=ev.message;li.append(stamp,label);return li;
      }));
    }
  }
}
