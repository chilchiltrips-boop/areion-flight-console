// Extracted from the supplied V18.3.82 shared-ui reference.
// Each feature receives the project's shared runtime explicitly.
import {wiresForStep} from './wiring-preview.js';

export function register(ctx) {
ctx.product = t=>ctx.products.find(x=>x.type===t);

ctx.showInspector = function showInspector(title,detail,rating={},pins=[],kind='PRODUCT',asset=''){ ctx.$('#inspector').innerHTML=`<div class="type">${kind}</div><h3>${title}</h3><p>${detail}</p><div class="specs">${Object.entries(rating).map(([k,v])=>`<div class="spec"><b>${k}</b><span>${v}</span></div>`).join('')}</div><table class="pin-table">${pins.map(p=>`<tr><td>${p[0]}</td><td>${p[1]}</td></tr>`).join('')}</table>${asset?`<div class="asset-path">3D asset: ${asset}</div>`:''}` };

ctx.notify = function notify(text, kind = 'good') {
 const message = ctx.$('#snapMessage');
 clearTimeout(notify.timer);
 message.textContent = text;
 message.className = 'snap-message ' + kind;
 notify.timer = setTimeout(() => {
   if (message.textContent === text) message.textContent = '';
 }, 2600);
};

ctx.renderShelf = function renderShelf(){
 const b=ctx.$('#componentShelf');b.innerHTML='';
 const stepRank=t=>{const i=ctx.steps.findIndex(s=>s.types.includes(t));return i<0?999:i};
 const required=ctx.products.filter(c=>!c.optional&&!c.internal&&ctx.state.parts.filter(p=>p.type===c.type).length<c.max).sort((a,b)=>stepRank(a.type)-stepRank(b.type));
 const optional=ctx.products.filter(c=>c.optional&&!c.internal&&ctx.state.parts.filter(p=>p.type===c.type).length<c.max);
 const addCard=(c)=>{
   const n=ctx.state.parts.filter(p=>p.type===c.type).length,left=c.max-n,e=document.createElement('div');
   e.className='product-card'+(c.optional?' optional-product':'')+(ctx.state.selectedType===c.type?' selected':'')+(ctx.steps[ctx.state.step]?.types.includes(c.type)?' current-part':'');e.setAttribute('role','button');e.tabIndex=0;
   e.draggable=true;const batch=(c.type==='frameScrew'||c.type==='motorScrew');
   const img=c.thumb?`<img class="product-thumb" src="${c.thumb}" alt="${c.name} preview">`:`<div class="product-fallback">${c.icon}</div>`;
   e.innerHTML=`${img}<div><b>${c.name}</b><span>${c.short}</span>${batch?'<small class="one-drag-note">ONE DRAG installs complete set</small>':''}${c.optional?'<em class="optional-badge">OPTIONAL / EXPANSION</em>':''}</div><i class="count-badge">${left} left</i><em class="model-tag">${c.asset?'3D MODEL':'VIRTUAL PART'}</em>`;
   const thumb=e.querySelector('.product-thumb');if(thumb)thumb.onerror=()=>{const f=document.createElement('div');f.className='product-fallback';f.textContent=c.icon;thumb.replaceWith(f)};
   e.onclick=()=>ctx.selectProduct(c.type);e.onkeydown=x=>{if(x.key==='Enter'||x.key===' '){x.preventDefault();ctx.selectProduct(c.type)}};e.ondragstart=x=>{x.dataTransfer.setData('text/plain',c.type);ctx.state.selectedType=c.type};b.appendChild(e)
 };
 if(required.length){const h=document.createElement('div');h.className='shelf-group-title';h.textContent='REQUIRED • ASSEMBLY ORDER';b.appendChild(h);required.forEach(addCard)}
 else {const h=document.createElement('div');h.className='shelf-complete';h.textContent='✓ Required physical assembly parts installed. Optional expansion devices remain below.';b.appendChild(h)}
 const oh=document.createElement('div');oh.className='shelf-group-title';oh.textContent='OPTIONAL • PPM / GPIO / I²C EXPANSION';b.appendChild(oh);optional.forEach(addCard)
};

ctx.selectProduct = function selectProduct(type){
 const c=ctx.product(type);if(!c)return;if(c.asset&&!ctx.assetsReady){ctx.notify('Component models are still loading • try again when 3D engine shows ready.','bad');return}
 if(c.optional&&!ctx.state.parts.some(p=>p.type==='fc')){ctx.notify('Mount Areion FC A1 to unlock the virtual expansion devices.','bad');return}
 if(!c.optional&&ctx.state.guided&&!ctx.steps[ctx.state.step].types.includes(type)){ctx.notify(`Current step needs ${ctx.steps[ctx.state.step].types.map(t=>ctx.product(t)?.name).filter(Boolean).join(' / ')||'a connection action'}.`,'bad');return}
 if(ctx.state.parts.filter(p=>p.type===type).length>=c.max){ctx.notify('Required quantity already installed.','bad');return}
 ctx.state.selectedType=type;ctx.playFX('pick');ctx.renderShelf();ctx.showInspector(c.name,c.detail,c.rating,c.pins,c.optional?'OPTIONAL DEVICE':'PRODUCT',c.asset||'')
};

ctx.wiringActionIds = new Set(['motorWire','powerWire','escFc','xt60']);

ctx.pairPresent = function pairPresent(a,b){return ctx.state.connections.some(c=>(c.from===a&&c.to===b)||(c.from===b&&c.to===a))};

ctx.partQty = function partQty(type){return ctx.state.parts.filter(p=>p.type===type).length};

ctx.wiringPrerequisitesReady = function wiringPrerequisitesReady(id){
 if(id==='motorWire')return ctx.partQty('esc')>=4&&ctx.partQty('motor')>=4;
 if(id==='powerWire')return ctx.partQty('bottomPlate')>=1&&ctx.partQty('esc')>=4;
 if(id==='escFc')return ctx.partQty('fc')>=1&&ctx.partQty('esc')>=4;
 if(id==='xt60')return ctx.partQty('bottomPlate')>=1&&ctx.partQty('battery')>=1;
 return true
};

ctx.wiringStepProgress = function wiringStepProgress(id){
 if(id==='motorWire'){let n=0;for(let i=1;i<=4;i++){for(const p of ['U','V','W'])if(ctx.state.connections.some(c=>{const a=c.from.split('.'),b=c.to.split('.');return(a[0]===`ESC${i}`&&a[1]===p&&b[0]===`M${i}`&&['U','V','W'].includes(b[1]))||(b[0]===`ESC${i}`&&b[1]===p&&a[0]===`M${i}`&&['U','V','W'].includes(a[1]))}))n++}return n}
 return wiresForStep(ctx,id).filter(([a,b])=>ctx.pairPresent(a,b)).length
};

ctx.wiringActionReady = function wiringActionReady(id){
 if(!ctx.wiringPrerequisitesReady(id))return false;
 if(id==='motorWire')return [1,2,3,4].every(i=>ctx.phaseMap(i));
 if(id==='powerWire')return ctx.wiringStepProgress(id)>=8;
 if(id==='escFc')return ctx.wiringStepProgress(id)>=12;
 if(id==='xt60')return ctx.wiringStepProgress(id)>=2;
 return false
};

ctx.syncWiringActionsToAssembly = function syncWiringActionsToAssembly(){
 let changed=false;
 for(const id of ctx.wiringActionIds){const ready=ctx.wiringActionReady(id),has=ctx.state.doneActions.has(id);if(ready&&!has){ctx.state.doneActions.add(id);changed=true}else if(!ready&&has){ctx.state.doneActions.delete(id);changed=true}}
 if (ctx.state.doneActions.has('inspect') && !ctx.inspectionReady()) {
   ctx.state.doneActions.delete('inspect');
   changed=true;
 }
 const xt=ctx.wiringActionReady('xt60');if(xt!==ctx.state.powered)ctx.setPowerVisual(xt,true);
 return changed
};

ctx.inspectionReady = () => ctx.steps.every((step,i) => step.id==='inspect' || ctx.stepDone(i)) &&
 !ctx.electricalIssues().some(issue=>issue.level==='bad');
ctx.countStep = function countStep(s){if(s.id==='inspect')return ctx.state.doneActions.has('inspect') && ctx.inspectionReady()?s.need:0;if(ctx.wiringActionIds.has(s.id))return ctx.wiringStepProgress(s.id);if(s.action)return ctx.state.doneActions.has(s.id)?s.need:0;return ctx.state.parts.filter(p=>s.types.includes(p.type)).length};

ctx.stepDone = i=>ctx.wiringActionIds.has(ctx.steps[i].id)?ctx.wiringActionReady(ctx.steps[i].id):ctx.countStep(ctx.steps[i])>=ctx.steps[i].need;

ctx.advanceGuidedStepIfReady = function advanceGuidedStepIfReady(origin=''){
 if(!ctx.state.guided||ctx.history.restoring)return false;
 let moved=false,start=ctx.state.step;
 while(ctx.state.step<ctx.steps.length-1&&ctx.stepDone(ctx.state.step)){ctx.state.step++;moved=true}
 if(moved){ctx.renderAssemblyUI();ctx.showGuides();if(origin)ctx.notify(`Guided build advanced to Step ${ctx.state.step+1}: ${ctx.steps[ctx.state.step].title}.`,'good')}
 return moved
};

ctx.stepTips = {
 bottom:{why:'The PDB is the electrical and mechanical base.',correct:'BAT/ESC solder pads face upward and remain visible.',mistake:'Starting with the top plate or covering the BAT pads.',risk:'Wrong polarity or hidden solder joints can damage the power system.',check:'Confirm BAT+, BAT− and E1–E4 pads are readable.'},
 arms:{why:'Arm orientation defines motor geometry and FRONT direction.',correct:'Red arms at FRONT, white arms at REAR; roots begin at plate edges.',mistake:'Swapping front/rear colours or starting rails from the plate centre.',risk:'Wrong orientation reverses flight-control assumptions.',check:'FRONT arrow points between the two red arms.'},
 guards:{why:'Guards protect the 1045 prop disc during training.',correct:'Open arc faces inward and sits below the motor.',mistake:'Mounting the guard above the motor or backwards.',risk:'Prop contact or obstructed motor mounting.',check:'All four arcs are clear of the propeller path.'},
 motors:{why:'Motor position and rotation group must match the mixer.',correct:'One A2212 centered on each arm tip.',mistake:'Offset motor or wrong M1–M4 location.',risk:'Unequal thrust and unstable control.',check:'Motor shafts align with all four arm-tip centres.'},
 motorScrews:{why:'Motor screws transfer thrust into the arm.',correct:'Four screws per motor, tightened evenly.',mistake:'Missing screw or uneven tightening.',risk:'Motor vibration or motor separation.',check:'16 screws are seated and level.'},
 escs:{why:'Each ESC drives one BLDC motor and supplies the control lead.',correct:'One ESC per arm with airflow and wire clearance.',mistake:'Crossing ESC/motor numbering.',risk:'Wrong motor responds to the FC output.',check:'ESC1→M1 through ESC4→M4.'},
 motorWire:{why:'The three phase wires energise the BLDC motor.',correct:'U/V/W all connected; swapping any two reverses direction.',mistake:'Missing or duplicate phase wire.',risk:'Motor will not start correctly.',check:'Each motor has three unique phase connections.'},
 powerWire:{why:'ESCs need high-current battery power from the PDB.',correct:'Thick red to +, thick brown-black to GND.',mistake:'Reversed polarity or using thin signal wire.',risk:'Immediate ESC/PDB damage.',check:'E1–E4 polarity is correct before fitting the top plate.'},
 top:{why:'The upper plate closes the frame after solder inspection.',correct:'Install only after ESC power soldering is complete.',mistake:'Installing it before checking solder joints.',risk:'Hidden shorts or difficult rework.',check:'No exposed strand or solder bridge is trapped inside.'},
 frameScrews:{why:'Frame screws clamp arms and both plates together.',correct:'Tighten progressively around all four arm roots.',mistake:'Fully tightening one corner first.',risk:'Twisted frame geometry.',check:'Top plate is level with a small centre gap.'},
 fcTape:{why:'Foam tape isolates vibration without a spacer.',correct:'Thin double-side foam tape directly on top plate.',mistake:'Using rigid standoffs in this build.',risk:'Higher vibration reaching IMU.',check:'Tape is flat, centered and not covering slots.'},
 fc:{why:'FC orientation defines Roll/Pitch/Yaw axes.',correct:'FRONT arrow points to red arms; headers project upward.',mistake:'Rotating FC 90°/180°.',risk:'Control axes become incorrect.',check:'ESC/GPIO/RX/I²C headers remain accessible.'},
 escFc:{why:'These leads carry ESC Source/PWM, +5V and GND.',correct:'Female 3-pin housing drops vertically onto matching ESC column.',mistake:'Connecting ESC1 lead to ESC2–4 or shifting one row.',risk:'Wrong motor command or rail short.',check:'Orange=Source, light red=+5V, brown-black=GND.'},
 battery:{why:'Under-frame battery lowers CG and leaves the top deck usable.',correct:'Battery centered underneath and both straps tight.',mistake:'Loose strap or off-centre battery.',risk:'CG shift during manoeuvres.',check:'Battery cannot slide forward/backward.'},
 xt60:{why:'XT60 is the final high-current connection.',correct:'BAT+ and BAT− mate with the visible PDB XT60 socket.',mistake:'Connecting before wiring inspection.',risk:'A short becomes live immediately.',check:'Run electrical validation before pressing Connect battery.'},
 props:{why:'Propellers are fitted only after electrical/motor checks.',correct:'1045 CW/CCW pattern matches motor rotation.',mistake:'Installing props before motor-direction test.',risk:'Unexpected thrust during testing.',check:'CW/CCW assignment and nut direction are correct.'},
 inspect:{why:'Final inspection catches assembly and wiring mistakes before flight.',correct:'Review polarity, motor order, FC orientation, props and fasteners.',mistake:'Skipping the checklist after successful power-up.',risk:'A small build error can cause loss of control.',check:'Electrical validator has no critical errors and all guided checks pass.'}
};

let displayedStep;
ctx.renderSteps = function renderSteps(){
 ctx.$('#assemblySteps').innerHTML=ctx.steps.map((s,i)=>`<div class="build-step ${i===ctx.state.step?'active':''} ${ctx.stepDone(i)?'done':''}" data-i="${i}" role="button" tabindex="0" aria-label="Step ${i+1}: ${s.title}"><div class="n">${String(i+1).padStart(2,'0')}</div><div><b>${s.title}</b><span>${s.target}</span></div><i class="state-dot"></i></div>`).join('');
 ctx.$$('.build-step').forEach(e=>e.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();e.click()}});
 ctx.$$('.build-step').forEach(e=>e.onclick=()=>{const i=+e.dataset.i;if(ctx.state.guided&&i>ctx.state.step&&!ctx.steps.slice(0,i).every((_,j)=>ctx.stepDone(j))){ctx.notify('Complete earlier guided steps first.','bad');return}ctx.historyPush();ctx.state.step=i;ctx.renderAssemblyUI();ctx.showGuides()});
 const s = ctx.steps[ctx.state.step];
 const tip = ctx.stepTips[s.id];
 const wiringStep = ctx.wiringActionIds.has(s.id);
 ctx.$('#stepCount').textContent = `Step ${ctx.state.step + 1} of ${ctx.steps.length}`;
 ctx.$('#currentStepTitle').textContent = s.title;
 ctx.$('#partsPanel').hidden = ctx.state.guided && Boolean(s.action);
 const card = ctx.$('#currentStepCard');
 card.innerHTML = `<p>${s.desc}</p><div class="targets">${ctx.countStep(s)}/${s.need} · ${s.target}</div>`;
 if (wiringStep || s.action) {
   const action = document.createElement('button');
   action.type = 'button';
   action.className = 'btn primary';
   action.id = wiringStep ? 'openWiringStep' : 'doStepAction';
   action.textContent = wiringStep ? 'Open 2D wiring' : 'Complete guided action';
   action.onclick = wiringStep ? () => ctx.setActiveTab('wiring') : () => ctx.performAction(s);
   card.append(action);
 }
 ctx.$('#stepNotes').innerHTML = Object.entries({
   Why:tip.why, Correct:tip.correct, 'Common mistake':tip.mistake, Risk:tip.risk, Check:tip.check
 }).map(([label,value]) => `<div><b>${label}</b><span>${value}</span></div>`).join('');
 if (displayedStep !== s.id) {
   displayedStep = s.id;
   // Reveal only within each rail. scrollIntoView would also move the enclosing console.
   const list = ctx.$('#assemblySteps');
   const active = list.querySelector('.active');
   if (active && list.offsetHeight) {
     const itemBox = active.getBoundingClientRect(), listBox = list.getBoundingClientRect();
     if (itemBox.top < listBox.top) list.scrollTop += itemBox.top - listBox.top;
     else if (itemBox.bottom > listBox.bottom) list.scrollTop += itemBox.bottom - listBox.bottom;
   }
   ctx.$('.right-panel').scrollTop = 0;
   ctx.$('.bench-panels').scrollTop = 0;
 }
 ctx.syncWiringPreview(s);
 ctx.$('#progressPill').textContent=Math.round(ctx.steps.filter((_,i)=>ctx.stepDone(i)).length/ctx.steps.length*100)+'%'
};

