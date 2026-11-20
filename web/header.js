import {GrantedPorts} from './ports.js';

const ROUTES = [
  ['welcome', 'Welcome'], ['assembly', 'Assembly'], ['flight', 'Flight Data'], ['configuration', 'Configuration'],
  ['system', 'System'], ['scopes', 'Scopes'], ['hitl', 'HITL'], ['firmware', 'Firmware']
];
const OPEN = new Set(['opening', 'handshake', 'connected', 'stale']);
const BUSY = new Set(['opening', 'handshake']);
const AP_DEFAULT = 'ws://192.168.4.1:8081/areion';

function write(element, value) {
  if (element.textContent !== value) element.textContent = value;
}

export class TrafficMeter {
  constructor() { this.reset(); }

  reset() {
    this.count = {tx: 0, rx: 0};
    this.latestRx = -Infinity;
    this.baseline = null;
    this.rates = {tx: null, rx: null};
  }

  add({direction, at = performance.now()}) {
    if (direction !== 'tx' && direction !== 'rx') return;
    this.count[direction]++;
    if (direction === 'rx') this.latestRx = at;
  }

  sample(now, live) {
    if (!live) {
      this.baseline = null;
      this.rates = {tx: null, rx: null};
    } else if (!this.baseline || this.baseline.now > now) {
      this.baseline = {now, ...this.count};
      this.rates = {tx: 0, rx: 0};
    } else if (now - this.baseline.now >= 500) {
      const seconds = (now - this.baseline.now) / 1000;
      this.rates = {
        tx: (this.count.tx - this.baseline.tx) / seconds,
        rx: (this.count.rx - this.baseline.rx) / seconds
      };
      this.baseline = {now, ...this.count};
    }
    return {...this.rates, fresh: live && now >= this.latestRx && now - this.latestRx < 500};
  }
}

export function armCaption(status, setup, connected) {
  if (!connected) return 'ARM UNKNOWN';
  if (status?.[0] === true) return setup && !setup[0] && setup[1] ? 'ARMED' : 'ARMED · DISARM REQUIRED';
  if (setup?.[0]) return 'ARM LOCKED · SETUP';
  if (!setup || !setup[1]) return 'ARM UNAVAILABLE · SETUP';
  return status?.[0] === false ? 'DISARMED' : 'ARM UNKNOWN';
}

function meterMarkup(direction) {
  return '<div class="traffic-row" data-traffic="'+direction+'"><span>'+direction.toUpperCase()+
    '</span><span class="traffic-bars" aria-hidden="true">'+ '<i></i>'.repeat(6)+
    '</span><output aria-live="off">—</output></div>';
}

function navMarkup([route, label]) {
  const disabled = route === 'hitl' ? ' disabled title="Hardware-in-the-loop is unavailable in this release"' : '';
  return '<button type="button" class="nav" data-route="'+route+'" id="'+route+'-tab"'+disabled+
    '><img src="./assets/console/nav-'+route+'.svg" alt="">'+label+'</button>';
}

