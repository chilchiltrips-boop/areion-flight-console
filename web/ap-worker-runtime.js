import {WifiPort, AP_CREDIT_MS, MAX_ROUND_TRIP_MS} from './wifi.js';

export function runApWorker(scope) {
  // Keep gateway polling independent of rendering. Opening a page or parsing a
  // model on the window thread must not interrupt them. Only the window issues
  // Link commands; polling never creates or repeats a flight-control frame.
  const clock = () => performance.timeOrigin + performance.now();
  const MAX_BURSTS = 8;
  let port, waiting = false, closed = false;
  const queue = [];

  function deliver() {
    while (queue.length && clock() - queue[0].receivedAt > MAX_ROUND_TRIP_MS) queue.shift();
    if (!waiting || !queue.length) return;
    waiting = false;
    const sample = queue.shift();
    scope.postMessage({type:'data', ...sample}, [sample.bytes.buffer]);
  }

  async function end(error) {
    if (closed) return;
    closed = true;
    await port?.close();
    scope.postMessage(error ? {type:'error', message:error.message,timing:port?.timing} : {type:'closed'});
    scope.close();
  }

  async function open(url) {
    port = new WifiPort(url);
    port.onTiming=timing=>scope.postMessage({type:'timing',timing});
    await port.open();
    if (closed) return;
    const reader = port.readable.getReader();
    scope.postMessage({type:'ready'});
    try {
      while (!closed) {
        const {value, done} = await reader.read();
        if (done) break;
        if (queue.length === MAX_BURSTS) queue.shift();
        queue.push({bytes:value, receivedAt:clock()});
        deliver();
      }
    } finally {
      reader.releaseLock();
    }
    if (!closed) await end(Error('Kit WebSocket ended.'));
  }

  scope.onmessage = async ({data}) => {
    if (closed) return;
    try {
      switch (data.type) {
        case 'open': if (!port) await open(data.url); break;
        case 'pull': waiting = true; deliver(); break;
        case 'write': {
          const age = clock() - data.issuedAt;
          if (!Number.isFinite(age) || age < -1 || age > AP_CREDIT_MS) {
            port.timing.dropped_writes++;
            scope.postMessage({type:'dropped',message:'AP command expired before transmission.',timing:port.timing});
            break;
          }
          try { port.write(data.bytes); }
          catch(error) {
            if(error.code!=='AP_FRAME_DROPPED')throw error;
            scope.postMessage({type:'dropped',message:error.message,timing:port.timing});
            break;
          }
          scope.postMessage({type:'sent'});
          break;
        }
        case 'close': await end(); break;
      }
    } catch (error) { await end(error); }
  };
  return end;
}
