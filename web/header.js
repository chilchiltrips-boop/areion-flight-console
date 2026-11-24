import {mountNotifications} from './header-notifications.js';
import {GrantedPorts} from './ports.js';
import {browserAccess} from './browser-access.js';
import {DEFAULT_AP_URL, findApGateway} from './wifi.js';

const ROUTES = [
  ['welcome', 'Welcome'], ['assembly', 'Assembly'], ['flight', 'Flight Data'], ['configuration', 'Configuration'],
  ['system', 'System'], ['scopes', 'Scopes'], ['firmware', 'Firmware']
];
const OPEN = new Set(['opening', 'handshake', 'connected', 'stale']);
const BUSY = new Set(['opening', 'handshake']);

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
  return '<button type="button" class="nav" data-route="'+route+'" id="'+route+'-tab" title="'+label+'" aria-label="'+label+'">'+
    '<img src="./assets/console/nav-'+route+'.svg" alt=""><span>'+label+'</span></button>';
}

export function mountHeader(root, {connect, disconnect, stop, notice = () => {}, apSupported = false, apDefault = DEFAULT_AP_URL, access = browserAccess(window), apOnly = false, retryOffline = () => {}}) {
  root.classList.add('console-mast');
  root.innerHTML = `
    <div class="console-toolbar">
      <div class="identity" aria-label="Areion FC A1"><strong>AREION</strong><span>FC A1</span></div>
      <div class="page-picker">
        <button type="button" id="pages-menu" title="Console pages" aria-label="Console pages" aria-expanded="false" aria-controls="console-pages">
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
        </button>
        <nav aria-label="Console pages" id="console-pages">${ROUTES.map(navMarkup).join('')}</nav>
      </div>
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
        <input type="url" id="header-ap" aria-label="Kit WebSocket address" title="Kit WebSocket address" aria-describedby="hardware-hint" spellcheck="false" autocomplete="off" hidden>
        <button type="button" id="find-ap" aria-label="Find kit" title="Find kit" hidden><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></svg><span>Find kit</span></button>
        <button type="button" class="primary" id="connect">Connect</button>
        <button type="button" id="disconnect" aria-label="Disconnect the kit" title="Disconnect the kit" disabled>×</button>
      </div>
      <div class="kit-state"><span id="link-state" role="status">OFFLINE</span><span id="top-arm"><span class="arm-label">ARM UNKNOWN</span><span class="arm-short" aria-hidden="true">ARM ?</span></span></div>
      <button id="header-stop" type="button" aria-label="Disarm / stop" title="Disarm / stop" disabled><span aria-hidden="true">■</span><span class="disarm-word"> DISARM /</span> STOP</button>
      <div class="header-notifications"></div>
    </div>`;

  const find = selector => root.querySelector(selector);
  const primary = find('#connect'), cancel = find('#disconnect'), halt = find('#header-stop');
  const routePill = find('#link-state'), armPill = find('#top-arm'), transport = find('#header-transport');
  if (apOnly) {
    transport.querySelector('option[value="usb"]').remove();
    transport.value='ap';
  }
  const menu = find('#header-port-menu'), endpoint = find('#header-port'), usbWrap = find('.port-wrap');
  const apAddress = find('#header-ap'), addPort = find('.add-port');
  const options = find('.port-options'), empty = find('.port-empty'), meter = find('.traffic-meter');
  const scan = find('#find-ap'), pages = find('.page-picker'), pagesToggle = find('#pages-menu');
  const traffic = new TrafficMeter();
  let storage;
  try { storage = localStorage; } catch { /* Private mode can restrict storage. */ }
  const release = document.querySelector('meta[name="areion-core"]')?.content || '';
  const notifications = mountNotifications(find('.header-notifications'), {release, storage, retry:retryOffline});
  const catalog = new GrantedPorts(access.serial, storage, drawPorts);
  let state = 'offline', pending = false, stopping = false, attempt = 0, lastCtx = null, activeEndpoint = null;
  let flashing=false;
  let pendingPort = null, titleUpdatedAt = -Infinity;
  let lastArmStatus = '', scanMessage = '', probe = null;
  let offline = {state:'preparing', detail:'Preparing offline files.'};
  const apIssue = access.apIssue || (!apSupported ? 'This kit needs browser AP firmware with WebSocket support.' : '');
  const buttons = new Map();
  apAddress.value = apDefault;
  if (apSupported) {
    try { apAddress.value = storage?.getItem('areion.ap.endpoint.v1') || apDefault; } catch {}
  }
  function setOffline(value) {
    offline = value;
    notifications.setOffline(value);
    drawState();
  }

  function setPages(open, restoreFocus = false) {
    pages.classList.toggle('is-open', open);
    pagesToggle.setAttribute('aria-expanded', String(open));
    if (open) (find('.nav.active') || find('.nav')).focus({preventScroll:true});
    else if (restoreFocus) pagesToggle.focus({preventScroll:true});
  }
  pagesToggle.addEventListener('click', () => setPages(!pages.classList.contains('is-open')));
  pages.addEventListener('click', event => {
    if (pages.classList.contains('is-open') && event.target.closest('[data-route]')) setPages(false, true);
  });
  pages.addEventListener('keydown', event => {
    if (event.key === 'Escape' && pages.classList.contains('is-open')) { event.preventDefault(); setPages(false, true); }
  });
  pages.addEventListener('focusout', event => {
    if (event.relatedTarget && !pages.contains(event.relatedTarget) && pages.classList.contains('is-open')) setPages(false);
  });

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
    for (const {port, label, key, remembered} of choices) {
      let button = buttons.get(port);
      if (!button) {
        button = document.createElement('button');
        button.type = 'button'; button.setAttribute('role', 'menuitemradio');
        button.addEventListener('click', () => selectFromMenu(port));
        buttons.set(port, button); options.append(button);
      }
      button.disabled = false;
      button.setAttribute('aria-checked', String(catalog.selected === port));
      write(button, label + (key ? ' · ' + key : '') + (remembered ? ' · Last connected' : ''));
      button.title = button.textContent;
    }
    empty.hidden = Boolean(choices.length);
    empty.textContent = catalog.serial ? 'No granted USB ports' : 'Web Serial is unavailable in this browser';
    const selected = choices.find(choice => choice.port === catalog.selected);
    const label = selected?.label || 'USB ports';
    write(endpoint.firstElementChild, label);
    endpoint.title = selected ? [label, selected.key, selected.remembered && 'Last connected'].filter(Boolean).join(' · ') : 'Choose a USB port';
    endpoint.setAttribute('aria-label', selected ? 'Choose USB port · ' + label : 'Choose USB port');
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
  const closeOutside = event => {
    if (!usbWrap.contains(event.target)) closeMenu();
    if (pages.classList.contains('is-open') && !pages.contains(event.target)) setPages(false);
  };
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
      lastArmStatus = arm;
      write(armPill.firstElementChild, arm);
      const compactArm = {'ARM LOCKED · SETUP':'LOCKED', 'ARM UNAVAILABLE · SETUP':'NO SETUP', 'ARMED · DISARM REQUIRED':'ARMED', 'ARM UNKNOWN':'ARM ?'};
      write(armPill.lastElementChild, compactArm[arm] || arm);
      armPill.title = arm;
      armPill.setAttribute('aria-label', arm);
      armPill.dataset.armed = String(arm.startsWith('ARMED'));
    }
    write(primary, flashing ? 'Flashing…' : busy ? 'Connecting…' : live || state === 'stale' ? 'Reconnect' : 'Connect');
    const issue = ap ? apIssue : access.usbIssue;
    primary.disabled = flashing || busy || !!probe || !!issue;
    cancel.disabled = flashing || (!open && !pending && !probe);
    halt.disabled = stopping || !['connected','stale'].includes(state) || replay;
    transport.disabled = flashing || open || pending;
    endpoint.disabled = flashing || open || pending || !!access.usbIssue;
    apAddress.disabled = flashing || open || pending || !!probe || !!apIssue;
    scan.hidden = !ap;
    scan.disabled = flashing || open || pending || !!probe || !!apIssue;
    const scanLabel = probe ? 'Finding…' : 'Find kit';
    write(scan.lastElementChild, scanLabel);
    scan.setAttribute('aria-label', scanLabel);
    usbWrap.hidden = ap; apAddress.hidden = !ap;
    const linkHint = issue || (ap && !open ? scanMessage || 'Join the kit in Wi-Fi settings, then find it or connect.' : '');
    const offlineIssue = ['unavailable','failed','update'].includes(offline.state);
    notifications.setConnection(linkHint, !!issue || (!!scanMessage && !probe),
      access.embedded && !!(issue || offlineIssue));
    if (primary.title !== (issue || '')) primary.title = issue || '';
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

  async function begin(originalPort=null, forFirmware=false) {
    if (primary.disabled) return;
    const token = ++attempt, mode = transport.value;
    const reconnect = state === 'connected' || state === 'stale';
    pending = true; drawState();
    try {
      let target;
      if (mode === 'usb') {
        // The permission picker must be requested synchronously from this click.
        const selected = forFirmware ? (catalog.ports.includes(originalPort) ? originalPort : null) : catalog.selected;
        target = selected || await catalog.choose();
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
    if (probe) { probe.abort(); return; }
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
  scan.addEventListener('click', async () => {
    if (scan.disabled) return;
    const job = new AbortController();
    probe = job;
    scanMessage = 'Looking for the Areion gateway…';
    drawState();
    try {
      const address = await findApGateway(apAddress.value.trim() || apDefault, {signal:job.signal, fallback:apDefault});
      if (!job.signal.aborted) {
        apAddress.value = address;
        scanMessage = 'Areion gateway found. Choose Connect to open the flight-controller link.';
      }
    } catch (error) {
      scanMessage = job.signal.aborted ? '' : 'Gateway not found. ' + error.message;
    } finally {
      probe = null;
      drawState();
    }
  });
  apAddress.addEventListener('input', () => { scanMessage = ''; drawState(); });
  transport.addEventListener('change', () => { probe?.abort(); scanMessage = ''; drawState(); });
  const refresh = () => { if (!document.hidden) void catalog.scan(); };
  document.addEventListener('visibilitychange', refresh);
  window.addEventListener('focus', refresh);
  const poll = setInterval(refresh, 3000);
  drawPorts(); setOffline(offline); void catalog.scan();
  return {
    setOffline,
    get connectionPending() { return pending || !!probe; },
    firmwareBusy(value) { flashing=value; drawState(); },
    chooseFirmwarePort() { transport.value='usb'; drawState(); return catalog.choose(); },
    reconnectFirmwarePort(port) {
      if (flashing || pending || probe || OPEN.has(state)) return;
      transport.value='usb'; drawState(); return begin(port,true);
    },
    get offline() { return offline; },
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
      clearInterval(poll); catalog.destroy(); notifications.destroy();
      window.removeEventListener('focus',refresh);
      document.removeEventListener('visibilitychange', refresh);
      probe?.abort();
      document.removeEventListener('pointerdown', closeOutside);
    }
  };
}
