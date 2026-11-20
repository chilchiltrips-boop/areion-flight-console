import {encodeCommand, encodeRequest, FrameDecoder, matchesAck, newer, schemaFor, validGroup} from './protocol.js';

const SETTINGS = [125,110,7,112,134,130,121,2,3,4,6,132,136];
const OWNER_LOST = new Set(['NOT_OWNER','SESSION_EXPIRED','SESSION_RETIRED']);
const now = () => performance.now();
const nextSeq = seq => (seq + 1) >>> 0 || 1;
const sessionId = () => crypto.getRandomValues(new Uint32Array(1))[0] || 1;
const fail = (message,code=message) => Object.assign(new Error(message),{code});
function stopPriority(group,command) {
  if(group === 123 && command === 'DISARM')return 3;
  if(group === 135 && command === 'STOP')return 2;
  if(group === 135 && command === 'MOTOR_STOP')return 1;
  return 0;
}

function bounded(promise, ms, message) {
  let timer;
  const timeout = new Promise((_, reject) => { timer = setTimeout(() => reject(fail(message)), ms); });
  return Promise.race([promise,timeout]).finally(() => clearTimeout(timer));
}

// One link owns one confirmed route. An AP adapter exposes the same byte-stream
// interface as a SerialPort and must terminate on a compatible kit.
export class UsbTelemetry {
  static supported() { return Boolean(globalThis.isSecureContext && globalThis.navigator?.serial?.requestPort); }

  constructor({onStatus=()=>{},onData=()=>{},onTraffic=()=>{},onPort=()=>{}}={}) {
    this.onStatus=onStatus; this.onData=onData; this.onTraffic=onTraffic; this.onPort=onPort;
    this.current=null; this.closing=null; this.state='offline';
    this.stats={sent:0,received:0,lastRxAt:null};
  }

  get session() { return this.current?.fc ? this.current.session : null; }
  get fcSession() { return this.current?.fc || null; }
  get source() { return this.current?.source ?? null; }

  report(state,message) {
    if (state === this.state && message === this.message) return;
    this.state=state; this.message=message;
    this.onStatus({state,message});
  }

  async connect(port=null,{source=2,label=source===1?'AP Wi-Fi':'USB'}={}) {
    if (this.current || this.closing) return;
    if (![1,2].includes(source) || source===1 && !port) throw fail('Select a compatible kit connection.');
    if (source===2 && !UsbTelemetry.supported()) {
      this.report('error','USB requires desktop Chrome or Edge on HTTPS.');
      return;
    }
    const run={source,label,session:sessionId(),seq:0,controlSeq:0,fc:0,decoder:new FrameDecoder(),
      events:new Map(),latest:new Map(),reads:[...SETTINGS],pending:null,writing:false,
      lastRx:0,lastPing:0,lastPong:0,lastControl:null,neutralSince:null,closing:false};
    this.stats={sent:0,received:0,lastRxAt:null};
    this.current=run;
    this.report('opening',port?'Opening '+label+'…':'Choose the Areion USB port.');
    try {
      run.port=port || await navigator.serial.requestPort();
      if (this.current!==run) return;
      run.opening=run.port.open({baudRate:115200,bufferSize:16384});
      await run.opening; run.open=true;
      if (this.current!==run || run.closing) return;
      run.reader=run.port.readable.getReader();
      run.writer=run.port.writable.getWriter();
      run.started=now();
      this.report('handshake','Waiting for the flight controller over '+label+'.');
      run.reading=this.read(run);
      run.timer=setInterval(()=>this.tick(run),25);
      this.tick(run);
    } catch(error) {
      if (this.current!==run || run.closing) return;
      const cancelled=error.name==='NotFoundError';
      await this.stop(run,cancelled?'offline':'error',
        cancelled?'Connection cancelled.':'Cannot open '+label+'. '+error.message);
    }
  }

  async read(run) {
    try {
      while (!run.closing) {
        const {value,done}=await run.reader.read();
        if (done || this.current!==run || run.closing) break;
        for (const msg of run.decoder.push(value)) this.receive(run,msg);
      }
    } catch { /* Device removal and stream cancellation both end the reader. */ }
    finally {
      if (this.current===run && !run.closing) void this.stop(run,'error',run.label+' disconnected. Reconnect the kit.');
    }
  }

