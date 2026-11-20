// Extracted from the supplied V18.3.82 wiring-renderer reference.
// Each feature receives the project's shared runtime explicitly.
export function register(ctx) {
ctx.selPort = null;

ctx.selectedWireId = null;

ctx.selectedWireNodeId = null;

ctx.svgPorts = {};

ctx.wireDrag = null;

ctx.wireMotorRun = false;

ctx.wireMotorAngle = [0,0,0,0];

ctx.wireAnimLast = performance.now();

ctx.wireMode = false;

ctx.wireDefaultLayout = {BAT:{x:55,y:402},FC:{x:870,y:360},ESC1:{x:230,y:175},ESC2:{x:1085,y:175},ESC3:{x:1085,y:635},ESC4:{x:230,y:635},M1:{x:90,y:55},M2:{x:1260,y:55},M3:{x:1260,y:790},M4:{x:90,y:790}};

ctx.wireLayout = structuredClone(ctx.wireDefaultLayout);

ctx.wireNodeTransforms = {};

ctx.optionalWireNodes = [];

ctx.E = function E(t,a={},x=''){const e=document.createElementNS(ctx.SVG,t);Object.entries(a).forEach(([k,v])=>e.setAttribute(k,v));if(x)e.textContent=x;return e};

ctx.wireTransform = function wireTransform(id){return ctx.wireNodeTransforms[id]||{rot:0,flipX:false}};

ctx.nodeTransformAttr = function nodeTransformAttr(id,w,h){
 const p=ctx.nodePos(id),t=ctx.wireTransform(id),cx=w/2,cy=h/2;
 // F-flip changes connector facing only. It intentionally never mirrors the text.
 return `translate(${p.x} ${p.y}) translate(${cx} ${cy}) rotate(${t.rot||0}) translate(${-cx} ${-cy})`
};

ctx.nodeCanvasPoint = function nodeCanvasPoint(id,w,h,x,y){
 const p=ctx.nodePos(id),t=ctx.wireTransform(id),cx=w/2,cy=h/2,r=ctx.rad(t.rot||0),dx=x-cx,dy=y-cy;
 return{x:p.x+cx+dx*Math.cos(r)-dy*Math.sin(r),y:p.y+cy+dx*Math.sin(r)+dy*Math.cos(r)}
};

ctx.optionalNodeId = function optionalNodeId(type,slotId){return `OPT_${type}_${slotId}`};

ctx.optionalThreeType = function optionalThreeType(type){return ctx.optional3DTypeMap[type]||null};

ctx.optionalBenchType = function optionalBenchType(threeType){return Object.entries(ctx.optional3DTypeMap).find(([,v])=>v===threeType)?.[0]||null};

ctx.ensureOptionalWireNode = function ensureOptionalWireNode(type,slotId){const id=ctx.optionalNodeId(type,slotId);let n=ctx.optionalWireNodes.find(x=>x.id===id);if(!n){n={id,type,slotId};ctx.optionalWireNodes.push(n)}if(!ctx.wireLayout[id])ctx.wireLayout[id]={x:1180,y:180+(ctx.optionalWireNodes.length-1)*118};return n};

ctx.syncOptionalNodesFromParts = function syncOptionalNodesFromParts(){ctx.state.parts.filter(p=>ctx.optionalBenchType(p.type)).forEach(p=>ctx.ensureOptionalWireNode(ctx.optionalBenchType(p.type),p.slotId));ctx.optionalWireNodes=ctx.optionalWireNodes.filter(n=>{const t=ctx.optionalThreeType(n.type);return !t||ctx.state.parts.some(p=>p.type===t&&p.slotId===n.slotId)})};

ctx.wireNodePart = function wireNodePart(id){
 const fixed={BAT:['battery','BAT'],FC:['fc','FC'],ESC1:['esc','ESC1'],ESC2:['esc','ESC2'],ESC3:['esc','ESC3'],ESC4:['esc','ESC4'],M1:['motor','M1'],M2:['motor','M2'],M3:['motor','M3'],M4:['motor','M4']};
 if(fixed[id]){const [type,slotId]=fixed[id];return ctx.state.parts.find(p=>p.type===type&&p.slotId===slotId)||null}
 const n=ctx.optionalWireNodes.find(x=>x.id===id);if(!n)return null;const t=ctx.optionalThreeType(n.type);return t?ctx.state.parts.find(p=>p.type===t&&p.slotId===n.slotId)||null:null
};

ctx.partToWireNodeId = function partToWireNodeId(type,slotId){const fixed={battery:{BAT:'BAT'},fc:{FC:'FC'},esc:{ESC1:'ESC1',ESC2:'ESC2',ESC3:'ESC3',ESC4:'ESC4'},motor:{M1:'M1',M2:'M2',M3:'M3',M4:'M4'}};if(fixed[type]?.[slotId])return fixed[type][slotId];const bench=ctx.optionalBenchType(type);return bench?ctx.optionalNodeId(bench,slotId):null};

ctx.nodeLabelSuffix = function nodeLabelSuffix(id){return ctx.wireNodePart(id)?' • 3D attached':' • 2D reference'};

ctx.selectWireNode = function selectWireNode(id){ctx.selectedWireNodeId=id;ctx.selectedWireId=null;ctx.selPort=null;ctx.render2D()};

ctx.setWireMode = function setWireMode(on=null,silent=false){ctx.wireMode=on===null?!ctx.wireMode:!!on;const b=ctx.$('#wireModeBadge');if(b){b.textContent=ctx.wireMode?'WIRE MODE':'OBJECT MODE';b.className='status '+(ctx.wireMode?'good':'')}if(!silent)ctx.notify(ctx.wireMode?'Wire mode enabled — click ports to connect.':'Object mode enabled — select, move, flip or rotate nodes.','good')};

ctx.clearWireConnectionsForPrefix = function clearWireConnectionsForPrefix(prefix){ctx.state.connections=ctx.state.connections.filter(c=>!(c.from===prefix||c.to===prefix||c.from.startsWith(prefix+'.')||c.to.startsWith(prefix+'.')))};

ctx.deleteOptionalNodeOnly = function deleteOptionalNodeOnly(id,silent=false){ctx.wireRemember();ctx.clearWireConnectionsForPrefix(id);delete ctx.wireLayout[id];delete ctx.wireNodeTransforms[id];ctx.optionalWireNodes=ctx.optionalWireNodes.filter(n=>n.id!==id);if(ctx.selectedWireNodeId===id)ctx.selectedWireNodeId=null;ctx.render2D();ctx.rebuild3DWires();ctx.rebuildSolder();ctx.persistWireLayout();if(!silent)ctx.notify('Optional device deleted from 2D bench.')};

ctx.rotateSelectedNode = function rotateSelectedNode(){if(!ctx.selectedWireNodeId){ctx.notify('Select an object first.','bad');return}ctx.wireRemember();const t=ctx.wireTransform(ctx.selectedWireNodeId);ctx.wireNodeTransforms[ctx.selectedWireNodeId]={...t,rot:((t.rot||0)+90)%360};ctx.persistWireLayout();ctx.render2D();ctx.notify('Selected 2D object rotated 90°.','good')};

ctx.flipSelectedNode = function flipSelectedNode(){
 if(!ctx.selectedWireNodeId){ctx.notify('Select an object first.','bad');return}
 if(ctx.selectedWireNodeId==='FC'){ctx.notify('The FC pin map is fixed.','bad');return}
 ctx.wireRemember();const t=ctx.wireTransform(ctx.selectedWireNodeId);
 ctx.wireNodeTransforms[ctx.selectedWireNodeId]={...t,flipX:!t.flipX};
 ctx.persistWireLayout();ctx.render2D();ctx.notify('Connector side flipped • labels stay readable.','good')
};

ctx.deleteSelectedObject = function deleteSelectedObject(){if(ctx.selectedWireId){ctx.deleteSelectedWire();return}if(!ctx.selectedWireNodeId){ctx.notify('Select an object or wire first.','bad');return}const part=ctx.wireNodePart(ctx.selectedWireNodeId);if(part){ctx.deleteInstalled(part.id);ctx.selectedWireNodeId=null;return}if(ctx.optionalWireNodes.some(n=>n.id===ctx.selectedWireNodeId)){ctx.deleteOptionalNodeOnly(ctx.selectedWireNodeId);return}ctx.notify('This fixed bench node is a reference. Install the matching 3D part first, then delete it.','bad')};

ctx.portDot = function portDot(svg,key,x,y,type,label,anchor='start'){ctx.svgPorts[key]={x,y};const c=ctx.E('circle',{cx:x,cy:y,r:6.5,class:`port-v8 ${type}${ctx.selPort===key?' selected':''}`});c.dataset.port=key;c.onclick=e=>{e.stopPropagation();ctx.choosePort(key)};svg.appendChild(c);if(label)svg.appendChild(ctx.E('text',{x:x+(anchor==='start'?9:-9),y:y+3,class:'port-label-v8','text-anchor':anchor},label))};

ctx.draw2DFrame = function draw2DFrame(svg){
 const g=ctx.E('g',{transform:'translate(750,450)',opacity:'.72'});svg.appendChild(g);
 const arms=[[-45,'red'],[45,'red'],[135,'white'],[-135,'white']];
 arms.forEach(([a,c])=>{const q=ctx.E('g',{transform:`rotate(${a})`});g.appendChild(q);q.appendChild(ctx.E('path',{d:'M-28 20 L-28 218 L-52 245 L-48 278 L48 278 L52 245 L28 218 L28 20 Z',class:`wire-bg-arm ${c==='red'?'red':''}`}));for(let y=55;y<210;y+=31)q.appendChild(ctx.E('path',{d:`M-19 ${y} L19 ${y+23} M19 ${y} L-19 ${y+23}`,stroke:c==='red'?'#b84a5060':'#9aa9b460','stroke-width':4}));q.appendChild(ctx.E('circle',{cx:0,cy:260,r:31,fill:'#0c182111',stroke:'#77899655','stroke-width':2}));q.appendChild(ctx.E('rect',{x:-22,y:250,width:44,height:75,rx:7,class:'wire-bg-foot'}))});
 g.appendChild(ctx.E('path',{d:'M-112 -96 L-60 -96 L-45 -118 L45 -118 L60 -96 L112 -96 L112 -42 L140 -28 L140 28 L112 42 L112 96 L60 96 L45 118 L-45 118 L-60 96 L-112 96 L-112 42 L-140 28 L-140 -28 L-112 -42 Z',class:'wire-bg-plate'}));
 g.appendChild(ctx.E('text',{x:-30,y:-140,class:'svg-front'},'↑ FRONT'));
 [['BAT+',655,438,'power'],['BAT-',655,462,'ground'],['E1+',700,392,'power'],['E1-',678,392,'ground'],['E2+',828,392,'power'],['E2-',828,414,'ground'],['E3+',828,486,'power'],['E3-',828,508,'ground'],['E4+',700,508,'power'],['E4-',678,508,'ground']].forEach(([n,x,y,t])=>ctx.portDot(svg,'PDB.'+n,x,y,t,n,'start'))
};

ctx.nodePos = function nodePos(id){return ctx.wireLayout[id]||{x:100,y:100}};

ctx.setNodePos = function setNodePos(id,x,y){
 const [w,h]=id==='FC'?[310,315]:id==='BAT'?[190,95]:id.startsWith('ESC')?[185,165]:id.startsWith('M')?[150,100]:[175,120];
 ctx.wireLayout[id]={x:ctx.clamp(x,5,1495-w),y:ctx.clamp(y,5,895-h)}
};

ctx.beginNodeDrag = function beginNodeDrag(id,e){if(e.target.closest?.('.port-v8'))return;e.preventDefault();e.stopPropagation();ctx.selectedWireNodeId=id;ctx.selectedWireId=null;ctx.selPort=null;ctx.wireRemember();const pt=ctx.svgLocalPoint(ctx.$('#wiringSvg'),e.clientX,e.clientY),p=ctx.nodePos(id);ctx.wireDrag={id,dx:pt.x-p.x,dy:pt.y-p.y};document.body.style.userSelect='none'};

ctx.svgLocalPoint = function svgLocalPoint(svg,x,y){const p=svg.createSVGPoint();p.x=x;p.y=y;return p.matrixTransform(svg.getScreenCTM().inverse())};

ctx.drawNode = function drawNode(svg,id,title,w,h,portsLeft=[],portsRight=[],sub='DRAG TO MOVE',extraClass=''){
 const t=ctx.wireTransform(id),flip=!!t.flipX,leftPorts=flip?portsRight:portsLeft,rightPorts=flip?portsLeft:portsRight;
 const g=ctx.E('g',{class:`wire-node-v8 ${extraClass}${ctx.selectedWireNodeId===id?' selected-node':''}`,'data-node':id,transform:ctx.nodeTransformAttr(id,w,h)});
 g.onclick=e=>{if(e.target.closest?.('.port-v8'))return;e.stopPropagation();ctx.selectWireNode(id)};
 g.appendChild(ctx.E('rect',{x:0,y:0,width:w,height:h,rx:12}));
 g.appendChild(ctx.E('rect',{x:0,y:0,width:w,height:28,rx:12,class:'drag-handle'}));
 g.appendChild(ctx.E('text',{x:11,y:18,class:'node-title'},title+ctx.nodeLabelSuffix(id)));
 g.appendChild(ctx.E('text',{x:11,y:h-8,class:'node-sub'},sub));
 if(flip)g.appendChild(ctx.E('text',{x:w-12,y:18,class:'flip-badge-2d','text-anchor':'end'},'FLIPPED'));
 leftPorts.forEach((q,i)=>{const yy=42+i*20;g.appendChild(ctx.E('text',{x:14,y:yy+3,class:'port-label-v8'},q[0]));const c=ctx.E('circle',{cx:0,cy:yy,r:6.5,class:`port-v8 ${q[1]}${ctx.selPort===id+'.'+q[0]?' selected':''}`});c.dataset.port=id+'.'+q[0];c.onclick=e=>{e.stopPropagation();ctx.choosePort(c.dataset.port)};g.appendChild(c);ctx.svgPorts[id+'.'+q[0]]=ctx.nodeCanvasPoint(id,w,h,0,yy)});
 rightPorts.forEach((q,i)=>{const yy=42+i*20;g.appendChild(ctx.E('text',{x:w-14,y:yy+3,class:'port-label-v8','text-anchor':'end'},q[0]));const c=ctx.E('circle',{cx:w,cy:yy,r:6.5,class:`port-v8 ${q[1]}${ctx.selPort===id+'.'+q[0]?' selected':''}`});c.dataset.port=id+'.'+q[0];c.onclick=e=>{e.stopPropagation();ctx.choosePort(c.dataset.port)};g.appendChild(c);ctx.svgPorts[id+'.'+q[0]]=ctx.nodeCanvasPoint(id,w,h,w,yy)});
 g.onpointerdown=e=>ctx.beginNodeDrag(id,e);svg.appendChild(g);return g
};

ctx.drawMotorNode = function drawMotorNode(svg,id,title){
 const w=150,h=100,phase=[['U','u'],['V','v'],['W','w']],phaseLeft=(id==='M2'||id==='M3');
 const g=phaseLeft?ctx.drawNode(svg,id,title,w,h,phase,[],'PHASE LEADS ← ESC • F flip • R rotate'):
                   ctx.drawNode(svg,id,title,w,h,[],phase,'ESC → PHASE LEADS • F flip • R rotate');
 const holder=ctx.E('g',{transform:'translate(75 62)'}),rotor=ctx.E('g',{id:`motorRotor${id.slice(1)}`,class:'motor-rotor-2d'});
 rotor.appendChild(ctx.E('circle',{cx:0,cy:0,r:25,class:'motor-ring-2d'}));
 rotor.appendChild(ctx.E('rect',{x:-39,y:-3,width:78,height:6,rx:3,class:'motor-blade-2d'}));
 rotor.appendChild(ctx.E('rect',{x:-3,y:-39,width:6,height:78,rx:3,class:'motor-blade-2d'}));holder.appendChild(rotor);g.appendChild(holder);
 const effectiveLeft=phaseLeft!==!!ctx.wireTransform(id).flipX,edge=effectiveLeft?0:w;
 [['#f5c542',-8],['#2c92ff',0],['#87949d',8]].forEach(([col,dy])=>g.appendChild(ctx.E('path',{d:effectiveLeft?`M52 ${62+dy} Q30 ${62+dy} ${edge} ${62+dy}`:`M98 ${62+dy} Q120 ${62+dy} ${edge} ${62+dy}`,stroke:col,'stroke-width':2.5,fill:'none',class:'motor-pigtail-2d'})));
 g.appendChild(ctx.E('text',{x:75,y:95,id:`motorDir${id.slice(1)}`,class:'motor-dir-2d'},'OPEN'));return g
};

ctx.drawFCNode = function drawFCNode(svg){
 const id='FC',w=310,h=315,g=ctx.E('g',{class:`wire-node-v8 fc-node-v14${ctx.selectedWireNodeId===id?' selected-node':''}`,'data-node':id,transform:ctx.nodeTransformAttr(id,w,h)});
 g.onpointerdown=e=>ctx.beginNodeDrag(id,e);g.onclick=e=>{if(e.target.closest?.('.port-v8'))return;e.stopPropagation();ctx.selectWireNode(id)};
 g.appendChild(ctx.E('rect',{x:0,y:0,width:w,height:h,rx:14,class:'fc-2d-case'}));
 g.appendChild(ctx.E('rect',{x:78,y:44,width:132,height:95,rx:9,class:'fc-2d-window'}));
 g.appendChild(ctx.E('text',{x:w/2,y:22,class:'fc-2d-label'},'Areion FC A1 • Virtual headers'));
 g.appendChild(ctx.E('text',{x:w/2,y:38,class:'fc-2d-front'},'↑ FRONT'));
 g.appendChild(ctx.E('text',{x:12,y:h-9,class:'node-sub'},'DRAG • FIXED PIN MAP'));
 const makePin=(key,cx,cy,t,label)=>{const c=ctx.E('circle',{cx,cy,r:6.4,class:`port-v8 ${t}${ctx.selPort===key?' selected':''}`});c.dataset.port=key;c.onclick=e=>{e.stopPropagation();ctx.choosePort(key)};g.appendChild(c);ctx.svgPorts[key]=ctx.nodeCanvasPoint(id,w,h,cx,cy);if(label)g.appendChild(ctx.E('text',{x:cx,y:cy-9,class:'fc-pin-mini','text-anchor':'middle'},label))};
 g.appendChild(ctx.E('rect',{x:35,y:172,width:178,height:78,rx:7,class:'fc-block-v14 esc'}));g.appendChild(ctx.E('text',{x:124,y:166,'text-anchor':'middle',class:'fc-section-label'},'ESC OUTPUTS • D0 D1 D2 D3'));
 const ex=[58,100,142,184],ey=[190,214,238];['SIGNAL','+5V','GND'].forEach((n,r)=>g.appendChild(ctx.E('text',{x:28,y:ey[r]+3,'text-anchor':'end',class:`fc-row-label ${r===0?'source':r===1?'fivev':'ground'}`},n)));ex.forEach((x,i)=>ey.forEach((y,r)=>makePin(`FC.ESC${i+1}-${r===0?'S':r===1?'5V':'G'}`,x,y,r===0?'signal':r===1?'fivev':'ground',r===0?`D${i}`:'')));
 g.appendChild(ctx.E('rect',{x:219,y:115,width:78,height:78,rx:7,class:'fc-block-v14 gpio'}));g.appendChild(ctx.E('text',{x:258,y:108,'text-anchor':'middle',class:'fc-section-label'},'Expansion rails'));
 const gx=[232,258,284],gy=[132,154,176];gx.forEach((x,i)=>gy.forEach((y,r)=>makePin(`FC.GPIO${i+1}-${r===0?'S':r===1?'5V':'G'}`,x,y,r===0?'signal':r===1?'fivev':'ground',r===0?`G${i+1}`:'')));
 g.appendChild(ctx.E('text',{x:258,y:251,'text-anchor':'middle',class:'fc-section-label'},'Virtual expansion'));
 [7,8,9].forEach((d,i)=>makePin(`FC.AUX-D${d}`,222+i*24,282,'signal',`D${d}`));
 g.appendChild(ctx.E('rect',{x:263,y:45,width:34,height:64,rx:7,class:'fc-block-v14 rx'}));g.appendChild(ctx.E('text',{x:280,y:39,'text-anchor':'middle',class:'fc-section-label'},'RX'));
 [['S','signal',60,'D10 / PPM'],['V','fivev',78,'+5V'],['G','ground',96,'GND']].forEach(([n,t,y,l])=>makePin(`FC.RX-${n}`,280,y,t,l));
 g.appendChild(ctx.E('rect',{x:18,y:47,width:114,height:38,rx:7,class:'fc-block-v14 i2c'}));g.appendChild(ctx.E('text',{x:75,y:40,'text-anchor':'middle',class:'fc-section-label'},'I²C • D4 SDA / D5 SCL'));
 [['V','fivev'],['G','ground'],['SCL','i2c'],['SDA','i2c']].forEach(([n,t],i)=>makePin(`FC.I2C-${n}`,36+i*28,66,t,n));
 g.appendChild(ctx.E('circle',{cx:225,cy:65,r:9,class:'fc-rgb-v14'}));g.appendChild(ctx.E('text',{x:225,y:83,'text-anchor':'middle',class:'fc-rgb-label-v14'},'RGB'));
 svg.appendChild(g)
};

ctx.optional3DTypeMap = {ppm:'receiver',servo:'servo',matrix:'matrix',sensor:'sensor',gps:'gps',led:'led'};

ctx.optionalPlacedIn3D = function optionalPlacedIn3D(type){const t=ctx.optional3DTypeMap[type];return !!t&&ctx.state.parts.some(p=>p.type===t)};

ctx.optionalNodeDefinition = function optionalNodeDefinition(n){
 if(n.type==='ppm')return{title:'PPM RECEIVER',ports:[['SIG','signal'],['5V','fivev'],['GND','ground']]};
 if(n.type==='servo')return{title:'SERVO',ports:[['SIG','signal'],['5V','fivev'],['GND','ground']]};
 if(n.type==='matrix')return{title:'I²C LED MATRIX',ports:[['SDA','i2c'],['SCL','i2c'],['VCC','fivev'],['GND','ground']]};
 if(n.type==='sensor')return{title:'I²C SENSOR',ports:[['SDA','i2c'],['SCL','i2c'],['VCC','fivev'],['GND','ground']]};
 if(n.type==='led')return{title:'LED / OUTPUT',ports:[['DATA','signal'],['5V','fivev'],['GND','ground']]};
 return{title:'GPS',ports:[['TX','signal'],['RX','signal'],['5V','fivev'],['GND','ground']]}
};

ctx.referenceAuxPins = [{name:'D7',gpio:17},{name:'D8',gpio:19},{name:'D9',gpio:20}];

ctx.optionalReferencePlan = function optionalReferencePlan(){
 ctx.syncOptionalNodesFromParts();
 const used=new Set(),wires=[],assignments={},warnings=[];
 const gpsUbx=(ctx.$('#wireGpsProtocol')?.value||'NMEA_9600')==='UBX_10HZ';
 const choose=kind=>{
   const available=ctx.referenceAuxPins.filter(pin=>!used.has(pin.gpio));
   const suggested=kind==='gps'?20:kind==='gpsTx'?19:null;
   const free=available.find(pin=>pin.gpio===suggested)||available[0];
   if(free)used.add(free.gpio);
   return free;
 };
 for(const n of ctx.optionalWireNodes){
   const id=n.id;
   if(n.type==='ppm'){warnings.push('PPM signal uses the fixed D10 / GPIO18 input.');wires.push([`${id}.SIG`,'FC.RX-S'],[`${id}.5V`,'FC.RX-V'],[`${id}.GND`,'FC.RX-G']);continue}
   if(n.type==='sensor'||n.type==='matrix'){
     wires.push([`${id}.SDA`,'FC.I2C-SDA'],[`${id}.SCL`,'FC.I2C-SCL'],[`${id}.GND`,'FC.I2C-G']);
     warnings.push(`${n.type==='matrix'?'Matrix':'Sensor'}: match its supply and logic voltage; power is not auto-wired.`);continue;
   }
   if(n.type==='servo'||n.type==='gps'){
     if(assignments[n.type]){warnings.push(`Only one ${n.type} is assigned by this reference plan; ${n.slotId} needs separate code/hardware.`);continue}
     const pin=choose(n.type);if(!pin){warnings.push(`No free D7–D9 signal pin for ${n.type}. Release a GPIO output or another module.`);continue}
     if(n.type==='gps'&&gpsUbx){
       const tx=choose('gpsTx');if(!tx){used.delete(pin.gpio);warnings.push('UBX GPS needs two free D7–D9 pins for RX and TX.');continue}
       assignments.gps={pin:pin.gpio,name:pin.name,txPin:tx.gpio,txName:tx.name,nodeId:id};
       wires.push([`${id}.RX`,`FC.AUX-${tx.name}`]);
     }else assignments[n.type]={pin:pin.gpio,name:pin.name,nodeId:id};
     wires.push([`${id}.${n.type==='servo'?'SIG':'TX'}`,`FC.AUX-${pin.name}`],[`${id}.GND`,`FC.GPIO${n.type==='servo'?1:2}-G`]);
     warnings.push(`${n.type==='servo'?'Servo':'GPS'}: use a compatible external regulated supply and common ground.`);continue;
   }
   if(n.type==='led'){
     const pin=choose('led');if(pin){wires.push([`${id}.DATA`,`FC.AUX-${pin.name}`],[`${id}.GND`,'FC.GPIO3-G']);warnings.push(`LED on ${pin.name}: set this free pin as GPIO output before sending values.`)}
     else warnings.push('No free D7–D9 GPIO for LED output.');
   }
 }
 return{wires,assignments,warnings};
};

ctx.drawOptionalNodes = function drawOptionalNodes(svg){ctx.syncOptionalNodesFromParts();ctx.optionalWireNodes.forEach(n=>{if(!ctx.wireLayout[n.id])ctx.wireLayout[n.id]={x:1180,y:420+(ctx.optionalWireNodes.indexOf(n)%3)*120};const d=ctx.optionalNodeDefinition(n),linked=ctx.wireNodePart(n.id);ctx.drawNode(svg,n.id,`${d.title} • ${n.slotId||'BENCH'}`,175,120,d.ports,[],linked?'SYNCED 2D ↔ 3D • DRAG':'UNPLACED IN 3D • DRAG','optional-node')})};

ctx.wireRoute = function wireRoute(c){
 const a=ctx.svgPorts[c.from],b=ctx.svgPorts[c.to];if(!a||!b)return'';
 if(/\.[UVW]$/.test(c.from)||/\.[UVW]$/.test(c.to)){const mx=(a.x+b.x)/2;return`M${a.x},${a.y} Q${mx},${Math.min(a.y,b.y)-18} ${b.x},${b.y}`}
 const aFC=c.from.startsWith('FC.'),bFC=c.to.startsWith('FC.');
 if(aFC||bFC){const pin=aFC?a:b,other=aFC?b:a,side=other.x<pin.x?-1:1,approach={x:pin.x+side*34,y:pin.y};if(aFC)return`M${pin.x},${pin.y} L${approach.x},${approach.y} C${approach.x+side*45},${approach.y} ${other.x-side*70},${other.y} ${other.x},${other.y}`;return`M${other.x},${other.y} C${other.x+side*70},${other.y} ${approach.x-side*45},${approach.y} ${approach.x},${approach.y} L${pin.x},${pin.y}`}
 return`M${a.x},${a.y} C${a.x+(b.x-a.x)*.38},${a.y} ${a.x+(b.x-a.x)*.62},${b.y} ${b.x},${b.y}`
};

ctx.cssW = function cssW(k){if(/\.U$/.test(k))return'#f5c542';if(/\.V$/.test(k))return'#2c92ff';if(/\.W$/.test(k))return'#87949d';if(/PWR\+|BAT\.\+|PDB\..*\+/.test(k))return'#ef3f48';if(/PWR-|BAT\.-|PDB\..*-$|GND|-G$/.test(k))return'#b88967';if(/5V|-V$/.test(k))return'#fb7185';if(/I2C/.test(k))return'#47c8f1';return'#f59e0b'};

ctx.wireGauge = function wireGauge(c){const k=c.from+' '+c.to;if(/BAT\.|PWR|PDB\.E/.test(k))return 7.5;if(/\.[UVW]/.test(k))return 4.6;if(/5V|GND|-G\b/.test(k))return 3.4;return 3.5};

ctx.portTypeFromKey = function portTypeFromKey(k){if(/5V|-V$/.test(k))return'fivev';if(/GND|-G$|BAT-/.test(k))return'ground';if(/\.U$/.test(k))return'u';if(/\.V$/.test(k))return'v';if(/\.W$/.test(k))return'w';if(/\+|PWR\+/.test(k))return'power';if(/I2C-(SCL|SDA)/.test(k))return'i2c';return'signal'};

ctx.drawFcPortOverlay = function drawFcPortOverlay(svg) {
  // Drawing only the hit targets here keeps the fixed header labels clear.
  const layer = ctx.E('g', {class:'fc-port-overlay-v13'});
  for (const [key, point] of Object.entries(ctx.svgPorts)) {
    if (!key.startsWith('FC.')) continue;
    const selected = ctx.selPort === key ? ' selected' : '';
    const pin = ctx.E('circle', {cx:point.x, cy:point.y, r:7.4,
      class:`port-v8 port-overlay-v13 ${ctx.portTypeFromKey(key)}${selected}`});
    pin.dataset.port = key;
    pin.onclick = event => { event.stopPropagation(); ctx.choosePort(key); };
    pin.appendChild(ctx.E('title', {}, key.replace('FC.', 'FC ')));
    layer.appendChild(pin);
  }
  svg.appendChild(layer);
};
}
