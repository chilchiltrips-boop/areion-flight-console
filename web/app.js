import {UsbTelemetry} from './usb.js';
import {WifiPort, DEFAULT_AP_URL} from './wifi.js';
import {Instruments} from './instruments.js';
import {mountHeader} from './header.js';
import {mountFlightExtra} from './flight-extra.js';
import {ConsoleShell} from './shell.js';
import {saveFlightInput} from './config-commands.js';
import {MAX_CSV_BYTES, parseCsv, serialize} from './records.js';

const $ = id => document.getElementById(id);
const elapsed = ms => Math.floor(ms / 60000) + ':' + String(Math.floor(ms / 1000) % 60).padStart(2,'0');
const openStates = new Set(['opening','handshake','connected','stale']);
const empty = new Instruments();
let live = new Instruments();
let recording = [], packetCount = 0;
let replay = null, state = 'offline', page = 'welcome', path = 'USB';
let nextPaint = 0, lastShellUpdate = -Infinity;
let connecting = false, stopPending = null;
const flightExtra = mountFlightExtra($('flight-page'));

function text(el, value) {
  if (el.textContent !== value) el.textContent = value;
}
function notice(message) {
  $('notice').hidden = !message;
  text($('notice'), message || '');
  if (message) log(message);
}
function log(message) {
  if (!message) return;
  shell.log(message);
  text($('session-status'),message);
}
const shell = new ConsoleShell({
  select(next) {
    if (page === 'flight' && next !== page) stopSender('Left Flight Data');
    page = next;
    lastShellUpdate = -Infinity;
    render();
  }
});
const view = route => shell.navigate(route);
function dropReplay() {
  if (replay) shell.reset(path.toLowerCase());
  replay = null;
  $('replay').hidden = true;
}
const link = new UsbTelemetry({
  onTraffic(sample) { header.traffic(sample); },
  onPort(port) { header.confirmed(port); },
  onStatus(update) {
    state = update.state;
    lastShellUpdate = -Infinity;
    log(update.message || state);
    if (state === 'opening') {
      connecting = true;
      flightExtra.transmitter.reset();
    }
    if (state === 'handshake') {
      live = new Instruments();
      shell.reset(path.toLowerCase());
    }
    if (state === 'connected' && connecting) {
      connecting = false;
      live = new Instruments();
      recording = [];
      packetCount = 0;
      if (path === 'AP') header.confirmed();
    }
    if (['offline','error','stale'].includes(state)) {
      if (state === 'stale') stopSender('Connection stale');
      else flightExtra.cancelSender('Disconnected');
      shell.modules.get('configuration')?.suspend?.();
      flightExtra.transmitter.reset();
    }
    notice(['error','stale'].includes(state) ? update.message : '');
    render();
  },
  onData(row) {
    live.push(row);
    recording.push(row);
    packetCount++;
    shell.onPacket(row,path.toLowerCase());
    if (recording.length > 5000) recording.splice(0,250);
  }
});

function stopKit() {
  if (stopPending) return stopPending;
  if (replay || !['connected','stale'].includes(state)) {
    return Promise.reject(Error('Connect the kit to verify DISARM.'));
  }
  flightExtra.cancelSender('DISARM / STOP');
  shell.modules.get('configuration')?.suspend?.({emergency:true});
  const session = link.session;
  stopPending = (async () => {
    const ack = await link.action(123,['DISARM']);
    if (ack?.[0] !== 'DISARMED' || link.session !== session) throw Error('DISARM was not acknowledged by this kit.');
    const status = await link.readGroup(120);
    if (status?.[0] !== false || link.session !== session) throw Error('Disarmed status could not be verified.');
    log('Kit disarmed · verified');
  })().finally(() => { stopPending = null; });
  return stopPending;
}
function stopSender(reason) {
  if (flightExtra.cancelSender(reason)) void stopKit().catch(error => notice(error.message));
}
function leaveControls() {
  stopSender('Controls released');
  shell.modules.get('configuration')?.suspend?.();
}
window.addEventListener('blur', leaveControls);
window.addEventListener('pagehide', leaveControls);
document.addEventListener('visibilitychange', () => { if (document.hidden) leaveControls(); });
async function disconnect() {
  if (flightExtra.running) {
    try { await stopKit(); } catch (error) { log(error.message); }
  }
  const pending = shell.modules.get('configuration')?.suspend?.();
  if (pending) await Promise.resolve(pending).catch(error => log(error.message));
  await link.disconnect();
}
async function connect(mode, endpoint) {
  if (openStates.has(state)) return;
  dropReplay();
  notice('');
  path = mode === 'ap' ? 'AP' : 'USB';
  if (mode === 'ap') {
    await link.connect(new WifiPort(endpoint || DEFAULT_AP_URL),{source:1,label:'AP Wi-Fi'});
  } else {
    await link.connect(endpoint);
  }
}
const header = mountHeader(document.querySelector('.mast'),{
  connect,disconnect,stop:stopKit,notice,apSupported:true,apDefault:DEFAULT_AP_URL
});

