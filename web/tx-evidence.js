// Physical radio status is inferred only from the receiver behavior verified on this kit.
const FRESH=500, SAMPLES=3, SEPARATION=300, TOLERANCE=75;
const fresh=(at,now)=>Number.isFinite(at)&&at<=now&&now-at<=FRESH;
const same=(a,b)=>Array.isArray(a)&&Array.isArray(b)&&a.length===b.length&&a.every((v,i)=>v===b[i]);
const result=(code,label,detail,level='warn')=>({code,label,detail,level});
const band=(v,target)=>Number.isFinite(v)&&Math.abs(v-target)<=TOLERANCE;
function pulse(v,timeout){
  if(!v||v[0]!==0||![0,1].includes(v[1]))return null;
  if(v[2]===false&&v[1]===0&&!v[4])return false;
  if(v[2]===true&&v[5]>=4&&v[5]<=8&&v[6]>=0&&v[6]<timeout&&v[4]===(v[1]===1))return true;
  return null;
}
export function spareChannels(o){
  return o.mapping.length===4&&Number.isInteger(o.mode)?[5,6,7,8].filter(ch=>ch<=o.count&&ch!==o.mode&&!o.mapping.includes(ch)):[];
}

export function observeTx(ctx,now=ctx.clock){
  const live=ctx.state==='connected'&&!ctx.replay;
  const frame=g=>ctx.model.frames.get(g);
  const setup=frame(130)?.values, config=frame(134)?.values;
  const rx=frame(122),selected=frame(110),fc=frame(120), mode=frame(7)?.values[0], timeout=frame(112)?.values[0]??250;
  const newerSelection=selected && (!rx || selected.at>rx.at);
  const o={now,session:ctx.model,live,source:newerSelection?selected.values[0]:rx?.values[0]??selected?.values[0],
    kit:live?(setup?.[15]||''):'',mapping:config?.slice(2,6)||[],mode,count:0,
    armed:live&&fresh(fc?.at,now)?fc.values[0]:null,pulse:null,inputs:[],channels:[]};
  if(!live||o.source!==0||!fresh(rx?.at,now))return o;
  o.pulse=pulse(rx.values,timeout);o.count=rx.values[5];
  if(o.pulse && (newerSelection || (rx.values[4]&&fresh(fc?.at,now)&&fc.at>rx.at&&fc.values[3]!==o.count)))o.pulse=null;
  if(o.pulse===null)return o;
  const rows=ctx.rows, since=now-(SAMPLES+2)*FRESH;
  let i=rows.length;while(i>0&&rows[i-1].at>=since)i--;
  let gate=null, gateAt=-Infinity,invalidated=-Infinity;
  for(;i<rows.length;i++){
    const {at,group,values}=rows[i]; if(at>now)break;
    if(group===122){
      const p=pulse(values,timeout);
      o.inputs.push({at,pulse:p,count:values[5]});if(o.inputs.length>SAMPLES)o.inputs.shift();
      const next=p&&values[4]&&values[1]===1?values[5]:null;
      if(gate!==next || !fresh(gateAt,at))o.channels=[];
      gate=next;gateAt=at;
    }else if(group===120 && values[3]!==o.count){
      invalidated=at;o.channels=[];
    }else if(group===22){
      if(gate===o.count && fresh(gateAt,at) && at>invalidated && at>=(selected?.at??-Infinity) &&
          values.slice(0,gate).every(v=>Number.isInteger(v)&&v>=900&&v<=2100)){
        o.channels.push({at,values});if(o.channels.length>SAMPLES)o.channels.shift();
      }else o.channels=[];
    }
  }
  if(!o.pulse||!rx.values[4]||!fresh(o.channels.at(-1)?.at,now))o.channels=[];
  return o;
}