ctx.renderChecks = function renderChecks(){
 const a=[
  ['Bottom PDB + four edge-root arms',ctx.stepDone(1)],
  ['Arc guards + A2212 motors',ctx.stepDone(4)],
  ['ESCs installed on arms',ctx.stepDone(5)],
  ['Motor U/V/W connected',ctx.stepDone(6)],
  ['ESC high-current power soldered',ctx.stepDone(7)],
  ['Top plate + 12 frame screws',ctx.stepDone(9)],
  ['FC double-side tape — NO spacers',ctx.stepDone(10)],
  ['Areion FC A1 mounted',ctx.stepDone(11)],
  ['ESC female 3-pin plugs connected',ctx.stepDone(12)],
  ['Under-frame LiPo + straps',ctx.stepDone(13)],
  ['XT60 power connected',ctx.stepDone(14)],
  ['1045 CW/CCW props',ctx.stepDone(15)],
  ['Final inspection',ctx.stepDone(16)]
 ]; ctx.$('#buildChecks').innerHTML=a.map(([t,o])=>`<div class="check ${o?'ok':'warn'}">${o?'✓':'○'} ${t}</div>`).join('')
};

ctx.renderAssemblyUI = function renderAssemblyUI(){ctx.renderShelf();ctx.renderSteps();ctx.renderChecks();ctx.updatePowerUi?.()};
}