  traffic(direction,bytes,at) {
    if (direction==='rx') { this.stats.received++; this.stats.lastRxAt=at; }
    else this.stats.sent++;
    this.onTraffic({direction,bytes,at});
  }

  data(run,msg,at) {
    const row={group:msg.group,values:msg.data,at};
    run.latest.set(msg.group,row);
    this.onData(row);
  }

  finish(run,err,values) {
    const p=run.pending;
    run.pending=null;
    if (!p) return;
    if (p.signal) p.signal.removeEventListener('abort',p.abort);
    if (err) p.reject?.(err);
    else p.resolve?.(values);
  }

  receive(run,msg) {
    if (this.current!==run || run.closing) return;
    const at=now(), p=run.pending;
    if (p && msg.session===run.session && msg.seq===p.seq && msg.group===p.group && msg.schema===p.schema) {
      if (msg.type==='ERROR' && msg.data.length===1 && typeof msg.data[0]==='string') {
        this.traffic('rx',msg.byteLength,at);
        const reason=msg.data[0];
        if (p.type==='HELLO' && reason==='BUSY') {
          run.busy=true;
          this.report('handshake','Kit busy. Waiting for its previous connection to close.');
        } else if (p.type==='HELLO' || OWNER_LOST.has(reason)) {
          this.finish(run,fail(reason));
          void this.stop(run,'error','Controller rejected the connection: '+reason);
        } else {
          run.lastPong=at;
          this.finish(run,fail(reason));
        }
        return;
      }
      if (p.type==='HELLO' && msg.type==='ACK' && msg.data.length===2 && msg.data[0]==='HELLO' &&
          Number.isInteger(msg.data[1]) && msg.data[1]>0 && msg.data[1]<=0xffffffff && msg.data[1]!==run.session) {
        run.fc=msg.data[1];
        run.lastRx=run.lastPong=run.lastPing=at;
        this.traffic('rx',msg.byteLength,at);
        this.finish(run,null,msg.data);
        if(run.source===2)this.onPort(run.port);
        this.report('connected','Areion '+run.label+' connected.');
        return;
      }
      const read=p.type==='READ' && msg.type==='DATA' && validGroup(msg.group,msg.schema,msg.data);
      const pong=p.type==='PING' && msg.type==='ACK' && msg.data.length===1 && msg.data[0]==='PONG';
      if (read || pong || matchesAck(p,msg)) {
        run.lastPong=at;
        this.traffic('rx',msg.byteLength,at);
        this.finish(run,null,msg.data);
        if(read && !p.saved) {
          if ([120,122,21,23,130].includes(msg.group)) run.lastRx=at;
          this.data(run,msg,at);
        }
      }
      return;
    }
    if(!run.fc || msg.session!==run.fc || msg.type!=='DATA' || !validGroup(msg.group,msg.schema,msg.data))return;
    const prior=run.events.get(msg.group);
    if(prior!==undefined && !newer(msg.seq,prior))return;
    run.events.set(msg.group,msg.seq);
    run.lastRx=at;
    this.traffic('rx',msg.byteLength,at);
    this.data(run,msg,at);
  }

  write(run,frame) {
    run.writing=true;
    run.writeDone=bounded(run.writer.write(frame),1100,run.label+' write timed out.')
      .then(()=>{if(this.current===run)this.traffic('tx',frame.length,now());})
      .catch(()=>{if(this.current===run&&!run.closing)void this.stop(run,'error',run.label+' write failed. Reconnect the kit.');})
      .finally(()=>{
        run.writing=false;
        if(this.current===run && run.pending?.sent===null) this.tick(run);
      });
  }

  startRequest(run,type,group=0) {
    const schema=group===0?1:schemaFor(group), seq=run.seq=nextSeq(run.seq);
    const frame=encodeRequest(type,group,schema,run.session,seq);
    run.pending={type,group,schema,seq,frame,values:[],sent:now()};
    this.write(run,frame);
  }

