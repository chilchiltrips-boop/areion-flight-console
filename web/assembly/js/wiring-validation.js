// Extracted from the supplied V18.3.82 wiring-validation reference.
// Each feature receives the project's shared runtime explicitly.
export function register(ctx) {
ctx.conn = function conn(a,b){return ctx.state.connections.some(c=>(c.from===a&&c.to===b)||(c.from===b&&c.to===a))};

ctx.phaseMap = function phaseMap(motor) {
  const phases = ['U','V','W'], destinations = new Set(), mapping = [];
  for (const phase of phases) {
    const pin = `ESC${motor}.${phase}`;
    const connections = ctx.state.connections.filter(wire => wire.from === pin || wire.to === pin);
    if (connections.length !== 1) return null;
    const {from,to} = connections[0], target = from === pin ? to : from;
    const index = phases.findIndex(name => target === `M${motor}.${name}`);
    if (index < 0 || destinations.has(index)) return null;
    // Each motor winding needs a single lead even when the extra lead came from a different ESC.
    if (ctx.state.connections.some(wire => wire !== connections[0] && (wire.from === target || wire.to === target))) return null;
    destinations.add(index);
    mapping.push(index);
  }
  return mapping;
};

ctx.permutationOdd = function permutationOdd(a){let inv=0;for(let i=0;i<a.length;i++)for(let j=i+1;j<a.length;j++)if(a[i]>a[j])inv++;return inv%2===1};

ctx.motorElectrical = function motorElectrical(i) {
  const map = ctx.phaseMap(i), header = ctx.fcHeaderForMotor(i);
  const ready = map && ctx.conn('BAT.+','PDB.BAT+') && ctx.conn('BAT.-','PDB.BAT-') &&
    ctx.conn(`PDB.E${i}+`,`ESC${i}.PWR+`) && ctx.conn(`PDB.E${i}-`,`ESC${i}.PWR-`) &&
    ctx.conn(`ESC${i}.SIG`,`FC.ESC${header}-S`) && ctx.conn(`ESC${i}.GND`,`FC.ESC${header}-G`);
  if (!ready) return {ready:false, dir:'OPEN', map};
  const clockwise = i === 1 || i === 3, reverse = ctx.permutationOdd(map);
  return {ready:true, dir:clockwise !== reverse ? 'CW' : 'CCW', map, reverse};
};

ctx.motorEnabled = function motorEnabled(i){return !!ctx.$(`#wireM${i}`)?.checked};

ctx.motorActive = function motorActive(i){return ctx.wireMotorRun&&!ctx.hasWiringFault&&+(ctx.$('#wireThrottle')?.value||1000)>=1100&&ctx.motorEnabled(i)&&ctx.motorElectrical(i).ready};

ctx.wireCarriesCurrent = function wireCarriesCurrent(c){const k=c.from+' '+c.to;if(ctx.state.powered&&(/BAT\.|PDB\.E|PWR/.test(k)))return true;if(!ctx.wireMotorRun||+(ctx.$('#wireThrottle')?.value||1000)<1100)return false;for(let i=1;i<=4;i++){if(!ctx.motorActive(i))continue;const keys=[['BAT.+','PDB.BAT+'],['BAT.-','PDB.BAT-'],[`PDB.E${i}+`,`ESC${i}.PWR+`],[`PDB.E${i}-`,`ESC${i}.PWR-`]];if(keys.some(([a,b])=>(c.from===a&&c.to===b)||(c.from===b&&c.to===a)))return true;if((c.from.startsWith(`ESC${i}.`)&&/\.[UVW]$/.test(c.from)&&c.to.startsWith(`M${i}.`))||(c.to.startsWith(`ESC${i}.`)&&/\.[UVW]$/.test(c.to)&&c.from.startsWith(`M${i}.`)))return true}return false};

ctx.render2D = function render2D(){
 const svg=ctx.$('#wiringSvg');if(!svg)return;const focusedPort=svg.contains(document.activeElement)?document.activeElement?.dataset.port:null;ctx.syncOptionalNodesFromParts();svg.innerHTML='';ctx.svgPorts={};const defs=ctx.E('defs');defs.innerHTML='<filter id="shadow"><feDropShadow dx="0" dy="2" stdDeviation="2" flood-opacity=".55"/></filter><filter id="glow"><feGaussianBlur stdDeviation="2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter><filter id="flowGlow"><feGaussianBlur stdDeviation="1.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>';svg.appendChild(defs);
 svg.onclick=()=>{ctx.selectedWireId=null;ctx.selPort=null;ctx.selectedWireNodeId=null;render2D()};
 ctx.draw2DFrame(svg);
 ctx.drawNode(svg,'BAT','3S LiPo / XT60',190,95,[],[['+','power'],['-','ground']],'DRAG • BATTERY • F / R');
 const phase=[['U','u'],['V','v'],['W','w']],control=[['PWR+','power'],['PWR-','ground'],['SIG','signal'],['5V','fivev'],['GND','ground']];
 ctx.drawNode(svg,'ESC1','ESC1 • FRONT LEFT',185,165,phase,control,'DRAG • F / R');
 ctx.drawNode(svg,'ESC2','ESC2 • FRONT RIGHT',185,165,control,phase,'DRAG • F / R');
 ctx.drawNode(svg,'ESC4','ESC4 • REAR LEFT',185,165,phase,control,'DRAG • F / R');
 ctx.drawNode(svg,'ESC3','ESC3 • REAR RIGHT',185,165,control,phase,'DRAG • F / R');
 [1,2,3,4].forEach(i=>ctx.drawMotorNode(svg,`M${i}`,`M${i} • A2212`));ctx.drawFCNode(svg);ctx.drawOptionalNodes(svg);
 const wires=ctx.E('g',{class:'wire-layer-v8'});ctx.state.connections.forEach((c,i)=>{const d=ctx.wireRoute(c);if(!d)return;const id=c.id||(c.id=`w${Date.now()}-${i}-${Math.random().toString(36).slice(2,5)}`),path=ctx.E('path',{d,class:`wire-v8 ${ctx.selectedWireId===id?'selected':''} ${ctx.wireCarriesCurrent(c)?'current-flow':''}`,stroke:ctx.cssW(c.from),'stroke-width':ctx.wireGauge(c),'data-wire-id':id});path.onclick=e=>{e.stopPropagation();ctx.selectedWireId=id;ctx.selectedWireNodeId=null;render2D()};wires.appendChild(path)});svg.appendChild(wires);
 ctx.drawFcPortOverlay(svg);
 // FC overlays share keys with their underlying pins; expose one keyboard target per port.
 const keyboardPorts=new Map();for(const port of svg.querySelectorAll('.port-v8')){port.tabIndex=-1;port.setAttribute('aria-hidden','true');keyboardPorts.set(port.dataset.port,port)}
 for(const [key,port] of keyboardPorts){port.tabIndex=0;port.removeAttribute('aria-hidden');port.setAttribute('role','button');port.setAttribute('aria-label',`Wiring port ${key}`);port.setAttribute('aria-pressed',String(ctx.selPort===key));port.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();ctx.choosePort(key)}}}
 if(focusedPort)keyboardPorts.get(focusedPort)?.focus({preventScroll:true});
 const syncChanged=ctx.syncWiringActionsToAssembly();ctx.validate2D();ctx.updateWireAssemblySync();ctx.updateMotorTestUI();ctx.persistWireLayout();if(syncChanged)ctx.renderAssemblyUI();if((syncChanged||ctx.wiringActionIds.has(ctx.steps[ctx.state.step]?.id))&&ctx.stepDone(ctx.state.step))ctx.advanceGuidedStepIfReady('wiring')
};

