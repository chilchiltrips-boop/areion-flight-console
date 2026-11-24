import {TouchInput, responses} from './touch-input.js';

const sides = ['left', 'right'];
const channels = {throttle: 2, yaw: 3, pitch: 1, roll: 0};
const storageKey = 'areion.android.touch.response.v1';
const fmtAngle = n => Number.isFinite(n) ? Math.round(n) + '°' : '—';

function pad(side, axes) {
  return '<div class="a1-pad" data-pad="' + side + '" role="group" aria-label="' + axes + ' joystick">' +
    '<span class="a1-pad-name">' + axes + '</span>' +
    '<div class="a1-pad-ring"><div class="a1-reticle"></div><div class="a1-knob"></div></div>' +
    '<span class="a1-pad-foot">' + (side === 'left' ? 'Hold throttle' : 'Spring return') + '</span></div>';
}

function channel(name) {
  return '<div class="a1-channel"><small>' + name + '</small><b data-channel="' + name +
    '">—</b><span>µs</span><i data-echo="' + name + '"></i></div>';
}

const deckMarkup = '<header class="a1-deck-head">' +
  '<button type="button" data-deck-action="console" aria-label="Open full console">❮ Console</button>' +
  '<strong class="a1-brand">AREION <small>FC A1</small></strong>' +
  '<span class="a1-clock" aria-label="Flight controller armed time">00:00</span>' +
  '<button type="button" data-deck-action="wifi" aria-label="Open Android Wi-Fi settings">Wi-Fi</button>' +
  '<button type="button" data-deck-action="connect">Connect AP</button>' +
  '<button type="button" data-deck-action="stop">■ STOP</button></header>' +
  '<div class="a1-deck-tools"><span class="a1-arm-state" data-armed="unknown">Offline</span>' +
  '<button type="button" data-deck-action="source" hidden>Use AP input</button>' +
  '<button type="button" data-deck-action="send" disabled>Start sender</button>' +
  '<button type="button" data-deck-action="arm" disabled>ARM</button>' +
  '<button type="button" data-deck-action="mode" disabled>Mode —</button>' +
  '<button type="button" data-deck-action="preset" aria-label="Joystick response">Medium</button>' +
  '<button type="button" data-deck-action="aux" aria-expanded="false">Aux</button></div>' +
  '<div class="a1-axes">' + pad('left','Throttle / Yaw') +
  '<div class="a1-imu"><div class="a1-horizon" aria-hidden="true"><div class="a1-plane"><i></i></div>' +
  '<strong class="a1-wings"></strong></div><small data-fc-pose>Awaiting IMU</small></div>' +
  pad('right','Pitch / Roll') + '</div><footer class="a1-deck-foot">' +
  Object.keys(channels).map(channel).join('') + '<span class="a1-deck-feedback" role="status">Touch preview</span></footer>' +
  '<aside class="a1-aux" aria-label="Auxiliary channels" hidden><header><strong>Auxiliary channels</strong><button type="button" data-deck-action="closeAux">Done</button></header>' +
  [5,6,7,8].map(n=>'<label><span>CH' + n + '</span><input type="range" aria-label="Channel ' + n +
    '" data-auxiliary="' + n + '" min="1000" max="2000" value="1000"><output>1000 µs</output></label>').join('') + '</aside>';

function text(el, value) {
  if (el.textContent !== value) el.textContent = value;
}