function valid(p){
  if(!p || p.version!==1 || typeof p.kit!=='string'||!p.kit.trim()||!Array.isArray(p.mapping)||p.mapping.length!==4||
    !p.mapping.every(v=>Number.isInteger(v)&&v>=1&&v<=8)||new Set(p.mapping).size!==4||
    !Number.isInteger(p.mode)||p.mode<1||p.mode>8||!Number.isInteger(p.count)||p.count<4||p.count>8)return false;
  if(p.kind==='pulse')return p.channel===null;
  return p.kind==='marker'&&spareChannels(p).includes(p.channel)&&Math.max(p.mode,...p.mapping)<=p.count&&
    [p.on,p.off].every(v=>Number.isInteger(v)&&v>=900&&v<=2100)&&Math.abs(p.on-p.off)>=SEPARATION;
}
const matches=(o,p)=>valid(p)&&o.kit===p.kit&&o.mode===p.mode&&same(o.mapping,p.mapping);
export function classifyTx(o,p){
  if(!o.live||[1,2].includes(o.source))return result('inactive','INACTIVE','Physical PPM transmitter monitoring requires a live PPM source.','idle');
  if(o.source!==0||o.pulse===null)return result('waiting','WAITING','Waiting for current PPM status from the kit.');
  if(o.pulse===false)return result('off','NO PPM','The controller reports that PPM pulses are absent.');
  if(!matches(o,p)||p.count!==o.count)return result('unverified','UNVERIFIED','PPM pulses are present. A receiver can hold its last values when the radio is off.');
  if(p.kind==='pulse')return result('on','TX ON','PPM is present. This receiver stopped sending pulses during its verified OFF check.','good');
  if(!o.channels.length)return result('waiting','WAITING','Waiting for a fresh accepted CH'+p.channel+' value.');
  const [a,b]=o.channels.slice(-2);
  const read=r=>r?.values[p.channel-1];
  if(!b||!fresh(a.at,b.at)||a.at===b.at)return result('waiting','CHECKING','Confirming CH'+p.channel+' on a second frame.');
  if(band(read(a),p.off)&&band(read(b),p.off))return result('off','TX OFF','CH'+p.channel+' matches the verified OFF value ('+p.off+' µs).');
  if(band(read(a),p.on)&&band(read(b),p.on))return result('on','TX ON','CH'+p.channel+' matches the verified ON value ('+p.on+' µs).','good');
  if(band(read(b),p.on)||band(read(b),p.off))return result('waiting','CHECKING','Confirming a change in the receiver loss channel.');
  return result('unverified','UNKNOWN','CH'+p.channel+' is outside the verified ON and OFF ranges.');
}

function stable(rows,after,now){
  return rows.length>=SAMPLES&&rows[0].at>after&&fresh(rows.at(-1).at,now)&&rows.slice(1).every((r,i)=>r.at>rows[i].at&&fresh(rows[i].at,r.at));
}
export class TxCheck{
  constructor(channel=null){this.channel=channel;this.step=0;this.after=-Infinity;this.levels=[];}
  capture(o){
    if(this.step===3)throw Error('The check is complete.');
    if(!o.live||o.source!==0||o.armed!==false)throw Error('Connect a disarmed kit with PPM selected.');
    if(!o.kit.trim()||o.mapping.length!==4||o.mode==null)throw Error('Waiting for receiver settings and kit identity.');
    if(this.step&&(this.session!==o.session||this.kit!==o.kit||this.mode!==o.mode||!same(this.mapping,o.mapping)))throw Error('Connection or channel settings changed. Start over.');
    if(o.pulse===null||!stable(o.inputs,this.after,o.now)||!o.inputs.every(v=>v.pulse===o.pulse))throw Error('Hold this state for one second, then capture.');
    if(this.step!==1&&!o.pulse)throw Error('Switch the transmitter on and wait for PPM.');
    let level=null;
    if(o.pulse){
      if(o.inputs.some(v=>v.count!==o.count)||(this.step&&o.count!==this.count))throw Error('Receiver channel count changed.');
      if(this.channel!==null&&!(this.step===2&&this.levels[1]===null)){
        if(!spareChannels(o).includes(this.channel))throw Error('Choose an unused received AUX channel.');
        if(!stable(o.channels,this.after,o.now))throw Error('Waiting for fresh accepted channel samples.');
        const v=o.channels.map(r=>r.values[this.channel-1]).sort((a,b)=>a-b);
        if(v.at(-1)-v[0]>40)throw Error('Keep the dedicated AUX channel steady.');
        level=v[1];
      }
      if(this.step===1 && (level===null||Math.abs(level-this.levels[0])<SEPARATION))throw Error('PPM is still present. Configure a distinct receiver failsafe value on a spare channel.');
      if(this.step===2 && this.levels[1]!==null && !band(level,this.levels[0]))throw Error('Restore the original transmitter-on channel value.');
    }
    if(!this.step){this.session=o.session;this.kit=o.kit;this.mapping=o.mapping;this.mode=o.mode;this.count=o.count;}
    this.after=o.now;this.levels.push(level);this.step++;
    if(this.step<3)return null;
    const marker=this.levels[1]!==null;
    return {version:1,kit:this.kit,mapping:this.mapping,mode:this.mode,count:this.count,kind:marker?'marker':'pulse',channel:marker?this.channel:null,on:marker?this.levels[0]:null,off:this.levels[1]};
  }
}

