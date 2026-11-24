// Web Serial exposes granted port handles and USB identifiers. OS device paths
// are not exposed to the page, and identical adapters may share identifiers.
const PREFERENCE = 'areion.last-confirmed-usb.v1';
const hex = n => Number.isInteger(n) && n >= 0 && n <= 65535 ? n.toString(16).toUpperCase().padStart(4, '0') : '';

function infoFor(port) {
  try { return port?.getInfo() || {}; } catch { return {}; }
}

export function usbKey(port) {
  const {usbVendorId, usbProductId} = infoFor(port);
  const vendor = hex(usbVendorId), product = hex(usbProductId);
  return vendor && product ? vendor + ':' + product : '';
}

export function usbLabel(port) {
  const key = usbKey(port);
  return key ? 'USB ' + key.slice(5) : 'Serial port';
}

function storedPreference(storage) {
  try {
    const key = storage?.getItem(PREFERENCE) || '';
    return /^[0-9A-F]{4}:[0-9A-F]{4}$/.test(key) ? key : '';
  } catch { return ''; }
}

export class GrantedPorts {
  constructor(serial, storage, changed = () => {}) {
    this.serial = serial;
    this.storage = storage;
    this.changed = changed;
    this.ports = [];
    this.selected = null;
    this.confirmedPort = null;
    this.preferred = storedPreference(storage);
    this.detached = new WeakSet();
    this.ids = new WeakMap();
    this.nextId = 1;
    this.scanRevision = 0;
    this.onDevice = event => {
      const port = event.port || event.target;
      if (port && typeof port.getInfo === 'function') {
        if (event.type === 'disconnect') this.detached.add(port);
        else this.detached.delete(port);
      }
      void this.scan();
    };
    serial?.addEventListener('connect', this.onDevice);
    serial?.addEventListener('disconnect', this.onDevice);
  }

  id(port) {
    if (!this.ids.has(port)) this.ids.set(port, this.nextId++);
    return this.ids.get(port);
  }

  choices() {
    return this.ports.map(port => {
      const label = usbLabel(port);
      const similar = this.ports.filter(other => usbLabel(other) === label);
      const key = usbKey(port);
      const matchesPreference = this.preferred && key === this.preferred &&
        this.ports.filter(other => usbKey(other) === key).length === 1;
      const remembered = port === this.confirmedPort || matchesPreference;
      const shortLabel = similar.length === 1 ? label : label + ' #' + this.id(port);
      return {port, label: shortLabel, key, remembered: Boolean(remembered)};
    });
  }

  async scan() {
    if (!this.serial) return;
    const rev = ++this.scanRevision;
    let granted;
    try { granted = await this.serial.getPorts(); } catch { return; }
    if (rev !== this.scanRevision) return;
    this.ports = granted.filter(p => p.connected !== false && !this.detached.has(p));
    this.ports.forEach(port => this.id(port));
    const matches = this.ports.filter(port => this.preferred && usbKey(port) === this.preferred);
    if (matches.length > 1) {
      this.preferred = '';
      try { this.storage?.removeItem(PREFERENCE); } catch {}
    }
    if (!this.ports.includes(this.selected)) this.selected = null;
    if (!this.selected) {
      if (this.ports.includes(this.confirmedPort)) this.selected = this.confirmedPort;
      else if (this.preferred && matches.length === 1) this.selected = matches[0];
    }
    this.changed();
  }

  select(port) {
    if (!this.ports.includes(port)) return;
    this.selected = port;
    this.changed();
  }

  // Request permission only from an explicit user gesture.
  async choose() {
    if (!this.serial) throw Error('USB needs desktop Chrome or Edge with Web Serial support.');
    const port = await this.serial.requestPort();
    if (!port) return null;
    this.scanRevision++;
    this.detached.delete(port);
    if (!this.ports.includes(port)) this.ports.push(port);
    this.select(port);
    return port;
  }

  remember(port) {
    if (!port) return;
    this.confirmedPort = port;
    this.preferred = usbKey(port);
    // Only keep a cross-session preference if identity is unambiguous at
    // confirmation. In this tab the actual granted handle remains available.
    if (this.ports.filter(p => usbKey(p) === this.preferred).length !== 1) this.preferred = '';
    try {
      if (this.preferred) this.storage?.setItem(PREFERENCE, this.preferred);
      else this.storage?.removeItem(PREFERENCE);
    } catch { /* The in-memory handle remains usable when storage is disabled. */ }
    this.select(port);
  }

  destroy() {
    this.scanRevision++;
    this.serial?.removeEventListener('connect', this.onDevice);
    this.serial?.removeEventListener('disconnect', this.onDevice);
  }
}
