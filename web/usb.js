import { encodeRequest, FrameDecoder, newer, schemaFor, validGroup } from "./protocol.js";

const SETTINGS = [125, 110, 7, 112, 134, 130, 121, 2, 3, 4, 6, 132, 136];
const OWNER_LOST = new Set(["NOT_OWNER", "SESSION_EXPIRED", "SESSION_RETIRED"]);
const time = () => performance.now();
const nextSeq = seq => (seq + 1) >>> 0 || 1;
const sessionId = () => crypto.getRandomValues(new Uint32Array(1))[0] || 1;
const handshakeWindow = 8500; // Includes FC boot and the five-second orphaned owner lease.

function bounded(promise, ms, message) {
  let timer;
  const timeout = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), ms); });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

export class UsbTelemetry {
  static supported() {
    return Boolean(globalThis.isSecureContext && globalThis.navigator?.serial?.requestPort);
  }

  constructor({onStatus = () => {}, onData = () => {}} = {}) {
    this.onStatus = onStatus;
    this.onData = onData;
    this.current = null;
    this.closing = null;
    this.state = "offline";
  }

  report(state, message) {
    if (state === this.state && message === this.message) return;
    this.state = state;
    this.message = message;
    this.onStatus({state, message});
  }

  async connect() {
    if (this.current || this.closing) return;
    if (!UsbTelemetry.supported()) {
      this.report("error", "USB requires desktop Chrome or Edge on HTTPS.");
      return;
    }
    const run = {
      session: sessionId(), seq: 0, fc: 0, decoder: new FrameDecoder(), eventSeq: new Map(),
      pending: null, reads: [...SETTINGS], lastRx: 0, lastPing: 0, lastPong: 0,
      busyMessage: false, closing: false
    };
    this.current = run;
    this.report("opening", "Choose the Areion USB port.");
    try {
      const port = await navigator.serial.requestPort();
      if (this.current !== run) return;
      run.port = port;
      // Track a pending open: disconnect waits for it before releasing the port.
      run.opening = port.open({baudRate: 115200, bufferSize: 16384});
      await run.opening;
      run.open = true;
      if (this.current !== run || run.closing) return;
      run.reader = port.readable.getReader();
      run.writer = port.writable.getWriter();
      run.started = time();
      this.report("handshake", "Waiting for the flight controller.");
      run.reading = this.read(run);
      run.timer = setInterval(() => this.tick(run), 100);
      this.tick(run);
    } catch (error) {
      if (this.current !== run || run.closing) return;
      const cancelled = error.name === "NotFoundError";
      await this.stop(run, cancelled ? "offline" : "error",
        cancelled ? "USB connection cancelled." : "Cannot open USB. " + error.message);
    }
  }

  async read(run) {
    try {
      while (!run.closing) {
        const {value, done} = await run.reader.read();
        if (done) break;
        if (this.current !== run || run.closing) break;
        for (const msg of run.decoder.push(value)) this.receive(run, msg);
      }
    } catch {
      // An unplugged device may raise, or may end the stream.
    } finally {
      if (this.current === run && !run.closing)
        void this.stop(run, "error", "USB disconnected. Reconnect the kit.");
    }
  }

