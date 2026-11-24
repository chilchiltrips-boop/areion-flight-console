import {escPrerequisite,markEsc} from './esc-progress.js';
import {defaults,equal,receiverValues,throttleWindow,saveFlightInput,SetupKit} from './config-commands.js';

const checked=(id,text)=>'<label class="cfg-check"><input type="checkbox" data-confirm="'+id+'"> '+text+'</label>';
const act=(key,label)=>'<button type="button" class="cfg-btn" data-kit="'+key+'">'+label+'</button>';
const range={2:[[0,100],[0,100],[0,100],[0,500],[0,500],[0,500],[0,20],[0,20],[0,20]],
  3:[[0,100],[0,100],[0,500],[0,500],[0,20],[0,20]],4:[[1001,1200],[1700,2000],[1000,1300],[1,200],[1,15],[1,10],[1,300]],
  7:[[1,8],[.01,.3],[.01,1],[.01,1],[0,1],[0,1]],112:[[50,1000],[100,500]],134:[[0,3],[0,2],[1,8],[1,8],[1,8],[1,8],[0,50],[1000,1500],[1000,1500],[1000,1500],[1000,1500]]};
const choices={source:['PPM receiver','AP Wi-Fi','USB'],mode:['Angle','Rate / Acro'],ch:Array.from({length:8},(_,i)=>'CH'+(i+1))};
export function editor(group,index,title,options,base=0){
  const data=' data-field="'+group+':'+index+'" aria-label="'+title+'"';
  const [min,max]=range[group]?.[index]||[0,1];
  const step=group===2||group===3||(group===7&&index>0&&index<4)?'.001':'1';
  return options?'<select'+data+'>'+options.map((label,i)=>'<option value="'+(i+base)+'">'+label+'</option>').join('')+'</select>':
    '<input type="number"'+data+' min="'+min+'" max="'+max+'" step="'+step+'">';
}
const field=(label,el)=>'<label class="cfg-edit"><span>'+label+'</span>'+el+'</label>';
const ch=(g,i,name)=>field(name,editor(g,i,name,choices.ch,1));
const num=(g,i,name)=>field(name,editor(g,i,name));
export const extras={
  begin:(label='Begin / resume kit setup')=>act('begin',label),
  reset:()=>checked('reset','Erase all kit settings and restore defaults.')+act('reset','Reset all kit settings'),
  source:()=>field('Flight input',editor(134,1,'Flight input',choices.source))+act('source','Save input'),
  profile:()=>act('profile','Save aircraft profile'),
  mapping:()=>['Roll','Pitch','Throttle','Yaw'].map((t,i)=>ch(134,i+2,t)).join('')+num(134,6,'Stick deadband (µs)'),
  receiver:()=>checked('receiver','Channel directions verified, throttle low and sticks centered.')+act('receiver','Save receiver calibration'),
  reverse:i=>'<input type="checkbox" data-field="132:'+(i*4+3)+'" aria-label="Reverse CH'+(i+1)+'">',
  esc:()=>'<p data-esc-guide aria-live="polite"></p>'+
    '<div data-esc-control="redo" hidden>'+checked('redo','Recalibrate ESCs and repeat motor-output checks.')+'</div>'+
    '<div data-esc-control="schedule" hidden>'+checked('compatible','My ESC supports PWM endpoint calibration.')+act('schedule','Schedule next startup')+
    checked('skip','My ESC does not need endpoint calibration.')+act('skip','Skip endpoint calibration')+'</div>'+
    '<div data-esc-control="verify" hidden>'+checked('tones','I heard the expected ESC response.')+act('verify-esc','Confirm ESC response')+'</div>'+
    '<div data-esc-control="cancel" hidden>'+act('stop-esc','Cancel ESC sequence')+'</div>',
  motors:()=>checked('frame','Propellers removed and frame secured.')+checked('battery','LiPo connected and polarity checked.')+
    '<label class="cfg-edit">Output <select data-mask aria-label="Motor output">'+['M1','M2','M3','M4','All four'].map((s,i)=>'<option value="'+[1,2,4,8,15][i]+'">'+s+'</option>').join('')+'</select></label>'+
    act('motor-start','Start test')+act('motor-stop','Stop')+
    '<label class="cfg-edit">Test pulse <output data-pulse-read>1000 µs</output><input type="range" min="1000" max="1500" value="1000" data-pulse aria-label="Test pulse"></label>'+
    act('record-min','Record starting pulse')+checked('direction','I verified motor position and rotation.')+act('motor-confirm','Save idle & confirm motors'),
  arming:()=>['Low throttle (µs)','Yaw right (µs)','Yaw left (µs)','Throttle movement (µs)','Arm hold (s)','Disarm hold (s)','Idle auto-disarm (s)'].map((title,i)=>num(4,i,title)).join('')+num(112,0,'PPM loss timeout (ms)')+num(112,1,'Digital loss timeout (ms)'),
  modes:()=>ch(7,0,'Flight mode channel')+['Low position','High position'].map((title,i)=>field(title,editor(7,i+4,title,choices.mode))).join('')+act('arming','Save arming & flight modes'),
  finalize:()=>checked('final','Checks reviewed, propellers removed and motors stopped.')+act('final','Save & finish'),
  verify:()=>act('restart','Verify after restart'),
  pid:g=>act('pid-'+g,'Save '+(g===2?'rate':'angle')+' PID to FC'),
  response:()=>['Angle stick scale','Rate stick scale','Yaw stick scale'].map((s,i)=>num(7,i+1,s)).join('')+act('response','Save stick settings in setup'),
};
const receiptKey=id=>'areion.setup.receipt.'+id;
const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));