ctx.choosePort = function choosePort(k){if(!ctx.wireMode){ctx.notify('Press W or click OBJECT/WIRE MODE to enable wire connections.','bad');return}if(!ctx.selPort){ctx.selPort=k;ctx.render2D();return}if(k===ctx.selPort){ctx.selPort=null;ctx.render2D();return}if(!ctx.state.connections.some(c=>(c.from===ctx.selPort&&c.to===k)||(c.from===k&&c.to===ctx.selPort))){ctx.wireRemember();ctx.state.connections.push({from:ctx.selPort,to:k,new:true,id:`w${Date.now()}-${Math.random().toString(36).slice(2,6)}`});ctx.animatePlug(ctx.selPort,k);setTimeout(()=>{ctx.state.connections.forEach(c=>c.new=false);ctx.render2D()},700)}ctx.selPort=null;ctx.render2D();ctx.rebuild3DWires();ctx.rebuildSolder()};

ctx.deleteSelectedWire = function deleteSelectedWire(){if(!ctx.selectedWireId){ctx.notify('Select a wire first.','bad');return}ctx.wireRemember();ctx.state.connections=ctx.state.connections.filter(c=>c.id!==ctx.selectedWireId);ctx.selectedWireId=null;ctx.render2D();ctx.rebuild3DWires();ctx.rebuildSolder();ctx.notify('Selected wire deleted.')};