  receive(run, msg) {
    const now = time();
    if (this.current !== run || run.closing) return;
    const pending = run.pending;
    if (pending && msg.session === run.session && msg.seq === pending.seq
        && msg.group === pending.group && msg.schema === pending.schema) {
      if (msg.type === "ERROR" && msg.data.length === 1 && typeof msg.data[0] === "string") {
        if (pending.type === "HELLO" && msg.data[0] === "BUSY") {
          run.busyMessage = true;
          this.report("handshake", "Port is open. Waiting for the previous kit connection to close.");
          return;
        }
        if (pending.type === "HELLO" || OWNER_LOST.has(msg.data[0])) {
          void this.stop(run, "error", "Flight controller rejected this connection: " + msg.data[0]);
        } else {
          run.pending = null;
        }
        return;
      }
      if (pending.type === "HELLO" && msg.type === "ACK" && msg.data.length === 2
          && msg.data[0] === "HELLO" && Number.isInteger(msg.data[1])
          && msg.data[1] > 0 && msg.data[1] <= 0xffffffff && msg.data[1] !== run.session) {
        run.fc = msg.data[1];
        run.lastRx = run.lastPong = run.lastPing = now;
        run.pending = null;
        this.report("connected", "Areion USB connected.");
      } else if (pending.type === "PING" && msg.type === "ACK"
                 && msg.data.length === 1 && msg.data[0] === "PONG") {
        run.lastPong = now;
        run.pending = null;
      } else if (pending.type === "READ" && msg.type === "DATA" && validGroup(msg.group, msg.schema, msg.data)) {
        run.pending = null;
        this.onData({group: msg.group, values: msg.data, at: now});
      }
      return;
    }
    if (!run.fc || msg.session !== run.fc || msg.type !== "DATA"
        || !validGroup(msg.group, msg.schema, msg.data)) return;
    const prior = run.eventSeq.get(msg.group);
    if (prior !== undefined && !newer(msg.seq, prior)) return;
    run.eventSeq.set(msg.group, msg.seq);
    run.lastRx = now;
    this.onData({group: msg.group, values: msg.data, at: now});
  }

  write(run, frame) {
    run.writing = true;
    bounded(run.writer.write(frame), 1100, "USB write timed out.").catch(() => {
      if (this.current === run && !run.closing)
        void this.stop(run, "error", "USB write failed. Reconnect the kit.");
    }).finally(() => { run.writing = false; });
  }

  request(run, type, group = 0) {
    const schema = group === 0 ? 1 : schemaFor(group);
    const seq = run.seq = nextSeq(run.seq);
    const frame = encodeRequest(type, group, schema, run.session, seq);
    run.pending = {type, group, schema, seq, frame, sent: time()};
    this.write(run, frame);
  }

  tick(run) {
    if (this.current !== run || run.closing || run.writing) return;
    const now = time();
    if (!run.fc) {
      if (now - run.started > handshakeWindow) {
        void this.stop(run, "error", run.busyMessage
          ? "Kit is busy. Close the desktop console, then reconnect."
          : "No Areion Link 2 response. Check the kit and USB port.");
      } else if (!run.pending) {
        this.request(run, "HELLO");
      } else if (now - run.pending.sent >= 550) {
        run.pending.sent = now;
        this.write(run, run.pending.frame);
      }
      return;
    }
    if (now - run.lastPong > 4800) {
      void this.stop(run, "error", "The controller heartbeat stopped. Reconnect the kit.");
      return;
    }
    if (now - run.lastRx > 1200)
      this.report("stale", "Waiting for fresh telemetry.");
    else
      this.report("connected", "Areion USB connected.");
    if (run.pending) {
      if (now - run.pending.sent < 800) return;
      run.pending = null;
    }
    if (now - run.lastPing >= 950) {
      run.lastPing = now;
      this.request(run, "PING");
    } else if (run.reads.length) {
      this.request(run, "READ", run.reads.shift());
    }
  }

  async stop(run, state, message) {
    if (this.current !== run || run.closing) return this.closing;
    run.closing = true;
    this.current = null;
    clearInterval(run.timer);
    this.closing = (async () => {
      try {
        if (run.opening) await run.opening.catch(() => {});
        if (run.fc && run.writer && !run.writing && state === "offline") {
          const frame = encodeRequest("RELEASE", 0, 1, run.session, nextSeq(run.seq));
          await bounded(run.writer.write(frame), 300, "Release timeout").catch(() => {});
        }
        if (run.reader) await run.reader.cancel().catch(() => {});
        if (run.reading) await run.reading;
        if (run.reader) run.reader.releaseLock();
        if (run.writer) {
          await bounded(run.writer.abort(), 450, "USB close timeout").catch(() => {});
          run.writer.releaseLock();
        }
        if (run.port && run.open) await run.port.close();
      } catch { /* A physically removed port might already be closed. */ }
    })();
    try {
      await this.closing;
    } finally {
      this.closing = null;
      this.report(state, message);
    }
  }

  async disconnect() {
    if (this.current) await this.stop(this.current, "offline", "USB disconnected.");
    else if (this.closing) await this.closing;
  }
}