  currentRow(run,group,limit=500) {
    const row=run.latest.get(group);
    return row && now()-row.at<=limit ? row.values : null;
  }

  controlState(run) {
    const status=this.currentRow(run,120), input=this.currentRow(run,122), setup=this.currentRow(run,130);
    if(!status || !input || now()-run.lastRx>=500 || input[0]!==run.source || input[7]!==run.session)
      throw fail('Waiting for fresh flight status and the selected input on this connection.');
    if(!setup || setup[0] || !setup[1] || setup[8])throw fail('Flight arming is locked or setup is incomplete.');
    if(globalThis.document?.visibilityState==='hidden')throw fail('The flight controls are in a background tab.');
    return {input,status,ready:input[1]===run.source+1 && input[run.source===1?3:8] &&
      input[4] && input[5]===8 && input[6]<(run.latest.get(112)?.values[1]??250)};
  }

  checkArm(run) {
    const {input,status,ready}=this.controlState(run), at=now();
    const last=run.lastControl, limits=run.latest.get(4)?.values;
    if(!ready || !this.currentRow(run,122,250) || input[7]!==run.session || status[0] ||
       !last || at-last.at>=150 || run.neutralSince===null || at-run.neutralSince<250 ||
       last.values[2]>=(limits?.[0]??1050) || [0,1,3].some(i=>Math.abs(last.values[i]-1500)>100))
      throw fail('ARM requires fresh neutral sender input and a disarmed controller.');
  }

  rpc(type,group,values,{signal}={}) {
    const run=this.current, priority=type==='ACTION' ? stopPriority(group,values?.[0]) : 0;
    const canInspect=type==='READ' && this.state==='stale';
    if(!run?.fc || run.closing || !priority && !canInspect && this.state!=='connected')
      return Promise.reject(fail('Connect to a live controller first.','OFFLINE'));
    if(signal?.aborted)return Promise.reject(fail('Request cancelled.','CANCELLED'));
    const seq=nextSeq(run.seq), schema=schemaFor(group)??1;
    let frame;
    try {frame=encodeCommand(type,group,run.session,seq,values);}
    catch(error){return Promise.reject(error);}
    if(run.pending?.priority>priority && priority)return Promise.reject(fail('A higher priority stop is in progress.','STOP_PENDING'));
    if(run.pending?.resolve && !priority)return Promise.reject(fail('Wait for the current kit operation.','BUSY'));
    if(run.pending) {
      if(!run.pending.resolve && run.pending.type==='READ')run.reads.unshift(run.pending.group);
      this.finish(run,fail('Superseded by a newer request.','CANCELLED'));
    }
    if(priority){run.neutralSince=null;run.lastControl=null;}
    run.seq=seq;
    return new Promise((resolve,reject)=>{
      const p={type,group,values:[...values],schema,seq,frame,saved:type==='READ' && values[0]==='saved',
        resolve,reject,signal,created:now(),sent:null,attempt:0,priority};
      p.abort=()=>{if(run.pending===p)this.finish(run,fail('Request cancelled.','CANCELLED'));};
      signal?.addEventListener('abort',p.abort,{once:true});
      run.pending=p;
      this.tick(run);
    });
  }

  readGroup(group,{saved=false,signal}={}) {return this.rpc('READ',group,saved?['saved']:[],{signal});}
  setGroup(group,values,options) {return this.rpc('SET',group,values,options);}
  saveGroup(group,options) {return this.rpc('SAVE',group,[],options);}
  action(group,values,options) {return this.rpc('ACTION',group,values,options);}

  sendControl(values) {
    const run=this.current;
    if(!run?.fc || this.state!=='connected')throw fail('No confirmed control connection.');
    const frame=encodeCommand('CONTROL',9,run.session,nextSeq(run.controlSeq),values);
    const {ready,status}=this.controlState(run);
    const neutral=values[2]===1000 && [0,1,3].every(i=>values[i]===1500);
    if(!ready && (status[0] || !neutral))throw fail('The controller is waiting for neutral input.');
    // An unsent stick position is dropped rather than queued behind an older USB frame.
    if(run.writing || run.pending?.sent===null || run.pending?.priority)return false;
    const at=now(), last=run.lastControl;
    const low=values[2]<(run.latest.get(4)?.values?.[0]??1050) && [0,1,3].every(i=>Math.abs(values[i]-1500)<=100);
    run.neutralSince=low?(last && at-last.at<150?(run.neutralSince??at):at):null;
    run.lastControl={at,values:[...values]};
    run.controlSeq=nextSeq(run.controlSeq);
    this.write(run,frame);
    return true;
  }