ctx.electricalIssues = function electricalIssues(){
 const issues=[],conns=ctx.state.connections;
 const has=(a,b)=>conns.some(c=>(c.from===a&&c.to===b)||(c.from===b&&c.to===a));
 const isHigh=k=>/^BAT\.\+$|^PDB\.(BAT\+|E\d\+)$|^ESC\d\.PWR\+$/.test(k),isGround=k=>/^BAT\.-$|^PDB\.(BAT-|E\d-)$|^ESC\d\.PWR-$|GND$|-G$/.test(k),isLow=k=>/^FC\.(ESC|GPIO|RX|I2C|AUX)/.test(k);
 conns.forEach(c=>{
   if((isHigh(c.from)&&isGround(c.to))||(isHigh(c.to)&&isGround(c.from)))issues.push({level:'bad',text:`Danger: positive connected to ground — ${c.from} ↔ ${c.to}`});
   if((isHigh(c.from)&&isLow(c.to))||(isHigh(c.to)&&isLow(c.from)))issues.push({level:'bad',text:`Danger: high-current battery voltage connected to FC low-voltage pin — ${c.from} ↔ ${c.to}`})
 });
 for(let i=1;i<=4;i++)if(has(`PDB.E${i}+`,`PDB.E${i}-`))issues.push({level:'bad',text:`Direct short detected across PDB E${i}+ and E${i}−.`});
 if(has('BAT.+','PDB.BAT-')||has('BAT.-','PDB.BAT+'))issues.push({level:'bad',text:'Battery polarity reversed at PDB XT60.'});
 for(let i=1;i<=4;i++){
   const source = `ESC${i}.SIG`, expected = `FC.ESC${ctx.fcHeaderForMotor(i)}-S`;
   for (const wire of conns.filter(w => w.from === source || w.to === source)) {
     const other = wire.from === source ? wire.to : wire.from;
     if (other !== expected) issues.push({level:'bad',text:`ESC${i} signal is on ${other}. Expected ${expected}.`});
   }
   const anyCtrl=['SIG','5V','GND'].some(p=>conns.some(c=>c.from===`ESC${i}.${p}`||c.to===`ESC${i}.${p}`));
   if(anyCtrl&&!conns.some(c=>(c.from===`ESC${i}.GND`&&c.to===`FC.ESC${ctx.fcHeaderForMotor(i)}-G`)||(c.to===`ESC${i}.GND`&&c.from===`FC.ESC${ctx.fcHeaderForMotor(i)}-G`)))issues.push({level:'warn',text:`ESC${i} control ground is missing.`});
   if(!ctx.phaseMap(i))issues.push({level:'warn',text:`M${i}: U/V/W phase set is incomplete or duplicated.`})
 }
 const fcUse={};conns.forEach(c=>[c.from,c.to].filter(k=>k.startsWith('FC.')).forEach(k=>(fcUse[k]??=[]).push(c)));
 Object.entries(fcUse).filter(([k,v])=>v.length>1&&!/^FC\.I2C-(G|SDA|SCL)$/.test(k)&&!/-G$/.test(k)).forEach(([k,v])=>issues.push({level:k.startsWith('FC.AUX-')?'bad':'warn',text:`FC pin ${k} is used by ${v.length} wires.`}));
 conns.forEach(c=>{const t=c.from+' '+c.to;if(/OPT_sensor_.*\.SDA.*FC\.I2C-SCL|FC\.I2C-SCL.*OPT_sensor_.*\.SDA/.test(t)||/OPT_sensor_.*\.SCL.*FC\.I2C-SDA|FC\.I2C-SDA.*OPT_sensor_.*\.SCL/.test(t))issues.push({level:'warn',text:'I²C SDA/SCL appear swapped.'})});
 const bv=ctx.state.batteryV||12.2;if(bv>16.8||bv<6.0)issues.push({level:'bad',text:`Battery ${bv.toFixed(1)} V is outside the 30A ESC 2S–4S training range.`});
 return issues
};

