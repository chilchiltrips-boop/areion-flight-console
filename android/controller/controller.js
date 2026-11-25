import {ApSessionPort} from '../../web/ap-session-port.js';
import {CockpitSender, Controls, currentGuard, switchPulse} from '../../web/cockpit-controls.js';
import {saveFlightInput} from '../../web/config-commands.js';
import {Instruments} from '../../web/instruments.js';
import {UsbTelemetry} from '../../web/usb.js';
import {DEFAULT_AP_URL} from '../../web/wifi.js';

const AP = 1;
const canStop = state => state === 'connected' || state === 'stale';

export class ApController {
  constructor({
    makePort = () => new ApSessionPort(DEFAULT_AP_URL),
    nativeAvailable = () => typeof globalThis.AreionNativeSocket === 'function',
    window = globalThis.window, document = globalThis.document
  } = {}) {
    this.window = window;
    this.document = document;
    this.makePort = makePort;
    this.nativeAvailable = nativeAvailable;
    this.controls = new Controls();
    this.model = new Instruments();
    this.listeners = new Set();
    this.recoveryAttempts = [];
    this.link = new UsbTelemetry({
      route: () => 'Android AP transmitter',
      onStatus: update => this.linkChanged(update),
      onData: row => this.receive(row),
      onApInterrupted: previous => this.recover(previous)
    });
    this.sender = new CockpitSender(this.controls, () => this.context(), reason => {
      this.notice(reason);
      if (canStop(this.link.state)) void this.stop().catch(() => {});
    });
    this.onPause = () => this.suspend();
    this.onVisibility = () => { if (document.hidden) this.suspend(); };
    for (const event of ['blur', 'areion-app-pause', 'pagehide']) window?.addEventListener(event, this.onPause);
    document?.addEventListener('visibilitychange', this.onVisibility);
  }

  context() {
    return {state:this.link.state, link:this.link, path:'AP', model:this.model};
  }

  subscribe(render) {
    this.listeners.add(render);
    if (!this.paintTimer) this.paintTimer = setInterval(() => this.emit(), 100);
    render(this.snapshot());
    return () => {
      this.listeners.delete(render);
      if (!this.listeners.size) { clearInterval(this.paintTimer); this.paintTimer = null; }
    };
  }

  emit() {
    if (!this.listeners.size || this.document?.hidden) return;
    const state = this.snapshot();
    for (const render of this.listeners) render(state);
  }

  notice(message) {
    this.message = message;
    this.messageUntil = performance.now() + 4500;
    this.emit();
  }

  receive(row) {
    if (row.group === 122) {
      const old = this.model.frames.get(122)?.values;
      if (old && (old[0] !== row.values[0] || old[7] !== row.values[7])) this.controls.reset();
    }
    this.model.push(row);
  }

  linkChanged({state}) {
    this.message = '';
    if (['opening', 'offline', 'error'].includes(state)) {
      this.sender.stop();
      this.model = new Instruments();
    }
    if (state === 'stale' && this.sender.running) void this.stop().catch(() => {});
    this.emit();
  }

  recover(previous) {
    const eligible = () => !this.destroyed && this.wantConnection && !this.document?.hidden &&
      !this.stopPending && this.link.state === 'error' && !this.link.current && !this.link.closing;
    if (!eligible()) return;
    const now = performance.now();
    this.recoveryAttempts = this.recoveryAttempts.filter(at => now - at < 30000);
    if (this.recoveryAttempts.length >= 2) return;
    clearTimeout(this.recoveryTimer);
    this.recoveryTimer = setTimeout(() => {
      if (!eligible()) return;
      this.recoveryAttempts.push(performance.now());
      // Restore telemetry only after checking the previous kit and boot identity.
      void this.link.connect(this.makePort(), {source:AP, label:'AP Wi-Fi', expected:previous});
    }, 1100);
  }

  canEdit(now = performance.now()) {
    if (this.destroyed || this.document?.hidden || this.saving || this.stopPending) return false;
    if (this.link.state === 'offline' || this.link.state === 'error') return true;
    return Boolean(currentGuard(this.context(), now).route && (!this.sender.running || this.sender.ready));
  }

