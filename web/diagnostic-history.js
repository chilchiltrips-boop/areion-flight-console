// Batches keep the flight display independent of disk speed. The metadata and its
// batches commit together; a clear watermark also covers other tabs' pending writes.
const blank=(cleared=0)=>({count:0,cleared,latest:0,recent:[],issue:null,esc:null});
const clock=()=>performance.timeOrigin+performance.now();
const notable=row=>!['telemetry','control','reply'].includes(row.kind)||['error','warning','interrupted'].includes(row.status);
function summarize(meta,rows){
  const updates=rows.filter(notable);
  const issues=updates.filter(r=>['error','warning','interrupted'].includes(r.status));
  const latest=(a,b)=>b.time-a.time;
  return {count:meta.count+rows.length,cleared:meta.cleared,latest:rows.reduce((t,r)=>Math.max(t,r.time),meta.latest||0),
    esc:[...updates.filter(r=>r.kind==='setup'&&r.group===130),meta.esc].filter(Boolean).sort(latest)[0]??null,
    recent:[...updates,...meta.recent].sort(latest).slice(0,24),
    issue:[...issues,meta.issue].filter(Boolean).sort(latest)[0]??null};
}
function openDatabase(){
  return new Promise((resolve,reject)=>{
    const request=indexedDB.open('areion-flight-diagnostics',1);
    request.onupgradeneeded=()=>{
      request.result.createObjectStore('batches',{autoIncrement:true});
      request.result.createObjectStore('state');
    };
    request.onerror=()=>reject(request.error);
    request.onsuccess=()=>resolve(request.result);
  });
}
function transaction(db,mode,work){
  return new Promise((resolve,reject)=>{
    const tx=db.transaction(['batches','state'],mode);
    let result;
    tx.oncomplete=()=>resolve(result);
    tx.onabort=()=>reject(tx.error||Error('Diagnostic storage transaction interrupted.'));
    const state=tx.objectStore('state'),request=state.get('summary');
    request.onsuccess=()=>{result=work(request.result??blank(),tx.objectStore('batches'),state);};
  });
}
function cleaned(row) {
  if(row.group!==138 && row.group!==139)return row;
  // Wi-Fi configuration can contain credentials. Keep only the operation outcome.
  return {...row,name:'USB Wi-Fi settings',values:undefined,detail:row.status==='error'?'Wi-Fi settings request failed.':undefined};
}

export class DiagnosticHistory {
  constructor(open=openDatabase){
    this.pending=[];this.fallback=[];this.lost=0;this.meta=blank();this.issue='';this.timer=null;
    this.work=Promise.resolve();
    this.database=Promise.resolve().then(open).catch(error=>{this.issue=error.message||'Browser storage unavailable';return null;});
    this.ready=this.enqueue(async()=>{
      const db=await this.database;
      if(db)try{this.meta=await transaction(db,'readonly',meta=>meta);}
      catch(error){this.issue=error.message;}
    });
  }
  enqueue(fn){
    const task=this.work.then(fn);
    this.work=task.catch(()=>{});
    return task;
  }
  add(record){
    const row=cleaned({...record,time:clock()});
    this.pending.push(row);
    if(this.pending.length>=128 || ['connection','setup','calibration'].includes(row.kind) ||
       ['error','interrupted'].includes(row.status) || row.kind==='operation'&&row.status==='ok')this.flush();
    else if(!this.timer)this.timer=setTimeout(()=>this.flush(),750);
  }
  flush(){
    clearTimeout(this.timer);this.timer=null;
    if(!this.pending.length)return this.work;
    const rows=this.pending;this.pending=[];
    return this.enqueue(async()=>{
      const db=await this.database;
      if(db)try{
        const backlog=this.fallback;
        this.meta=await transaction(db,'readwrite',(meta,batches,state)=>{
          const fresh=[...backlog,...rows].filter(r=>r.time>meta.cleared);
          if(!fresh.length)return meta;
          for(let i=0;i<fresh.length;i+=128)batches.add(fresh.slice(i,i+128));
          const next=summarize(meta,fresh);state.put(next,'summary');return next;
        });
        this.fallback=[];this.issue='';return;
      }catch(error){this.issue=error.message;}
      this.fallback.push(...rows);
      if(this.fallback.length>12000)this.lost+=this.fallback.splice(0,this.fallback.length-12000).length;
    });
  }
  summary(){
    const local=this.fallback.length?summarize(this.meta,this.fallback):this.meta;
    return {...local,pending:this.pending.length,storage:this.issue,lost:this.lost};
  }
  async visit(consume){
    this.flush();
    return this.enqueue(async()=>{
      const db=await this.database;
      if(db)this.meta=await transaction(db,'readonly',(meta,batches)=>{
        const request=batches.openCursor();
        request.onsuccess=()=>{
          const cursor=request.result;
          if(cursor){consume(cursor.value);cursor.continue();}
        };
        return meta;
      });
      if(this.fallback.length)consume(this.fallback.filter(row=>row.time>this.meta.cleared));
      return this.summary();
    });
  }
  clear(){
    const cutoff=clock();
    this.flush();
    return this.enqueue(async()=>{
      const db=await this.database;
      if(db)this.meta=await transaction(db,'readwrite',(meta,batches,state)=>{
        // Another tab may already have committed new records after this click.
        const barrier=Math.max(cutoff,meta.cleared),next=blank(barrier);
        if(meta.latest<=barrier){batches.clear();state.put(next,'summary');return next;}
        const request=batches.openCursor();
        request.onsuccess=()=>{
          const cursor=request.result;
          if(!cursor){state.put(next,'summary');return;}
          const keep=cursor.value.filter(row=>row.time>barrier);
          if(!keep.length)cursor.delete();
          else{if(keep.length!==cursor.value.length)cursor.update(keep);Object.assign(next,summarize(next,keep));}
          cursor.continue();
        };
        return next;
      });else this.meta=blank(cutoff);
      this.fallback=this.fallback.filter(row=>row.time>this.meta.cleared);this.lost=0;
    });
  }
  async refresh(){
    return this.enqueue(async()=>{
      const db=await this.database;
      if(db){
        this.meta=await transaction(db,'readonly',meta=>meta);
        this.fallback=this.fallback.filter(row=>row.time>this.meta.cleared);
      }
    });
  }
}