ctx.updateWireAssemblySync = function updateWireAssemblySync(){
 const box=ctx.$('#wireAssemblySync'),badge=ctx.$('#wireSyncBadge');if(!box)return;
 const rows=[['motorWire','Motor U / V / W',12],['powerWire','ESC power → PDB',8],['escFc','ESC control → FC',12],['xt60','Battery XT60',2]];
 box.innerHTML=rows.map(([id,label,need])=>{const n=ctx.wiringStepProgress(id),done=ctx.wiringActionReady(id),pr=ctx.wiringPrerequisitesReady(id);return `<div class="sync-row ${done?'done':''}"><span><b>${label}</b><span>${pr?`${n}/${need} correct connection(s)`: 'Install prerequisite parts in Assembly first'}</span></span><em>${done?'ASSEMBLY ✓':pr?'DRAW':'WAIT'}</em></div>`}).join('');
 if(badge){const complete=rows.filter(([id])=>ctx.wiringActionReady(id)).length;badge.textContent=`${complete}/4 SYNC`;badge.className='status '+(complete===4?'good':'')}
};

const escapeText = value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
ctx.validate2D = function validate2D(){
 const b=ctx.$('#wireValidation');if(!b)return;
 const fixed=ctx.referenceWires().filter(([a,z])=>!/\.[UVW]$/.test(a)&&!/\.[UVW]$/.test(z)),missingPairs=fixed.filter(([a,z])=>!ctx.conn(a,z)),batteryMissing=missingPairs.filter(([a,z])=>a.startsWith('BAT.')||z.startsWith('BAT.')).length,nonBatteryMissing=missingPairs.length-batteryMissing,phaseReady=[1,2,3,4].filter(i=>ctx.phaseMap(i)).length,issues=ctx.electricalIssues();
 ctx.hasWiringFault = issues.some(issue => issue.level === 'bad');
 const critical=issues.filter(x=>x.level==='bad').length,warns=issues.filter(x=>x.level==='warn').length,powerLine=nonBatteryMissing?`${nonBatteryMissing} fixed power/FC connection(s) missing`:(batteryMissing?`XT60 battery + / − not connected yet • press Connect battery XT60`:'✓ Fixed power + FC wiring complete');
 b.innerHTML=`<div class="check ${critical?'bad':'ok'}">${critical?`⚠ ${critical} critical electrical issue(s)`:'✓ No critical polarity / rail conflict'}</div><div class="check ${missingPairs.length?'warn':'ok'}">${powerLine}</div><div class="check ${phaseReady===4?'ok':'warn'}">${phaseReady}/4 motors have three unique U/V/W phase connections</div><div class="check ${warns?'warn':'ok'}">${warns?`${warns} wiring warning(s)`:'✓ Pin allocation checks pass'}</div><div class="electrical-issue-list">${issues.slice(0,8).map(x=>`<div class="${x.level}">${x.level==='bad'?'⚠':'○'} ${escapeText(x.text)}</div>`).join('')||'<div class="ok">✓ Electrical validation ready</div>'}</div><div class="check ${(ctx.selectedWireId||ctx.selectedWireNodeId)?'ok':'warn'}">${ctx.selectedWireId?'Wire selected — Delete removes it':ctx.selectedWireNodeId?'Object selected — F flip • R rotate • Delete removes it':'Click a wire or object to select. Press W for wire mode.'}</div>`
 const plan=ctx.optionalReferencePlan(),pinText=ctx.$('#wirePinPlan');ctx.referencePinPlan=plan.assignments;ctx.referencePinWiresOk=!!Object.keys(plan.assignments).length&&plan.wires.every(([a,z])=>ctx.conn(a,z))&&!issues.some(x=>x.level==='bad');if(pinText){const names=Object.entries(plan.assignments).map(([kind,v])=>`${kind.toUpperCase()} ${v.name} (GPIO${v.pin})${v.txName?` ↔ ${v.txName} (GPIO${v.txPin})`:''}`);pinText.textContent=[names.length?names.join(' • '):'Add servo or GPS to see free signal pins.',...plan.warnings].join('  |  ')}
};

