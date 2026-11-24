import {apUrl, MAX_ROUND_TRIP_MS} from './wifi.js';

const createWorker = () => new Worker(new URL('./ap-worker.js', import.meta.url),
  {type:'module', name:'Areion AP telemetry'});

function pending() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve=ok; reject=fail; });
  return {promise, resolve, reject};
}

// One worker and one socket per explicit Connect, shared by every console page.
export class ApSessionPort {
  constructor(endpoint, workerFactory = createWorker) {
    this.url = apUrl(endpoint);
    this.workerFactory = workerFactory;
    this.timestamped = true;
  }

  open() {
    if (this.worker) throw Error('AP Wi-Fi is already open.');
    const worker = this.worker = this.workerFactory();
    const opened = this.opened = pending();
    this.startTimer = setTimeout(() => this.finish(Error('AP connection did not start. Check the kit Wi-Fi and offline console files.')), 35000);
    this.error = null;
    this.readable = new ReadableStream({
      start: controller => { this.controller = controller; },
      pull: () => {
        this.pull = pending();
        worker.postMessage({type:'pull'});
        return this.pull.promise;
      },
      cancel: () => { this.controller = null; this.pull?.resolve(); this.pull = null; }
    }, {highWaterMark:0});
    this.writable = new WritableStream({
      write: frame => {
        if (this.error || !this.worker) throw this.error || Error('AP connection closed.');
        this.writeAck = pending();
        worker.postMessage({type:'write', bytes:frame.bytes, issuedAt:frame.issuedAt});
        return this.writeAck.promise;
      }
    });
    worker.onerror = event => {
      event.preventDefault?.();
      this.finish(Error('AP connection worker stopped. Reopen the console online if its files need updating.'));
    };
    worker.onmessageerror = () => this.finish(Error('AP worker message could not be read.'));
    worker.onmessage = ({data}) => {
      if (worker !== this.worker) return;
      switch (data.type) {
        case 'ready': clearTimeout(this.startTimer); opened.resolve(); this.opened = null; break;
        case 'sent': this.writeAck?.resolve(); this.writeAck = null; break;
        case 'error': this.finish(Error(data.message)); break;
        case 'closed': this.finish(); break;
        case 'data': {
          if (!this.pull || !this.controller) break;
          const now = performance.now();
          const at = Math.min(now, data.receivedAt - performance.timeOrigin);
          if (!Number.isFinite(at) || now - at > MAX_ROUND_TRIP_MS) {
            // A delayed UI must never turn pre-stall telemetry into live flight input.
            worker.postMessage({type:'pull'});
            break;
          }
          this.controller.enqueue({bytes:data.bytes, at});
          this.pull.resolve();
          this.pull = null;
          break;
        }
      }
    };
    worker.postMessage({type:'open', url:this.url});
    return opened.promise;
  }

  cancelOpen() { this.finish(Error('AP connection cancelled.')); }

  finish(error) {
    if (!this.worker) return;
    clearTimeout(this.startTimer);
    this.worker.terminate();
    this.worker = null;
    this.error = error || Error('AP connection closed.');
    this.opened?.reject(this.error);
    this.writeAck?.reject(this.error);
    if (this.controller) {
      if (error) this.controller.error(error);
      else this.controller.close();
    }
    this.pull?.resolve();
    this.closed?.resolve();
    this.controller = this.opened = this.writeAck = this.pull = this.closed = null;
  }

  async close() {
    if (!this.worker) return;
    if (this.closed) return this.closed.promise;
    const closed = this.closed = pending();
    this.worker.postMessage({type:'close'});
    const timer = setTimeout(() => this.finish(), 350);
    try { await closed.promise; } finally { clearTimeout(timer); }
  }
}