  snapshot() {
    const now = performance.now(), connection = this.link.state, live = connection === 'connected';
    const g = currentGuard(this.context(), now);
    const telemetry = live ? this.model.snapshot(now) : null;
    const modeSettings = live && this.model.get(7, now, Infinity);
    const selected = live ? (g.input?.[0] ?? this.model.get(110, now, Infinity)?.[0] ?? null) : null;
    const mode = g.status ? (g.status[1] ? 0 : 1) : null;
    const busy = !!(this.saving || this.stopPending || this.disconnecting || this.destroyed);
    let feedback = this.link.message || 'Join the kit Wi-Fi.';
    if (live) {
      if (this.stopPending) feedback = 'Confirming disarm…';
      else if (this.saving) feedback = 'Saving AP input…';
      else if (this.sender.running) feedback = this.sender.ready ? 'Sending controls' : 'Waiting for FC input';
      else if (!g.input || !g.status || !g.setup) feedback = 'Waiting for kit status';
      else if (selected !== AP) feedback = 'Select AP input to control the kit';
      else if (!g.lockClear) feedback = 'Flight setup locked';
      else if (!g.route) feedback = 'Waiting for AP ownership';
      else feedback = 'AP connected';
    }
    return {
      connection, session:this.link.fcSession, armed:g.status?.[0] ?? null, mode, selected,
      modeChannel:modeSettings?.[0] ?? null, received:telemetry?.channels ?? null, imu:telemetry?.imu ?? null,
      sending:this.sender.running, ready:this.sender.ready, senderHz:this.sender.running ? this.sender.rate : 0,
      canEdit:this.canEdit(now), canConnect:!busy && !this.sender.running && !this.link.closing,
      canChooseAp:live && !busy && !this.sender.running && selected != null && selected !== AP &&
        g.status?.[0] === false && g.status[7] === true,
      canSend:!busy && (this.sender.running || g.canStart === true),
      canArm:!busy && Boolean(this.sender.canArm(now)),
      canMode:!busy && this.sender.ready && !!g.ready && mode != null &&
        switchPulse(modeSettings, mode === 0 ? 1 : 0) !== null,
      feedback:this.message && now < this.messageUntil ? this.message : feedback
    };
  }

  async connect() {
    if (!this.snapshot().canConnect) return;
    clearTimeout(this.recoveryTimer);
    this.recoveryAttempts = [];
    if (this.link.current) {
      this.wantConnection = false;
      this.disconnecting = true;
      try { await this.link.disconnect(); }
      finally { this.disconnecting = false; this.emit(); }
      return;
    }
    if (!this.nativeAvailable()) { this.notice('Android AP connection unavailable.'); return; }
    this.wantConnection = true;
    await this.link.connect(this.makePort(), {source:AP, label:'AP Wi-Fi'});
  }

  async chooseAp() {
    if (!this.snapshot().canChooseAp) return;
    const owner = this.link.session, boot = this.link.fcSession;
    const saving = this.saving = {};
    this.message = '';
    this.controls.reset();
    this.emit();
    try {
      await saveFlightInput(this.link, AP, {guard:() => {
        if (this.document?.hidden || this.stopPending || this.saving !== saving || this.link.session !== owner ||
            this.link.fcSession !== boot || this.link.state !== 'connected')
          throw Error('AP input save interrupted. Reconnect to verify.');
      }});
      this.notice('AP input saved and verified');
    } catch (error) { this.notice(error.message); throw error; }
    finally {
      if (this.saving === saving) this.saving = null;
      this.emit();
    }
  }

  async toggleSender() {
    if (this.sender.running) return this.stop();
    if (!this.snapshot().canSend) return;
    try { this.sender.start(); this.message = ''; }
    catch (error) { this.notice(error.message); throw error; }
    this.emit();
  }

  async arm() {
    if (!this.snapshot().canArm) return;
    const owner = this.link.session;
    try {
      await this.sender.arm();
      if (this.sender.running && this.link.session === owner) this.notice('FC armed · verified');
    } catch (error) {
      if (this.sender.running && this.link.session === owner) {
        await this.stop();
        this.notice(error.message);
      }
      throw error;
    }
  }

  setMode(mode) {
    if (![0,1].includes(mode) || !this.snapshot().canMode) return;
    const settings = this.model.get(7, performance.now(), Infinity);
    const pulse = switchPulse(settings, mode);
    if (pulse !== null) this.controls.values[settings[0] - 1] = pulse;
    // Mode shown by the deck comes from subsequent FC status, not this command.
    this.emit();
  }

  stop() {
    if (this.stopPending) return this.stopPending;
    this.sender.stop();
    this.saving = false;
    const owner = this.link.session, boot = this.link.fcSession;
    if (!owner || !canStop(this.link.state)) { this.emit(); return Promise.resolve(false); }
    this.message = '';
    this.stopPending = this.verifyDisarm(owner, boot).finally(() => { this.stopPending = null; this.emit(); });
    this.emit();
    return this.stopPending;
  }

  async verifyDisarm(owner, boot) {
    try {
      const ack = await this.link.action(123, ['DISARM']);
      if (ack?.[0] !== 'DISARMED' || this.link.session !== owner || this.link.fcSession !== boot)
        throw Error('Disarm not acknowledged by this kit.');
      const status = await this.link.readGroup(120);
      if (status?.[0] !== false || this.link.session !== owner || this.link.fcSession !== boot)
        throw Error('Disarmed status not verified.');
      this.notice('FC disarmed · verified');
      return true;
    } catch (error) { this.notice('Disarm unconfirmed · ' + error.message); throw error; }
  }

  suspend() {
    clearTimeout(this.recoveryTimer);
    this.wantConnection = false;
    this.saving = false;
    if (this.sender.running) void this.stop().catch(() => {});
    else this.controls.reset();
    this.emit();
  }

  async destroy() {
    this.destroyed = true;
    this.listeners.clear();
    clearInterval(this.paintTimer);
    this.suspend();
    for (const event of ['blur', 'areion-app-pause', 'pagehide']) this.window?.removeEventListener(event, this.onPause);
    this.document?.removeEventListener('visibilitychange', this.onVisibility);
    if (this.stopPending) await this.stopPending.catch(() => {});
    await this.link.disconnect();
  }
}
