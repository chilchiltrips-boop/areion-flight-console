import {parentPort} from 'node:worker_threads';
import {crc32} from 'node:zlib';

const encoder = new TextEncoder(), fc = 8451, credit = 142;
function packet(message) {
  const json = JSON.stringify(message), bytes = encoder.encode(json);
  return encoder.encode('$'+bytes.length+':'+json+'*'+crc32(bytes).toString(16).toUpperCase().padStart(8,'0')+'\n');
}

// The fixture enforces the shipping gateway's maximum interval between polls.
class KitSocket {
  static OPEN=1; static CONNECTING=0;
  constructor(url,protocol) {
    this.protocol=protocol;
    this.readyState=0; this.bufferedAmount=0; this.last=performance.now();
    this.replies=[]; this.sequence=0; this.connected=false;
    KitSocket.instance=this;
    parentPort.postMessage({audit:'socket'});
    queueMicrotask(()=>{this.readyState=1;this.onopen();});
  }
  send(frame) {
    const id=new DataView(frame.buffer,frame.byteOffset).getUint32(1);
    if(frame[0]===80) {
      const now=performance.now();
      if(now-this.last>250)return this.drop();
      this.last=now;
      if(this.connected)this.replies.push(packet({v:2,type:'DATA',group:22,schema:1,session:fc,seq:++this.sequence,
        data:[1500,1500,1010,1500,1000,1000,1500,1500]}));
      const view=new Uint8Array(9+this.replies.reduce((n,r)=>n+r.length,0));
      const head=new DataView(view.buffer);
      view[0]=65;head.setUint32(1,id);head.setUint32(5,credit);
      let i=9;for(const r of this.replies){view.set(r,i);i+=r.length;}
      this.replies=[];
      parentPort.postMessage({audit:'poll',time:now});
      queueMicrotask(()=>this.onmessage?.({data:view.buffer}));
      return;
    }
    if(frame[0]!==70 || id!==credit)throw Error('Gateway rejected credit');
    const wire=new TextDecoder().decode(frame.subarray(5));
    const msg=JSON.parse(wire.slice(wire.indexOf(':')+1,-10));
    parentPort.postMessage({audit:'request',command:msg.type});
    const reply=(type,data)=>this.replies.push(packet({...msg,type,data}));
    if(msg.type==='HELLO'){this.connected=true;reply('ACK',['HELLO',fc]);}
    else if(msg.type==='PING')reply('ACK',['PONG']);
    else if(msg.type==='READ' && msg.group===110)reply('DATA',[1]);
    else if(msg.type==='READ')reply('ERROR',['UNAVAILABLE']);
  }
  drop(){this.readyState=3;this.onclose?.({code:1006});}
  close(){this.readyState=3;}
}

globalThis.WebSocket=KitSocket;
globalThis.self = {postMessage:(value,transfer)=>parentPort.postMessage(value,transfer),close:()=>parentPort.close()};
await import('../../web/ap-worker.js');
parentPort.on('message',data=>{
  if(data.test==='radio-loss')KitSocket.instance.drop();
  else self.onmessage({data});
});