function render() {
  const clock = replay ? replay.position : performance.now();
  const model = replay ? replay.model : state === 'connected' ? live : empty;
  const snapshot = model.snapshot(clock);
  const count = replay ? replay.index : packetCount;
  const route = openStates.has(state) ? path : header.mode.toUpperCase();
  text($('fw'),snapshot.firmware || '—');
  text($('transport'),replay ? 'CSV recording' : route === 'USB' ? 'USB serial' : 'AP Wi-Fi');
  text($('frames'),count.toLocaleString()+' packets');
  $('export').disabled = !recording.length;
  text($('record-detail'),recording.length ? recording.length.toLocaleString()+' packets available to export.' : 'No telemetry recorded.');
  $('import').disabled = openStates.has(state);
  $('import').title = $('import').disabled ? 'Disconnect the kit to open a recording.' : 'Open a telemetry recording';
  const now = performance.now(), refresh = now - lastShellUpdate >= 150;
  if (!refresh && page !== 'flight') return;
  const ctx = {model,clock,state:replay?'replay':state,replay:!!replay,snapshot,events:shell.events,link,
    path:route,mode:header.mode,portLabel:header.endpointLabel,packetCount:count,
    get rows(){return replay ? replay.rows.slice(0,replay.index) : recording;},
    group:(id,maxAge=Infinity)=>model.get(id,clock,maxAge),
    checkTransmitter:()=>flightExtra.transmitter.open(ctx),
    navigate:view,toggleUsb:()=>header.toggle(),openRecording:()=>view('record'),message:log,stopKit,
    saveInput: source => {
      if (flightExtra.running || !link.fcSession || replay || state !== 'connected') throw Error('Stop the sender and connect a disarmed kit to save input.');
      const host=link.session,fc=link.fcSession;
      return saveFlightInput(link,source,{guard(){if (link.session!==host || link.fcSession!==fc || state!=='connected' || page!=='flight') throw Error('Input save interrupted. Read back the kit settings.');}});
    }
  };
  if (refresh) {
    header.update(ctx);
    shell.update(ctx);
    lastShellUpdate = now;
  }
  if (page === 'flight') flightExtra.update(ctx);
  else if (flightExtra.transmitter.isOpen()) flightExtra.transmitter.update(ctx);
}

function advance(target,seek=false){
  if(!replay)return;
  if(seek&&target<replay.position){replay.model=new Instruments();replay.index=0;shell.reset('replay');}
  while(replay.index<replay.rows.length&&replay.rows[replay.index].at<=target){
    const row=replay.rows[replay.index++];
    replay.model.push(row);shell.onPacket(row,'replay');
  }
  replay.position=target;
  $('seek').value=String(target);
  text($('play-time'),elapsed(target)+' / '+elapsed(replay.duration));
}
function pause(){
  if(!replay)return;replay.playing=false;text($('play'),'Play');
}
$('import').onclick=()=>$('file').click();
$('file').onchange=async()=>{
  const file=$('file').files[0];$('file').value='';if(!file)return;
  try{
    if(file.size>MAX_CSV_BYTES)throw new Error('Choose a telemetry CSV smaller than 8 MiB.');
    const rows=parseCsv(await file.text());
    if(['opening','handshake','connected','stale'].includes(state))throw new Error('Disconnect the kit to open a recording.');
    replay={rows,model:new Instruments(),index:0,duration:rows.at(-1).at,position:0,playing:false,startedAt:0};
    $('replay').hidden=false;$('seek').max=String(replay.duration);$('play').disabled=replay.duration===0;
    shell.reset('replay');shell.log('Opened recording · '+file.name);pause();advance(0);notice('');view('flight');
  }catch(e){notice(e.message);}
};
$('seek').oninput=()=>{pause();advance(Number($('seek').value),true);render();};
$('play').onclick=()=>{
  if(!replay)return;
  if(replay.playing){pause();return;}
  if(replay.position>=replay.duration)advance(0,true);
  replay.startedAt=performance.now()-replay.position;replay.playing=true;text($('play'),'Pause');
};
$('close-replay').onclick=()=>{dropReplay();render();};
$('export').onclick=()=>{
  try{
    const url=URL.createObjectURL(new Blob([serialize(recording)],{type:'text/csv;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download='areion-telemetry-'+new Date().toISOString().replaceAll(':','-')+'.csv';a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){notice(e.message);}
};
function tick(now){
  if(now>=nextPaint){
    if(replay?.playing){advance(Math.min(now-replay.startedAt,replay.duration));if(replay.position>=replay.duration)pause();}
    render();nextPaint=now+50;
  }
  requestAnimationFrame(tick);
}
shell.start();render();requestAnimationFrame(tick);

if (location.protocol === 'https:' && window.isSecureContext && 'serviceWorker' in navigator) {
  navigator.serviceWorker.register('./offline-worker.js').then(() => navigator.serviceWorker.ready).then(() => {
    document.documentElement.dataset.offlineReady='true';
    document.dispatchEvent(new Event('areion-offline-ready'));
  }).catch(() => { /* USB and online use remain available when caching is disabled. */ });
}
