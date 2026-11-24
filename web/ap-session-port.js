import {apUrl, MAX_ROUND_TRIP_MS} from './wifi.js';

import {runApWorker} from './ap-worker-runtime.js';

// Run polling away from rendering whenever the browser permits it. The shipped
// page already contains the complete worker, including its Wi-Fi dependency.
function createWorker() {
  let worker, blobUrl, opening, ready=false, local=false, ended=false;
  const bridge={
    postMessage(message){if(message.type==='open')opening=message;worker.postMessage(message);},
    terminate(){ended=true;worker?.terminate();if(blobUrl)URL.revokeObjectURL(blobUrl);}
  };
  function useWindow(){
    if(ended||local||ready)return;
    local=true;worker?.terminate();
    if(blobUrl){URL.revokeObjectURL(blobUrl);blobUrl=null;}
    const {port1,port2}=new MessageChannel();
    const stop=runApWorker(port2);
    worker=port1;worker.terminate=()=>{port1.close();void stop();};
    listen(port1);
    if(opening){bridge.onfallback?.();port1.postMessage(opening);}
  }
  function listen(instance){
    instance.onmessage=event=>{
      if(ended||instance!==worker)return;
      if(event.data.type==='error'&&!ready&&!local){useWindow();return;}
      if(event.data.type==='ready')ready=true;
      bridge.onmessage?.(event);
    };
    instance.onmessageerror=event=>bridge.onmessageerror?.(event);
    instance.onerror=event=>{
      event.preventDefault?.();
      if(ended||instance!==worker)return;
      if(!ready&&!local)useWindow();else bridge.onerror?.(event);
    };
  }
  try{
    const source=JSON.parse(document.getElementById('ap-worker-source')?.textContent||'null');
    if(source)blobUrl=URL.createObjectURL(new Blob([source],{type:'text/javascript'}));
    worker=blobUrl?new Worker(blobUrl,{name:'Areion AP telemetry'}):
      new Worker(new URL('./ap-worker.js',import.meta.url),{type:'module',name:'Areion AP telemetry'});
    listen(worker);
  }catch{useWindow();}
  return bridge;
}

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
    const armDeadline=()=>{
      clearTimeout(this.startTimer);
      this.startTimer=setTimeout(()=>this.finish(Error('AP connection did not start. Join the kit Wi-Fi and allow local network access.')),35000);
    };
    worker.onfallback=armDeadline;
    armDeadline();
    this.error = null;this.timing=null;
    this.readable = new ReadableStream({
      start: controller => { this.controller = controller; },
      pull: () => {
        this.pull = pending();
        worker.postMessage({type:'pull'});
        return this.pull.promise;
      },
      cancel: () => { this.controller = null; this.pull?.resolve(); this.pull = null; }
    }, {highWaterMark:0});
    this.writable=new WritableStream({write:frame=>this.writeFresh(frame)});
    worker.onerror = event => {
      event.preventDefault?.();
      this.finish(Error('AP telemetry stopped'+(event.message?' · '+event.message:'. Reconnect to the kit Wi-Fi.')));
    };
    worker.onmessageerror = () => this.finish(Error('AP worker message could not be read.'));
    worker.onmessage = ({data}) => {
      if (worker !== this.worker) return;
      if(data.timing)this.timing=data.timing;
      switch (data.type) {
        case 'timing': break;
        case 'dropped':
          this.writeAck?.reject(Object.assign(Error(data.message),{code:'AP_FRAME_DROPPED'}));
          this.writeAck=null;break;
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

  // A WritableStream latches a rejected write. Release one expired command without poisoning later requests.
  writeFresh(frame) {
    if (this.error || !this.worker) return Promise.reject(this.error || Error('AP connection closed.'));
    if (this.writeAck) return Promise.reject(Object.assign(Error('AP write already pending.'),{code:'AP_FRAME_DROPPED'}));
    this.writeAck=pending();
    this.worker.postMessage({type:'write',bytes:frame.bytes,issuedAt:frame.issuedAt});
    return this.writeAck.promise;
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