export class ConfigPanel {
  constructor(root,local){
    this.root=root;this.local=local;this.draft=new Map();this.base=new Map();this.confirm=new Set();this.knownKit=null;
    this.pendingMotorStop=null;this.status='';this.epoch=0;this.busy=false;this.entered=false;this.mask=1;this.pulse=1000;this.minima=new Map();
    root.addEventListener('input',e=>this.edit(e.target));
    root.addEventListener('change',e=>this.edit(e.target));
    root.addEventListener('click',e=>{
      const button=e.target.closest('button[data-kit]');if(button&&!button.disabled)this.run(button.dataset.kit);
    });
  }
  edit(node){
    if(node.closest?.('[data-tripod]'))return;
    if(node.hasAttribute('data-confirm')){
      const key=node.dataset.confirm;if(node.checked)this.confirm.add(key);else this.confirm.delete(key);
      if(['frame','battery'].includes(key)&&!node.checked)this.stopMotor();
    }
    if(node.hasAttribute('data-field')){
      const [g,i]=node.dataset.field.split(':').map(Number);
      if(!this.base.has(g)&&this.ctx?.group(g))this.base.set(g,[...this.ctx.group(g)]);
      const v=node.type==='checkbox'?Number(node.checked):node.value===''?NaN:Number(node.value);
      this.draft.set(g+':'+i,v);
      if((g===2||g===3)&&this.confirm.has('axis-'+g)){
        const n=g===2?3:2,axis=i%n;
        if(axis<2)this.draft.set(g+':'+(axis===0?i+1:i-1),v);
      }
      if(g===134&&i>=2&&i<6)this.local.clearReceiver();
    }
    if(node.hasAttribute('data-mask')){this.stopMotor();this.mask=Number(node.value);this.confirm.delete('direction');}
    if(node.hasAttribute('data-pulse')){this.pulse=clamp(Number(node.value),1000,1500);this.pulseDisplay();}
    if(this.ctx)this.refresh(this.ctx);
  }
  fresh(group){return this.ctx?.model.get(group,performance.now(),500);}
  get armed(){return this.fresh(120)?.[0];}
  get live(){return this.ctx?.link?.session && this.ctx.state==='connected'&&!this.ctx.replay;}
  get lock(){const s=this.fresh(130);return this.entered&&s?.[0]&&!s[1]&&s[2]>0;}
  get safe(){return this.live && this.armed===false && this.local.state().confirmed;}
  pulseDisplay(){const out=this.root.querySelector('[data-pulse-read]');if(out)out.textContent=this.pulse+' µs';}
  info(text,bad=false){this.status=text;this.bad=bad;const slot=this.root.querySelector('[data-operation]');if(slot){slot.textContent=text;slot.classList.toggle('cfg-error',bad);}}
  suspend({emergency=false}={}){
    this.epoch++;this.busy=false;const stopped=this.stopMotor(emergency);
    if(this.status==='Working…')this.info('Action interrupted. Read the kit before retrying.',true);
    this.confirm.clear();this.local.clearCaptures();
    return stopped;
  }
  pageChange(){this.suspend();this.info('');}
  reset(){this.suspend();this.entered=false;this.ctx=null;this.draft.clear();this.base.clear();this.minima.clear();this.knownKit=null;}
  stopMotor(skipCommand=false){
    const motor=this.motor;this.motor=null;this.pulse=1000;
    if(motor){clearInterval(motor.timer);
      if(!skipCommand && motor.session===motor.link.session){
        const request=motor.link.action(135,['MOTOR_STOP',0,0,0,0])
          .then(ack=>{if(ack[0]!=='STOPPED')throw Error('Unexpected controller reply.');})
          .catch(error=>this.info('Motor STOP unconfirmed: '+error.message,true))
          .finally(()=>{if(this.pendingMotorStop===request)this.pendingMotorStop=null;});
        this.pendingMotorStop=request;
      }
    }
    const slide=this.root.querySelector('[data-pulse]');if(slide)slide.value='1000';this.pulseDisplay();
    return this.pendingMotorStop;
  }
  motorOk(){
    const s=this.fresh(130);
    return this.safe&&this.lock&&this.confirm.has('frame')&&this.confirm.has('battery')&&s?.[5]&&[4,5].includes(s[3])&&this.fresh(120)?.[2]&&this.fresh(21)&&!this.root.hidden&&!document.hidden;
  }
  startMotor(op){
    if(!this.motorOk())throw Error('Confirm the battery, frame and controller checks.');
    const mask=this.mask;this.pulse=1000;
    const motor={link:op.link,session:op.session,mask,started:performance.now(),sending:false,ready:false};this.motor=motor;
    return (async()=>{
      try{
        const ack=await op.call('action',135,['MOTOR_START',mask,1,0,0]);
        if(ack[0]!=='MOTOR_TEST_STARTED')throw Error('Motor test start unconfirmed.');
        if(this.motor!==motor||!this.motorOk())throw Error('Motor start interrupted.');
        motor.ready=true;
        const tick=async()=>{
          if(this.motor!==motor)return;
          if(!this.motorOk()||performance.now()-motor.started>=30000){this.stopMotor();this.info('Motor test stopped.');return;}
          if(motor.sending)return;
          motor.sending=true;
          try{
            const ack=await motor.link.action(135,['MOTOR_SET',mask,this.pulse,0,0]);
            if(ack[0]!=='MOTOR_TEST_UPDATED')throw Error('Motor output unconfirmed.');
          }catch(error){if(this.motor===motor){this.stopMotor();this.info(error.message,true);}}
          finally{motor.sending=false;}
        };
        motor.timer=setInterval(tick,100);return 'Motor test active. Start at minimum.';
      }catch(error){if(this.motor===motor)this.stopMotor();throw error;}
    })();
  }
  snapshot(group,active,indices=null){
    const copy=[...active];
    for(let i=0;i<copy.length;i++)if((!indices||indices.includes(i))&&this.draft.has(group+':'+i)){
      if(this.base.has(group)&&!equal([this.base.get(group)[i]],[active[i]]))throw Error('Kit settings changed. Reload the current settings.');
      copy[i]=this.draft.get(group+':'+i);
    }
    return copy;
  }
  clearFields(g,indices){for(const i of indices)this.draft.delete(g+':'+i);if(!Array.from(this.draft.keys()).some(k=>k.startsWith(g+':')))this.base.delete(g);}
  async saveEdits(op,g,indices){
    const before=await op.read(g);
    await op.store(g,this.snapshot(g,before,indices),before);this.clearFields(g,indices);
  }
  receiverPreview(){
    const ctx=this.ctx,a=this.local.state(),raw=this.fresh(131),cfg=ctx?.group(134),cal=ctx?.group(132);
    const at=ctx?.model.frames.get(131)?.at,timeout=ctx?.group(112)?.[0],limit=ctx?.group(4)?.[0];
    if(!cfg||cfg[1]!==0||!raw?.[9]||!Number.isFinite(at)||!(raw[10]+ctx.clock-at<timeout))
      return {message:'Waiting for fresh PPM from the selected receiver.'};
    if(!cal||!Number.isFinite(limit))return {message:'Reading receiver settings from the kit.'};
    let label;
    try {
      const mapped=this.snapshot(134,cfg,[2,3,4,5,6]).slice(2,6),direction=this.snapshot(132,cal);
      const throttle=throttleWindow(a.endpoints,raw,direction,mapped[2],limit);
      label=throttle?.label;
      if(a.rxRun)return {label,message:'Sweep every axis, then choose Stop capture.'};
      if(!a.endpoints&&!this.fresh(130)?.[6])return {label,message:'Choose Capture range to measure stick travel.'};
      if(throttle&&!throttle.ready)return {label,message:'Move throttle to its low endpoint. Keep this captured range.'};
      if(a.endpoints)receiverValues(a.endpoints,raw,direction,mapped,limit);
      if(!throttle)return {label,message:'Capture the full throttle range.'};
      const flight=ctx.group(7);
      if(!flight||new Set([...mapped,flight[0]]).size!==5||flight[0]>raw[8])return {label,message:'Assign separate, available channels to each axis and flight mode.'};
      return {label,ready:true,message:'Hold throttle low, release roll, pitch and yaw to centre, then save.'};
    }catch(error){return {label,message:error.message};}
  }
  allowed(key){
    const s=this.fresh(130),cfg=this.ctx?.group(134),a=this.local.state(),check=k=>this.confirm.has(k);
    if(key==='motor-stop')return Boolean(this.motor||s?.[8])&&this.live;
    if(key==='stop-esc')return this.live && s && [1,2].includes(s[3]);
    if(this.busy||this.pendingMotorStop||this.motor && key!=='record-min')return false;
    if(/^(read|saved|revert)-[23]$/.test(key))return this.live;
    if(key==='pid-2'||key==='pid-3')return this.live&&this.armed===false&&Boolean(this.ctx.group(Number(key.slice(-1))));
    if(key==='source'&&a.page!=='wizard')return this.live&&this.armed===false&&cfg;
    if(key==='restart')return this.live&&this.armed===false;
    if(!this.safe)return false;
    if(key==='begin')return !this.lock;
    if(!this.lock)return false;
    switch(key){
      case 'reset':return check('reset');
      case 'start-sensor':return this.local.sensorVisible() && !this.local.calibration.sensor.active &&
        !this.local.calibration.gate(this.ctx,this.local.sensorControls());
      case 'retry-sensor':return this.local.sensorVisible() && this.local.calibration.sensor.needsRetry &&
        !this.local.calibration.gate(this.ctx,this.local.sensorControls());
      case 'imu':return this.local.sensorVisible() && this.local.calibration.ready(this.ctx,this.local.sensorControls());
      case 'receiver':return check('receiver')&&!a.rxRun&&cfg?.[1]===0&&this.receiverPreview().ready;
      case 'schedule':case 'skip':return !escPrerequisite(s,cfg)&&([0,6].includes(s[3])||[4,5].includes(s[3])&&check('redo'))&&check(key==='schedule'?'compatible':'skip');
      case 'verify-esc':return s[3]===3&&check('tones')&&this.fresh(21)&&this.fresh(120)?.[2];
      case 'motor-start':return !s[8]&&this.motorOk();
      case 'record-min':return this.motor?.ready;
      case 'motor-confirm':return check('direction')&&!s[8]&&[0,1,2,3].every(i=>!(this.mask&(1<<i))||this.minima.has(i));
      case 'final':return !this.local.calibration.pending&&check('final')&&s[5]&&(cfg?.[1]!==0||s[6])&&[4,5].includes(s[3])&&s[4]===15&&!s[8];
      default:return true;
    }
  }
  refresh(ctx){
    this.ctx=ctx;const kit=ctx.group(130)?.[15];
    if(kit&&this.knownKit&&this.knownKit!==kit)this.reset();
    this.ctx=ctx;if(kit)this.knownKit=kit;
    this.info(this.status,this.bad);
    for(const el of this.root.querySelectorAll('[data-field]')){
      const [g,i]=el.dataset.field.split(':').map(Number),v=this.draft.get(el.dataset.field)??ctx.group(g)?.[i]??(this.local.state().page==='pid'?defaults[g]?.[i]:null);
      if(el.type==='checkbox')el.checked=Boolean(v);else if(document.activeElement!==el)el.value=Number.isFinite(v)?String(Number(v.toFixed(6))):'';
      el.disabled=!this.live||v==null||this.busy||Boolean(this.motor)||([2,3].includes(g)&&this.armed!==false);
    }
    const receiverHint=this.root.querySelector('[data-rx-guide]');
    if(receiverHint){
      const preview=this.receiverPreview(),reading=this.root.querySelector('[data-rx-throttle]');
      receiverHint.textContent=preview.message;reading.textContent=preview.label||'—';
    }
    for(const el of this.root.querySelectorAll('[data-confirm]'))el.checked=this.confirm.has(el.dataset.confirm);
    for(const el of this.root.querySelectorAll('button[data-kit]'))el.disabled=!this.allowed(el.dataset.kit);
    const mask=this.root.querySelector('[data-mask]');if(mask)mask.value=String(this.mask);
    const slider=this.root.querySelector('[data-pulse]');if(slider)slider.disabled=!this.motor?.ready;
    this.pulseDisplay();
  }
  async run(key){
    if(!this.allowed(key))return;
    const record=this.ctx?.diagnosticScope?.();
    const trace=(status,detail,values)=>record?.({kind:'operation',name:key,status,detail,values});
    trace('started');

    if(key==='motor-stop'||key==='stop-esc'){
      const hadMotor=!!this.motor;this.epoch++;this.busy=false;this.stopMotor(true);
      try{await this.ctx.link.action(135,[key==='motor-stop'?'MOTOR_STOP':'STOP',0,0,0,0]);const detail=hadMotor?'Motor test stopped.':'Stop acknowledged.';this.info(detail);trace('ok',detail);}
      catch(error){this.info('Stop unconfirmed: '+error.message,true);trace('error',error.message);}return;
    }
    if(key==='record-min'){
      for(let i=0;i<4;i++)if(this.mask&(1<<i))this.minima.set(i,this.pulse);
      this.info('Starting pulse recorded: '+this.pulse+' µs. Stop and verify rotation.');trace('ok','Starting pulse recorded',{mask:this.mask,pulse_us:this.pulse});return;
    }
    const token=++this.epoch, link=this.ctx.link,guard=()=>{
      if(token!==this.epoch||this.root.hidden||document.hidden||this.ctx?.link!==link||!this.live)throw Error('Action cancelled or kit disconnected.');
    };
    const op=new SetupKit(link,guard);this.busy=true;this.info('Working…');this.refresh(this.ctx);
    try{
      const result=await this.perform(key,op);
      guard();const detail=result||'Saved and verified on the kit.';this.info(detail);
      trace('ok',detail,key==='final'||key==='restart'?this.receipt:undefined);
      if(key==='receiver')this.local.receiverVerified?.();
    }catch(error){trace(token===this.epoch?'error':'interrupted',error.message);if(token===this.epoch)this.info(error.message,true);}
    finally{if(token===this.epoch){this.busy=false;if(this.ctx)this.refresh(this.ctx);}}
  }
  async perform(key,op){
    const a=this.local.state();
    if(/^(read|saved|revert)-[23]$/.test(key)){
      const [kind,id]=key.split('-'),g=Number(id),active=await op.read(g);
      this.clearFields(g,active.map((_,i)=>i));
      if(kind==='saved'){
        const saved=await op.read(g,true);this.base.set(g,active.slice());saved.forEach((v,i)=>this.draft.set(g+':'+i,v));
        return 'Stored gains loaded into the editor.';
      }
      return 'Active controller gains loaded.';
    }
    switch(key){
      case 'begin':await op.begin();this.entered=true;return 'Setup lock verified. Flight arming is blocked.';
      case 'reset':await op.reset();markEsc(this.knownKit,false);this.local.resetDraft();this.draft.clear();this.base.clear();this.minima.clear();this.confirm.clear();return 'Factory defaults saved and verified. Setup remains locked.';
      case 'source':{
        const selected=this.snapshot(134,await op.read(134),[1])[1];
        await saveFlightInput(op.link,selected,{wizard:a.page==='wizard',guard:()=>op.check()});
        this.clearFields(134,[1]);return 'Flight input saved and verified.';
      }
      case 'profile':{
        const cfg=await op.read(134);
        if(cfg[0]!==a.profile){
          await op.store(134,[a.profile,...cfg.slice(1)],cfg);
          await op.store(2,defaults[2]);await op.store(3,defaults[3]);
        }
        return 'Aircraft profile verified.';
      }
      case 'start-sensor':{
        const setup=await op.sensorState();
        const base=await op.read(6),reason=this.local.calibration.gate(this.ctx,this.local.sensorControls());
        if(reason||!this.local.sensorVisible())throw Error(reason||'Reopen the sensor calibration page.');
        this.local.calibration.start(this.ctx,base,setup[15],performance.now());
        return 'Automatic capture started.';
      }
      case 'retry-sensor':{
        await op.sensorState();
        await op.read(6);
        op.check();
        if (!this.local.sensorVisible()) throw Error('Reopen the sensor calibration page.');
        this.local.calibration.retry(this.ctx,this.local.sensorControls());
        return 'Capturing highlighted faces.';
      }
      case 'imu':{
        await this.local.calibration.save(op,this.ctx,this.local.sensorControls());
        return 'Accelerometer offsets and sensor check saved and verified on the kit.';
      }
      case 'receiver':{
        const before=await op.read(134),indices=[2,3,4,5,6],cfg=this.snapshot(134,before,indices),map=cfg.slice(2,6),f=await op.read(7);
        if(new Set([...map,f[0]]).size!==5)throw Error('Choose distinct channels for four axes and flight mode.');
        const base=await op.read(132),withDirection=this.snapshot(132,base);
        const limit=(await op.read(4))[0],timeout=(await op.read(112))[0],raw=await op.read(131);
        if(!raw[9]||raw[10]>=timeout)throw Error('Fresh PPM required.');
        const values=a.endpoints?receiverValues(a.endpoints,raw,withDirection,map,limit):withDirection;
        const throttle=throttleWindow(null,raw,values,map[2],limit);
        if(!throttle?.ready)throw Error('Lower the throttle before finishing. '+(throttle?.label??''));
        await op.store(134,cfg,before);await op.store(132,values,base);
        await op.checkedAction('RX_OK',[1,0,0,0],s=>s[6]);
        this.clearFields(134,indices);this.clearFields(132,Array.from({length:32},(_,i)=>i));return 'Receiver calibration saved and verified.';
      }
      case 'schedule':await op.escAction('ESC_SCHEDULE',this.confirm.has('redo'));markEsc(this.knownKit,true);this.confirm.delete('redo');this.confirm.delete('compatible');this.confirm.delete('tones');return 'Scheduled for the next kit startup.';
      case 'verify-esc':await op.escAction('ESC_VERIFY');return 'ESC response verified.';
      case 'skip':await op.escAction('ESC_SKIP',this.confirm.has('redo'));this.confirm.delete('redo');this.confirm.delete('skip');return 'ESC calibration skip saved.';
      case 'motor-start':await op.locked();return this.startMotor(op);
      case 'motor-confirm':{
        const mask=this.mask,before=await op.read(134),values=[...before];
        for(let i=0;i<4;i++)if(mask&(1<<i))values[7+i]=this.minima.get(i);
        await op.store(134,values,before);await op.checkedAction('MOTOR_OK',[mask,1,0,0],s=>(s[4]&mask)===mask);return 'Motor verification saved.';
      }
      case 'arming':{
        const cfg=await op.read(134),flight=this.snapshot(7,await op.read(7),[0,4,5]);
        if(cfg.slice(2,6).includes(flight[0])||flight[4]===flight[5])throw Error('Choose a separate flight mode channel and distinct low/high modes.');
        await this.saveEdits(op,4,[0,1,2,3,4,5,6]);await this.saveEdits(op,7,[0,4,5]);await this.saveEdits(op,112,[0,1]);return;
      }
      case 'response':await this.saveEdits(op,7,[1,2,3]);return;
      case 'pid-2':case 'pid-3':{
        const g=Number(key.slice(-1)),before=await op.read(g),values=this.snapshot(g,before);
        const message=await op.pid(g,values,false);this.clearFields(g,values.map((_,i)=>i));return message;
      }
      case 'final':{
        const receipt=await op.finalize();markEsc(receipt.kit,false);this.receipt=receipt;this.entered=false;this.confirm.clear();
        try{localStorage.setItem(receiptKey(receipt.kit),JSON.stringify(receipt));}catch{/* available for this tab */}
        return 'Setup saved and verified. Arming is available.';
      }
      case 'restart':{
        let receipt=this.receipt;
        if(receipt?.kit!==this.knownKit)try{receipt=JSON.parse(localStorage.getItem(receiptKey(this.knownKit)));}catch{receipt=null;}
        await op.verifyRestart(receipt);this.receipt=receipt;return 'Restart verified. Active and stored settings match.';
      }
    }
  }
}