export function mountHeader(root, {connect, disconnect, stop, notice = () => {}, apSupported = false, apDefault = AP_DEFAULT}) {
  root.classList.add('console-mast');
  root.innerHTML = `
    <div class="top-line"><div class="identity"><strong>AREION</strong><span>FC A1 · Web Console</span></div>
      <div class="head-actions"><span id="link-state" role="status">OFFLINE</span><span id="top-arm">ARM UNKNOWN</span>
        <button id="header-stop" type="button" disabled><span aria-hidden="true">■</span> DISARM / STOP</button>
      </div>
    </div>
    <div class="nav-line"><nav aria-label="Console pages">${ROUTES.map(navMarkup).join('')}</nav>
      <div class="link-controls" aria-label="Kit connection">
        <div class="traffic-meter" role="group" aria-label="Transport frame rates">${meterMarkup('tx')}${meterMarkup('rx')}</div>
        <select id="header-transport" aria-label="Connection transport"><option value="usb">USB</option><option value="ap">AP Wi-Fi</option></select>
        <div class="port-wrap"><button type="button" id="header-port" aria-label="Choose USB port" aria-haspopup="menu" aria-expanded="false" aria-controls="header-port-menu">
          <span>USB ports</span><i aria-hidden="true"></i></button>
          <div id="header-port-menu" class="port-menu" role="menu" aria-label="USB ports" hidden>
            <div class="port-options"></div><p class="port-empty">No granted USB ports</p>
            <button type="button" role="menuitem" class="add-port">Choose a new port…</button>
          </div>
        </div>
        <input type="url" id="header-ap" aria-label="Kit WebSocket address" title="Kit WebSocket address" aria-describedby="header-ap-info" spellcheck="false" autocomplete="off" hidden>
        <button type="button" class="primary" id="connect">Connect</button>
        <button type="button" id="disconnect" aria-label="Disconnect the kit" title="Disconnect the kit" disabled>×</button>
      </div>
    </div>
    <div id="header-ap-info" hidden><span id="ap-offline-status" role="status"></span>
      <span id="ap-firmware-note">Requires WebSocket-enabled kit firmware. Stock 3.2 uses UDP.</span></div>`;

  const find = selector => root.querySelector(selector);
  const primary = find('#connect'), cancel = find('#disconnect'), halt = find('#header-stop');
  const routePill = find('#link-state'), armPill = find('#top-arm'), transport = find('#header-transport');
  const menu = find('#header-port-menu'), endpoint = find('#header-port'), usbWrap = find('.port-wrap');
  const apAddress = find('#header-ap'), apInfo = find('#header-ap-info'), addPort = find('.add-port');
  const options = find('.port-options'), empty = find('.port-empty'), meter = find('.traffic-meter');
  const offlineStatus = find('#ap-offline-status');
  const traffic = new TrafficMeter();
  let storage;
  try { storage = localStorage; } catch { /* Private mode can restrict storage. */ }
  const catalog = new GrantedPorts(navigator.serial, storage, drawPorts);
  let state = 'offline', pending = false, stopping = false, attempt = 0, lastCtx = null, activeEndpoint = null;
  let pendingPort = null, titleUpdatedAt = -Infinity;
  let lastArmStatus = '';
  const buttons = new Map();
  apAddress.value = apDefault;
  if (apSupported) {
    try { apAddress.value = storage?.getItem('areion.ap.endpoint.v1') || apDefault; } catch {}
  }
  if (!apSupported) {
    transport.options[1].title = 'This kit currently supports UDP over AP Wi-Fi.';
    find('#ap-firmware-note').textContent = 'This kit uses UDP for AP Wi-Fi. Connect with USB in this browser.';
  }

  function showOfflineStatus() {
    const ready = document.documentElement.dataset.offlineReady === 'true';
    offlineStatus.hidden = !apSupported;
    offlineStatus.dataset.ready = String(ready);
    write(offlineStatus, ready ? 'Ready for kit Wi-Fi.' : 'Open this page online before joining kit Wi-Fi.');
  }

  function closeMenu(restoreFocus = false) {
    if (menu.hidden) return;
    menu.hidden = true;
    endpoint.setAttribute('aria-expanded', 'false');
    if (restoreFocus) endpoint.focus();
    drawPorts();
  }

  function selectFromMenu(port) {
    catalog.select(port);
    closeMenu(true);
  }

  function drawPorts() {
    const choices = catalog.choices();
    for (const [port, button] of buttons) {
      if (choices.some(choice => choice.port === port)) continue;
      if (menu.hidden) { button.remove(); buttons.delete(port); }
      else button.disabled = true;
    }
    for (const {port, label, remembered} of choices) {
      let button = buttons.get(port);
      if (!button) {
        button = document.createElement('button');
        button.type = 'button'; button.setAttribute('role', 'menuitemradio');
        button.addEventListener('click', () => selectFromMenu(port));
        buttons.set(port, button); options.append(button);
      }
      button.disabled = false;
      button.setAttribute('aria-checked', String(catalog.selected === port));
      write(button, label + (remembered ? ' · Last connected' : ''));
      button.title = label;
    }
    empty.hidden = Boolean(choices.length);
    empty.textContent = catalog.serial ? 'No granted USB ports' : 'Web Serial is unavailable in this browser';
    const selected = choices.find(choice => choice.port === catalog.selected);
    const label = selected?.label || 'USB ports';
    write(endpoint.firstElementChild, label);
    endpoint.title = selected ? label + (selected.remembered ? ' · Last connected' : '') : 'Choose a USB port';
    addPort.disabled = !catalog.serial;
  }

  function openMenu() {
    if (endpoint.disabled) return;
    if (!menu.hidden) { closeMenu(); return; }
    drawPorts(); menu.style.setProperty('--ports-menu-top', Math.round(endpoint.getBoundingClientRect().bottom + 5)+'px');
    menu.hidden = false; endpoint.setAttribute('aria-expanded', 'true');
    void catalog.scan();
    const first = menu.querySelector('[aria-checked="true"]:enabled') || menu.querySelector('button:enabled');
    first?.focus();
  }

  endpoint.addEventListener('click', openMenu);
  addPort.addEventListener('click', async () => {
    closeMenu(true);
    try { await catalog.choose(); }
    catch (error) { if (error.name !== 'NotFoundError') notice(error.message); }
  });
  const closeOutside = event => { if (!usbWrap.contains(event.target)) closeMenu(); };
  document.addEventListener('pointerdown', closeOutside);
  usbWrap.addEventListener('focusout', event => {
    if (event.relatedTarget && !usbWrap.contains(event.relatedTarget)) closeMenu();
  });
  usbWrap.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); closeMenu(true); return; }
    if (menu.hidden && ['ArrowDown','ArrowUp'].includes(event.key)) { event.preventDefault(); openMenu(); return; }
    if (menu.hidden || !['ArrowDown','ArrowUp','Home','End'].includes(event.key)) return;
    event.preventDefault();
    const items = Array.from(menu.querySelectorAll('button:enabled'));
    if (!items.length) return;
    const index = items.indexOf(document.activeElement);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 :
      (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[next].focus();
  });

  function drawState() {
    const live = state === 'connected', busy = pending || BUSY.has(state);
    const open = OPEN.has(state), ap = transport.value === 'ap';
    const replay = !!lastCtx?.replay;
    const label = replay && !open ? 'REPLAY' :
      ({connected: ap ? 'AP LINK' : 'USB LINK', opening:'CONNECTING…', handshake:'HANDSHAKE…', stale:'LINK STALE', error:'LINK ERROR'}[state] || (pending ? 'CONNECTING…' : 'OFFLINE'));
    write(routePill, label);
    routePill.dataset.tone = live ? 'good' : busy || state === 'stale' ? 'warn' : state === 'error' ? 'bad' : 'idle';
    const arm = armCaption(lastCtx?.snapshot?.status, lastCtx?.group?.(130,500), live && !replay);
    if (lastArmStatus !== arm) {
      lastArmStatus = arm; write(armPill, arm);
      armPill.dataset.armed = String(arm.startsWith('ARMED'));
    }
    write(primary, busy ? 'Connecting…' : live || state === 'stale' ? 'Reconnect' : 'Connect');
    primary.disabled = busy || (ap && !apSupported);
    cancel.disabled = !open && !pending;
    halt.disabled = stopping || !['connected','stale'].includes(state) || replay;
    transport.disabled = open || pending;
    endpoint.disabled = open || pending;
    apAddress.disabled = open || pending || !apSupported;
    usbWrap.hidden = ap; apAddress.hidden = !ap; apInfo.hidden = !ap || live;
    if (ap || endpoint.disabled) closeMenu();
  }

  function paintRates(now) {
    const live = (state === 'connected' || state === 'stale') && !lastCtx?.replay;
    const rates = traffic.sample(now, live);
    for (const direction of ['tx','rx']) {
      const row = meter.querySelector('[data-traffic="'+direction+'"]'), rate = rates[direction];
      const blocks = rate > 0 ? Math.min(6, Math.max(1, Math.ceil(2 * Math.log10(rate + 1)))) : 0;
      const nodes = row.querySelectorAll('.traffic-bars i');
      for (let i = 0; i < nodes.length; i++) nodes[i].classList.toggle('lit', i < blocks);
      write(row.querySelector('output'), rate === null ? '—' : Math.round(rate)+'/s');
    }
    meter.dataset.fresh = String(rates.fresh);
    if (now - titleUpdatedAt >= 1000) {
      meter.title = 'Link frames · TX '+traffic.count.tx+' sent · RX '+traffic.count.rx+' received';
      titleUpdatedAt = now;
    }
  }

  async function begin() {
    if (primary.disabled) return;
    const token = ++attempt, mode = transport.value;
    const reconnect = state === 'connected' || state === 'stale';
    pending = true; drawState();
    try {
      let target;
      if (mode === 'usb') {
        // The permission picker must be requested synchronously from this click.
        target = catalog.selected || await catalog.choose();
        if (!target || token !== attempt) return;
        pendingPort = target;
      } else {
        target = apAddress.value.trim();
        if (!target) { apAddress.focus(); throw Error('Enter the kit WebSocket address.'); }
      }
      if (reconnect) await disconnect();
      if (token !== attempt) return;
      traffic.reset();
      activeEndpoint = target;
      await connect(mode, target);
    } catch (error) {
      if (token === attempt && error.name !== 'NotFoundError') notice(error.message || 'Connection failed.');
    } finally {
      if (token === attempt) { pending = false; drawState(); }
    }
  }

  async function end() {
    if (cancel.disabled) return;
    attempt++; pending = false; pendingPort = null; activeEndpoint = null;
    try { await disconnect(); }
    catch (error) { notice(error.message || 'Disconnect failed.'); }
    finally { drawState(); }
  }

  primary.addEventListener('click', begin);
  cancel.addEventListener('click', end);
  halt.addEventListener('click', async () => {
    if (halt.disabled || stopping) return;
    stopping = true; drawState();
    try { await stop(); }
    catch (error) { notice(error.message || 'Stop command failed.'); }
    finally { stopping = false; drawState(); }
  });
  transport.addEventListener('change', drawState);
  const refresh = () => { if (!document.hidden) void catalog.scan(); };
  document.addEventListener('visibilitychange', refresh);
  document.addEventListener('areion-offline-ready', showOfflineStatus);
  showOfflineStatus();
  window.addEventListener('focus', refresh);
  const poll = setInterval(refresh, 3000);
  drawPorts(); drawState(); void catalog.scan();
  return {
    get mode() { return transport.value; },
    get endpointLabel() {
      if (transport.value === 'ap') return apAddress.value.trim();
      return catalog.choices().find(choice => choice.port === catalog.selected)?.label || '';
    },
    traffic: sample => traffic.add(sample),
    confirmed(port) {
      if (transport.value === 'usb') catalog.remember(port || pendingPort);
      else if (typeof activeEndpoint === 'string') {
        try { storage?.setItem('areion.ap.endpoint.v1', activeEndpoint); } catch {}
      }
    },
    update(ctx) {
      lastCtx = ctx;
      state = ctx.replay ? 'offline' : ctx.state;
      drawState(); paintRates(performance.now());
    },
    toggle() { return OPEN.has(state) ? end() : begin(); },
    destroy() {
      clearInterval(poll); catalog.destroy();
      window.removeEventListener('focus',refresh);
      document.removeEventListener('visibilitychange', refresh);
      document.removeEventListener('areion-offline-ready', showOfflineStatus);
      document.removeEventListener('pointerdown', closeOutside);
    }
  };
}