export function mountTouchDeck(root, api) {
  const sheet = document.createElement('link');
  sheet.rel = 'stylesheet';
  sheet.href = new URL('./touch-deck.css', import.meta.url).href;
  document.head.append(sheet);
  const deck = document.createElement('section');
  deck.className = 'a1-touch-deck';
  deck.setAttribute('aria-label', 'Touch transmitter');
  deck.innerHTML = deckMarkup;
  root.append(deck);
  root.classList.add('a1-touch-active');
  const launch = document.createElement('button');
  launch.type = 'button';
  launch.textContent = 'Touch deck';
  launch.setAttribute('aria-label','Open touch transmitter');
  root.querySelector('.cockpit-heading > div').append(launch);

  const q = sel => deck.querySelector(sel);
  const actions = Object.fromEntries([...deck.querySelectorAll('[data-deck-action]')].map(el => [el.dataset.deckAction, el]));
  const pads = Object.fromEntries(sides.map(s => [s, q('[data-pad="' + s + '"]')]));
  const rings = Object.fromEntries(sides.map(s => [s,pads[s].querySelector('.a1-pad-ring')]));
  const auxPanel=q('.a1-aux'), auxInputs=[...auxPanel.querySelectorAll('input')];
  const channelLabels = Object.fromEntries(Object.keys(channels).map(n=>[n,q('[data-channel="' + n + '"]')]));
  const echoes = Object.fromEntries(Object.keys(channels).map(n=>[n,q('[data-echo="' + n + '"]')]));
  const feedback = q('.a1-deck-feedback'), armLabel = q('.a1-arm-state');
  const clockLabel = q('.a1-clock'), horizon = q('.a1-horizon'), scene = q('.a1-plane'), pose = q('[data-fc-pose]');
  let stored;
  try { stored = localStorage.getItem(storageKey); } catch {}
  const input = new TouchInput(api.controls,stored);
  actions.wifi.hidden=typeof window.AreionAndroid?.openWifiSettings!=='function';
  let latest = null, raf = 0, stopPending = false, stopGeneration = 0, uiNote = '', noteUntil = 0;
  let armAt = null, elapsed = 0, priorArmed = null, session = null;

  const buzz = kind => { try { window.AreionAndroid?.haptic(kind); } catch {} };
  const visible = () => !deck.hidden && !root.hidden && !document.hidden;
  function readChannels(values,received) {
    for (const [name,idx] of Object.entries(channels)) {
      const n = values?.[idx], back = received?.[idx];
      text(channelLabels[name],Number.isFinite(n) ? String(Math.round(n)) : '—');
      text(echoes[name],Number.isFinite(back) ? 'RX ' + Math.round(back) : '');
    }
  }
  function paintPads() {
    for (const side of sides) {
      const ring = rings[side], pt = input.pointers.get(side);
      if (pt) {
        const rect = pads[side].getBoundingClientRect();
        ring.style.left = (pt.originX - rect.left) + 'px';
        ring.style.top = (pt.originY - rect.top) + 'px';
        ring.style.setProperty('--dx',(pt.x * pt.radius) + 'px');
        ring.style.setProperty('--dy',(-pt.y * pt.radius) + 'px');
      } else if (ring.classList.contains('a1-held')) {
        ring.style.left = ring.style.top = '';
        ring.style.removeProperty('--dx');ring.style.removeProperty('--dy');
      }
      ring.classList.toggle('a1-held',!!pt);
    }
  }
  function releasePads() {
    cancelAnimationFrame(raf);raf = 0;
    const held = [...input.pointers.entries()];
    input.release();
    for (const [side,pt] of held) {
      const pad = pads[side];
      if(pad.hasPointerCapture(pt.id))pad.releasePointerCapture(pt.id);
    }
    paintPads();
  }
  function suspend() {
    auxPanel.hidden=true;actions.aux.setAttribute('aria-expanded','false');
    releasePads();
    api.controls.reset();
    if(visible())readChannels(api.controls.values,null);
  }
  function note(message) {
    uiNote = message;noteUntil = performance.now()+4000;
    text(feedback,message);
  }
  function animate(now) {
    raf = 0;
    if (!visible() || !api.canEdit()) {releasePads();return;}
    input.tick(now);
    paintPads();
    readChannels(api.controls.values,latest?.received);
    if (input.pointers.has('left'))raf = requestAnimationFrame(animate);
  }
  for (const side of sides) {
    const zone = pads[side];
    zone.oncontextmenu = e => e.preventDefault();
    zone.onpointerdown = e => {
      if (!visible() || !auxPanel.hidden || !api.canEdit() || stopPending || (e.pointerType==='mouse' && e.button!==0)) return;
      const rect = zone.getBoundingClientRect();
      const radius = Math.max(22,Math.min(82,Math.min(rect.width,rect.height)*.25));
      if(!input.begin(side,e.pointerId,e.clientX,e.clientY,radius,performance.now()))return;
      e.preventDefault();zone.setPointerCapture(e.pointerId);
      buzz('tick');paintPads();readChannels(api.controls.values,latest?.received);
      if(side==='left'&&!raf)raf=requestAnimationFrame(animate);
    };
    zone.onpointermove = e => {
      if(!visible()||!api.canEdit()||!input.move(side,e.pointerId,e.clientX,e.clientY,performance.now()))return;
      e.preventDefault();paintPads();readChannels(api.controls.values,latest?.received);
    };
    const end = e => {
      if(!input.end(side,e.pointerId,performance.now()))return;
      paintPads();readChannels(api.controls.values,latest?.received);
    };
    zone.onpointerup=end;zone.onpointercancel=end;zone.onlostpointercapture=end;
  }
  async function stop() {
    if(stopPending)return;
    stopPending=true;const attempt=++stopGeneration;
    suspend();buzz('stop');
    const live = latest && !latest.context.replay && ['connected','stale'].includes(latest.context.state);
    note(live ? 'Confirming disarm…' : 'Preview stopped');
    try {
      const verified = await api.stop();
      if(attempt===stopGeneration)note(verified ? 'FC disarmed · verified' : 'Preview stopped');
    } catch(error) {
      if(attempt===stopGeneration)note('Disarm unconfirmed · ' + error.message);
    } finally { if(attempt===stopGeneration)stopPending=false; }
  }
  // A third finger may not generate a click while two pointers hold the pads.
  actions.stop.onpointerdown = e => {
    if(e.pointerType==='mouse'&&e.button!==0)return;
    e.preventDefault();void stop();
  };
  actions.stop.onclick = e => {if(e.detail===0)void stop();}; // keyboard / accessibility
  actions.console.onclick=()=>{suspend();api.leave();deck.hidden=true;root.classList.remove('a1-touch-active');launch.focus();};
  launch.onclick=()=>{suspend();api.leave();api.enter();root.classList.add('a1-touch-active');deck.hidden=false;if(latest)update(latest);};
  actions.connect.onclick=()=>{
    if(latest?.context.state==='connected'){
      actions.console.click();latest.context.navigate('system/connections');
    }else{buzz('tick');api.connect();}
  };
  actions.wifi.onclick=()=>{suspend();api.leave();window.AreionAndroid?.openWifiSettings();};
  actions.aux.onclick=actions.closeAux.onclick=()=>{
    if(input.pointers.size)return;
    auxPanel.hidden=!auxPanel.hidden;
    actions.aux.setAttribute('aria-expanded',String(!auxPanel.hidden));
    buzz('tick');if(latest)update(latest);
  };
  for(const slider of auxInputs)slider.oninput=()=>{
    const ch=Number(slider.dataset.auxiliary);
    if(auxPanel.hidden||slider.disabled||!api.canEdit())return;
    api.controls.values[ch-1]=slider.valueAsNumber;
    text(slider.nextElementSibling,slider.value+' µs');
  };
  actions.send.onclick=()=>{suspend();buzz('tick');api.buttons.send.click();};
  actions.arm.onclick=()=>{
    if(latest?.status?.[0]===true && api.sender.running){void stop();return;}
    releasePads();buzz('confirm');api.buttons.arm.click();
  };
  actions.mode.onclick=()=>{buzz('tick');api.buttons[latest?.mode===0?'rate':'angle'].click();};
  actions.source.onclick=()=>{suspend();buzz('tick');void api.chooseAp();};
  actions.preset.onclick=()=>{
    if(input.pointers.size)return;
    const names=Object.keys(responses);
    input.preset=names[(names.indexOf(input.preset)+1)%names.length];
    try {localStorage.setItem(storageKey,input.preset);}catch{}
    buzz('tick');text(actions.preset,input.preset);
    actions.preset.setAttribute('aria-label','Joystick response '+input.preset);
  };
  function update(state) {
    latest=state;
    if(!visible())return;
    const {context,view,status,received,reason,selected,mode}=state;
    const now=performance.now(),live=context.state==='connected'&&!context.replay;
    const monitor=!['local','preview'].includes(view);
    const boot=context.link?.fcSession??null;
    if(boot!==null && boot!==session){
      armAt=null;elapsed=0;priorArmed=null;session=boot;
      ++stopGeneration;stopPending=false;uiNote='';noteUntil=0;
    }
    const armed=live && status ? status[0] : null;
    if(armed===true && armAt===null){
      if(priorArmed!==true)elapsed=0;
      armAt=now-elapsed;
    }
    if(armAt!==null){
      elapsed=now-armAt;
      if(armed!==true)armAt=null;
    }
    if(armed!==null)priorArmed=armed;
    const secs=Math.floor(elapsed/1000);
    text(clockLabel,String(Math.floor(secs/60)).padStart(2,'0')+':'+String(secs%60).padStart(2,'0'));
    text(armLabel,armed===true?'Armed':armed===false?'Disarmed':context.replay?'Replay':live?'Waiting':'Offline');
    armLabel.dataset.armed=armed==null?'unknown':String(armed);
    text(actions.connect,live?'AP link':context.state==='opening'||context.state==='handshake'?'Connecting…':'Connect AP');
    actions.connect.disabled=(!live&&document.getElementById('connect')?.disabled===true)||api.sender.running;
    actions.source.hidden=!live||selected==null||selected===1;
    actions.source.disabled=api.buttons['save-input'].disabled;
    actions.wifi.disabled=api.sender.running;
    actions.send.disabled=api.buttons.send.disabled;
    text(actions.send,api.sender.running?'Stop sender':'Start sender');
    const canDisarm=armed===true && api.sender.running;
    text(actions.arm,canDisarm?'Disarm':'ARM');
    actions.arm.disabled=(!canDisarm&&api.buttons.arm.disabled)||stopPending;
    const modeAction=mode===0?'rate':'angle';
    actions.mode.disabled=api.buttons[modeAction].disabled;
    text(actions.mode,mode===0?'Angle':mode===1?'Rate / Acro':'Mode —');
    actions.mode.setAttribute('aria-label',mode===0?'Angle mode; switch to Rate / Acro':mode===1?'Rate / Acro mode; switch to Angle':'Flight mode unavailable');
    text(actions.preset,input.preset);
    actions.preset.setAttribute('aria-label','Joystick response '+input.preset);
    const editable=api.canEdit()&&!stopPending;
    if(!editable&&input.pointers.size)releasePads();
    input.synchronize();paintPads();
    for(const pad of Object.values(pads))pad.setAttribute('aria-disabled',String(!editable));
    readChannels(monitor?received:api.controls.values,received);
    if(!auxPanel.hidden){
      const modeChannel=context.group(7)?.[0]??5;
      for(const slider of auxInputs){
        const ch=Number(slider.dataset.auxiliary);
        slider.disabled=!editable||ch===modeChannel;
        const value=(monitor?received:api.controls.values)?.[ch-1];
        if(Number.isFinite(value))slider.value=String(value);
        text(slider.nextElementSibling,ch===modeChannel?'Flight mode':Number.isFinite(value)?Math.round(value)+' µs':'—');
      }
    }
    const imu=context.snapshot.imu;
    horizon.dataset.live=String(!!imu);
    if(imu)scene.style.transform='rotate('+(-imu.roll)+'deg) translateY('+Math.max(-36,Math.min(36,imu.pitch))+'%)';
    else scene.style.transform='';
    text(pose,imu?'R '+fmtAngle(imu.roll)+' · P '+fmtAngle(imu.pitch)+' · Y '+fmtAngle(state.yaw):'Awaiting IMU');
    const headerNotice=document.getElementById('notice');
    const statusText=monitor?(view==='ppm'?'PPM receiver · monitor':reason):
      api.sender.running?(api.sender.ready?(api.sender.rate?Math.round(api.sender.rate)+' Hz · FC ready':'FC ready'):'Qualifying input…'):
      (!live ? 'Touch preview' : 'AP selected · sender off');
    text(feedback,now<noteUntil?uiNote:headerNotice&&!headerNotice.hidden?headerNotice.textContent:statusText);
  }
  return {update,suspend,get showing(){return visible();}};
}