  tick(run) {
    if(this.current!==run || run.closing || run.writing)return;
    const at=now(), p=run.pending;
    if(!run.fc) {
      if(at-run.started>8500)void this.stop(run,'error',run.busy?'Kit busy. Close its other connection and reconnect.':'No Areion Link v2 response on '+run.label+'.');
      else if(!p)this.startRequest(run,'HELLO');
      else if(at-p.sent>=550){p.sent=at;this.write(run,p.frame);}
      return;
    }
    if(at-run.lastPong>4800){void this.stop(run,'error','Controller heartbeat stopped. Reconnect the kit.');return;}
    const stale=at-run.lastRx>1200;
    if(stale)this.report('stale','Waiting for fresh telemetry.');
    else this.report('connected','Areion '+run.label+' connected.');
    // Status callbacks can synchronously cancel/send a newer operation.
    if(this.current!==run || p!==run.pending || run.writing)return;
    if(p?.resolve) {
      if(p.sent===null) {
        if(!p.priority && (stale && p.type!=='READ' || at-p.created>150)){this.finish(run,fail('Request expired before transmission.','EXPIRED'));return;}
        try {
          if(p.group===123 && p.values[0]==='ARM')this.checkArm(run);
          if(!p.priority && p.type!=='READ' && globalThis.document?.visibilityState==='hidden')throw fail('Return to the console to send this command.');
        } catch(error){this.finish(run,error);return;}
        p.sent=at; p.attempt++; this.write(run,p.frame);
      } else if(at-p.sent>(p.type==='SAVE'||p.type==='ACTION'&&p.group!==123?1500:600)) {
        // Reuse the exact sequence and bytes for idempotent reads/settings only.
        // Do not reissue ARM or motor test commands on delayed or lost replies.
        if(p.attempt<2 && ['READ','SET','SAVE'].includes(p.type) && !stale &&
           globalThis.document?.visibilityState!=='hidden'){p.attempt++;p.sent=at;this.write(run,p.frame);}
        else this.finish(run,fail('Controller reply timed out. Read the kit to verify its state.','TIMEOUT'));
      }
      return;
    }
    if(p && at-p.sent<800)return;
    if(p)this.finish(run);
    if(at-run.lastPing>=950){run.lastPing=at;this.startRequest(run,'PING');}
    else if(run.reads.length)this.startRequest(run,'READ',run.reads.shift());
  }

  async stop(run,state,message) {
    if(this.current!==run || run.closing)return this.closing;
    run.closing=true; this.current=null;
    clearInterval(run.timer);
    this.finish(run,fail('Connection closed.','OFFLINE'));
    this.closing=(async()=>{
      try {
        if(run.opening && !run.open)run.port?.cancelOpen?.();
        if(run.opening)await run.opening.catch(()=>{});
        if(run.fc && run.writer && state==='offline') {
          if(run.writing)await run.writeDone;
          const frame=encodeRequest('RELEASE',0,1,run.session,nextSeq(run.seq));
          await bounded(run.writer.write(frame),300,'Release timeout').catch(()=>{});
        }
        if(run.reader)await run.reader.cancel().catch(()=>{});
        if(run.reading)await run.reading;
        run.reader?.releaseLock();
        if(run.writer) {
          await bounded(run.writer.abort(),450,'Close timeout').catch(()=>{});
          run.writer.releaseLock();
        }
      } finally {
        if(run.port && run.open)await run.port.close().catch(()=>{});
      }
    })();
    try {await this.closing;}
    finally {this.closing=null;this.report(state,message);}
  }
  async disconnect() {
    if(this.current)await this.stop(this.current,'offline','Disconnected.');
    else if(this.closing)await this.closing;
  }
}