const key=kit=>'areion.ppmRadio.v1.'+encodeURIComponent(kit);
export function mountTxEvidence(container){
  const create=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text)n.textContent=text;return n;};
  const badge=create('span','tx-evidence-badge','TX INACTIVE'),button=create('button','flight-action','Check transmitter');
  button.type='button';container.append(badge,button);
  const dialog=create('dialog','tx-evidence-dialog');document.body.append(dialog);
  dialog.setAttribute('aria-label','Check transmitter');
  dialog.innerHTML='<h2>Check transmitter</h2><p data-prompt></p><label>Receiver loss indication <select aria-label="Receiver loss indication"></select></label><p data-method></p><p data-reading></p><label><input type="checkbox"> Propellers removed. Kit disarmed.</label><p role="status" data-message></p><div class="flight-choices"><button type="button" data-capture>Capture ON</button><button type="button" data-save hidden>Save check</button><button type="button" data-restart>Start over</button><button type="button" data-forget>Forget saved check</button><button type="button" data-close>Close</button></div>';
  const find=q=>dialog.querySelector(q), selector=find('select'), props=find('input'),capture=find('[data-capture]'),save=find('[data-save]'),forget=find('[data-forget]'),message=find('[data-message]');
  let session,kit='',profile=null,check=new TxCheck(),candidate=null,ctx=null,identity='',methodKey=null,firstOpen=false;
  const start=()=>{check=new TxCheck(Number(selector.value)||null);candidate=null;message.textContent='';};
  const recalc=()=>ctx&&update(ctx,Math.max(ctx.clock,performance.now()));
  function update(c,clock=c.clock){
    ctx=c;
    const o=observeTx(c,clock);
    const changedKit=o.kit!==kit||session!==o.session;
    if(changedKit){
      session=o.session;kit=o.kit;profile=null;start();props.checked=false;methodKey=null;identity='';
      if(kit){try{const p=JSON.parse(localStorage.getItem(key(kit)));if(valid(p)&&p.kit===kit)profile=p;}catch{/* storage may be unavailable */}}
    }
    const tx=classifyTx(o,profile);
    const label=tx.label==='NO PPM'&&matches(o,profile)&&profile.kind==='pulse'?'TX OFF · NO PPM':tx.label.startsWith('TX ')?tx.label:'TX '+tx.label;
    if(badge.textContent!==label)badge.textContent=label;
    if(badge.title!==tx.detail)badge.title=tx.detail;
    if(badge.dataset.tone!==tx.level)badge.dataset.tone=tx.level;
    if(dialog.open){
      const current=[o.source,o.armed,o.mapping.join('/'),o.mode].join(':');
      if(identity&&identity!==current){start();props.checked=false;methodKey=null;}
      identity=current;
      const eligible=o.live&&o.source===0&&o.armed===false&&Boolean(kit);
      if(!check.step){
        const spare=spareChannels(o), id=spare.join(',');
        if(id!==methodKey||firstOpen){
          const preferred=firstOpen?(profile ? profile.channel : 6):Number(selector.value)||null;
          selector.replaceChildren(new Option('PPM pulses stop','0'),...spare.map(ch=>new Option('CH'+ch+' failsafe value',String(ch))));
          selector.value=spare.includes(preferred)?String(preferred):'0';
          methodKey=id;firstOpen=false;start();
        }
      }
      const ch=Number(selector.value), reading=o.channels.at(-1)?.values[ch-1];
      find('[data-method]').textContent=ch?'Reserve CH'+ch+'. Keep its transmitter-on value fixed and set the receiver failsafe at least 300 µs away.':'Choose this if the receiver stops PPM pulses when the transmitter switches off.';
      selector.disabled=!eligible||check.step>0;props.disabled=!eligible;
      const prompts=['Transmitter ON. Keep throttle low and sticks still.','Switch the transmitter OFF. Keep the receiver and kit powered.','Switch the transmitter back ON. Restore the original stick and switch positions.','Save this receiver check for this kit in this browser.'];
      find('[data-prompt]').textContent=!eligible?'Connect the disarmed kit with PPM selected to start.':prompts[check.step];
      find('[data-reading]').textContent=o.pulse===false?'No PPM pulses':o.pulse===true?(Number.isFinite(reading)?'CH'+ch+' · '+reading+' µs':'PPM pulses present'):'Waiting for PPM evidence';
      capture.textContent=['Capture ON','Capture OFF','Capture restored link','Complete'][check.step];capture.hidden=check.step===3;save.hidden=!candidate;
      capture.disabled=!eligible||!props.checked;save.disabled=!eligible||!props.checked;forget.disabled=!eligible||!profile;
    }
    return tx;
  }
  function open(context=ctx){
    if(context)update(context);
    if(dialog.open)return;
    firstOpen=true;props.checked=false;start();dialog.showModal();recalc();
  }
  button.onclick=()=>open();
  selector.onchange=()=>{start();recalc();};props.onchange=()=>{if(!props.checked)start();recalc();};
  capture.onclick=()=>{if(!ctx||!props.checked)return;const now=Math.max(ctx.clock,performance.now());try{candidate=check.capture(observeTx(ctx,now));message.textContent='';}catch(e){message.textContent=e.message;}update(ctx,now);};
  save.onclick=()=>{if(!ctx||!props.checked||!candidate)return;try{
    const o=observeTx(ctx,Math.max(ctx.clock,performance.now()));
    if(o.session!==check.session||o.armed!==false||classifyTx(o,candidate).code!=='on')throw Error('Reconnect the same disarmed kit with the transmitter on.');
    localStorage.setItem(key(kit),JSON.stringify(candidate));profile=candidate;dialog.close();recalc();
  }catch(e){message.textContent='Could not save. '+e.message;}};
  forget.onclick=()=>{if(!ctx||!profile)return;const o=observeTx(ctx,Math.max(ctx.clock,performance.now()));
    if(o.armed!==false||!o.live||o.kit!==kit)return;
    try{localStorage.removeItem(key(kit));profile=null;start();message.textContent='Saved receiver check removed.';recalc();}catch{message.textContent='Browser storage is unavailable.';}};
  find('[data-restart]').onclick=()=>{start();recalc();};
  find('[data-close]').onclick=()=>dialog.close();
  return {open,isOpen:()=>dialog.open,update,reset(){session=null;kit='';profile=null;ctx=null;identity='';props.checked=false;start();if(dialog.open)dialog.close();}};
}