ctx.addOptionalWireDevice = function addOptionalWireDevice(){const type=ctx.$('#optionalWireDevice')?.value||'servo',threeType=ctx.optionalThreeType(type);if(!threeType){ctx.notify('Unsupported optional device.','bad');return}if(!ctx.state.parts.some(p=>p.type==='fc')){ctx.notify('Mount the flight controller first, then add optional devices.','bad');return}const free=(ctx.slots[threeType]||[]).find(s=>!ctx.state.parts.some(p=>p.type===threeType&&p.slotId===s.id));if(!free){ctx.notify(`${ctx.product(threeType)?.name||threeType} has no free mounting slot.`,'bad');return}ctx.historyPush();ctx.install(threeType,free,true);ctx.ensureOptionalWireNode(type,free.id);ctx.selectedWireNodeId=ctx.optionalNodeId(type,free.id);ctx.renderAssemblyUI();ctx.render2D();ctx.showGuides();ctx.notify(`${ctx.optionalNodeDefinition({type}).title} added in 2D and attached in 3D.`)};

ctx.updateMotorTestUI = function updateMotorTestUI(){for(let i=1;i<=4;i++){const e=ctx.motorElectrical(i),active=ctx.motorActive(i),el=ctx.$(`#wireM${i}State`);if(el){el.textContent=!e.ready?'OPEN':active?`${e.dir} • RUN`:`${e.dir} • READY`;el.className=active?(e.reverse?'reverse':'running'):''}const dir=ctx.$(`#motorDir${i}`);if(dir){dir.textContent=e.ready?e.dir:'OPEN';dir.setAttribute('class',`motor-dir-2d ${e.reverse?'reverse':''}`)}}const pwm=ctx.$('#wireThrottle');if(ctx.$('#wirePwmOut')&&pwm)ctx.$('#wirePwmOut').textContent=`${pwm.value} µs`;if(ctx.$('#wireRunState')){ctx.$('#wireRunState').textContent=ctx.wireMotorRun?'RUNNING':'STOPPED';ctx.$('#wireRunState').className='status '+(ctx.wireMotorRun?'good':'')}};

ctx.animate2DMotors = function animate2DMotors(now=performance.now()){const dt=Math.min(.05,(now-ctx.wireAnimLast)/1000);ctx.wireAnimLast=now;const pwm=+(ctx.$('#wireThrottle')?.value||1000),speed=pwm<1100?0:ctx.clamp((pwm-1100)/900,0,1);let activeCount=0;for(let i=1;i<=4;i++){if(ctx.motorActive(i)){activeCount++;const e=ctx.motorElectrical(i),sign=e.dir==='CW'?1:-1;ctx.wireMotorAngle[i-1]=(ctx.wireMotorAngle[i-1]+sign*dt*(260+speed*1500))%360}const r=ctx.$(`#motorRotor${i}`);if(r)r.style.transform=`rotate(${ctx.wireMotorAngle[i-1]}deg)`}ctx.updateMotorAudio('wire',ctx.wireMotorRun&&activeCount?speed*(.45+.55*activeCount/4):0,.08*activeCount/4);if(ctx.wireMotorRun&&Math.floor(now/150)%2===0)ctx.updateMotorTestUI()};
}
