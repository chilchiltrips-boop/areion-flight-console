// A browser port for the optional on-kit WebSocket gateway. The inner payloads
// are ordinary Areion Link v2 frames and use the same owner and ACK as USB.
export const DEFAULT_AP_URL = 'ws://192.168.4.1:8081/areion';
const POLL = 0x50, FRAME = 0x46, REPLY = 0x41;
const MAX_FRAME = 1552, POLL_MS = 20, MAX_ROUND_TRIP_MS = 200;
const SUBPROTOCOL = 'areion-link-v2';

export function apUrl(endpoint = DEFAULT_AP_URL) {
  let text = String(endpoint).trim();
  if (!text) text = DEFAULT_AP_URL;
  if (!text.includes('://')) text = 'ws://' + text;
  const url = new URL(text);
  if (!['ws:', 'wss:'].includes(url.protocol) || url.username || url.password || url.search || url.hash)
    throw new Error('Enter the kit WebSocket address.');
  const privateAddress = /^(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)/.test(url.hostname)
    && /^(?:\d+\.){3}\d+$/.test(url.hostname);
  if (url.protocol === 'ws:' && !privateAddress && !url.hostname.endsWith('.local'))
    throw new Error('Use the kit’s private IP or .local name for AP Wi-Fi.');
  if (url.pathname === '/') url.pathname = '/areion';
  if (!url.port && url.protocol === 'ws:') url.port = '8081';
  return url.toString();
}

function header(kind, value, length = 5) {
  const bytes = new Uint8Array(length);
  bytes[0] = kind;
  new DataView(bytes.buffer).setUint32(1, value);
  return bytes;
}

export class WifiPort {
  constructor(endpoint = DEFAULT_AP_URL) {
    this.url = apUrl(endpoint);
    this.socket = null;
    this.readable = this.writable = null;
    this.readController = null;
    this.pending = null;
    this.serial = 0;
    this.credit = null;
  }

  async open() {
    if (this.socket) throw Error('AP Wi-Fi is already open.');
    const errorHint = 'Join the kit Wi-Fi and allow local network access. The kit needs the browser AP firmware on port 8081.';
    let socket;
    try { socket = new WebSocket(this.url, SUBPROTOCOL); }
    catch { throw Error(errorHint); }
    this.socket = socket;
    socket.binaryType = 'arraybuffer';
    this.readable = new ReadableStream({
      start: controller => { this.readController = controller; },
      cancel: () => { this.readController = null; }
    }, {highWaterMark: 16});
    this.writable = new WritableStream({write: bytes => this.write(bytes)});
    return new Promise((resolve, reject) => {
      let ready = false;
      const fail = message => {
        if (socket !== this.socket) return;
        this.shutdown(new Error(message));
        if (!ready) reject(new Error(message));
      };
      this.cancelOpen = () => fail('AP connection cancelled.');
      const poll = () => {
        if (socket.readyState !== WebSocket.OPEN) return;
        const now = performance.now();
        if (this.pending) {
          if (now - this.pending.at > MAX_ROUND_TRIP_MS && ready) fail('AP telemetry link expired. Reconnect the kit.');
          return;
        }
        if (socket.bufferedAmount > MAX_FRAME) return fail('AP Wi-Fi is congested. Reconnect the kit.');
        this.serial = (this.serial + 1) >>> 0;
        this.pending = {id:this.serial, at:now};
        try { socket.send(header(POLL, this.serial)); } catch { fail('AP Wi-Fi disconnected.'); }
      };
      this.openTimer = setTimeout(() => fail(errorHint), 8000);
      socket.onopen = () => {
        if (socket.protocol !== SUBPROTOCOL) return fail(errorHint);
        poll();
        this.pollTimer = setInterval(poll, POLL_MS);
      };
      socket.onmessage = ({data}) => {
        if (socket !== this.socket) return;
        if (!(data instanceof ArrayBuffer) || data.byteLength < 9 || data.byteLength > 9 + MAX_FRAME * 4)
          return fail('Invalid browser AP response.');
        const view = new DataView(data), pending = this.pending;
        if (view.getUint8(0) !== REPLY || !pending || view.getUint32(1) !== pending.id)
          return fail('Unexpected browser AP response.');
        const now = performance.now();
        if (now - pending.at > MAX_ROUND_TRIP_MS) return fail('AP telemetry arrived too late. Reconnect the kit.');
        this.credit = {value:view.getUint32(5), at:pending.at};
        this.pending = null;
        if (!ready) { ready = true; clearTimeout(this.openTimer); this.cancelOpen = null; resolve(); }
        if (data.byteLength > 9 && this.readController) {
          if (this.readController.desiredSize <= 0) return fail('AP telemetry could not be consumed in time.');
          this.readController.enqueue(new Uint8Array(data, 9));
        }
      };
      socket.onerror = () => fail(errorHint);
      socket.onclose = () => fail(ready ? 'AP Wi-Fi disconnected.' : errorHint);
    });
  }

  write(bytes) {
    const ws = this.socket, credit = this.credit;
    if (!ws || ws.readyState !== WebSocket.OPEN || !credit || performance.now() - credit.at > 120)
      throw Error('AP link has no fresh response.');
    if (!(bytes instanceof Uint8Array) || !bytes.length || bytes.length > MAX_FRAME || ws.bufferedAmount > MAX_FRAME)
      throw Error('AP frame refused.');
    const payload = header(FRAME, credit.value, 5 + bytes.length);
    payload.set(bytes, 5);
    ws.send(payload);
  }

  shutdown(error) {
    clearTimeout(this.openTimer);
    clearInterval(this.pollTimer);
    const ws = this.socket, reader = this.readController;
    this.socket = this.credit = this.pending = this.readController = this.cancelOpen = null;
    if (ws) {
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close();
    }
    if (reader) {
      if (error) reader.error(error);
      else reader.close();
    }
  }

  async close() {
    if (this.cancelOpen) this.cancelOpen();
    else this.shutdown();
  }
}
