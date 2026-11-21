import {banks,terms,limits} from './gains.js';

const select=(name, entries, value)=>'<select data-tp="'+name+'" aria-label="'+name+'">'+entries.map(([k,label])=>
  '<option value="'+k+'"'+(k===value?' selected':'')+'>'+label+'</option>').join('')+'</select>';
const button=(name,label,cls='')=>'<button type="button" data-tp-action="'+name+'" class="cfg-btn '+cls+'">'+label+'</button>';
const out=(key,value='—')=>'<output data-tp-out="'+key+'">'+value+'</output>';
const field=(name,control)=>'<label class="tp-field"><span>'+name+'</span>'+control+'</label>';
const bankName=name=>name.replace(/^(rate|angle)/,(_,loop)=>loop==='rate'?'Rate · ':'Angle · ');
const plotModes=[['response','Target / measured'],['terms','P / I / D terms'],['motors','Motor pulses'],['rpm','Motor RPM'],['travel','Slider travel']];
const cameraViews=[['isometric','Isometric'],['rear','Rear'],['front','Front'],['left','Left'],['right','Right'],['top','Top'],['follow','Follow yaw']];
const axes=[['roll','Roll'],['pitch','Pitch'],['yaw','Yaw']];
function scene(live) {
  return '<section class="tp-card tp-model"><div class="tp-card-head"><h3>F450 tripod</h3>'+select('Camera view',cameraViews,'isometric')+'</div>'+
    '<div class="tp-stage" data-tp-stage><span class="tp-stage-source">'+(live?'FC attitude':'Simulated attitude')+'</span><span class="tp-model-info" data-tp-out="model">Loading F450</span></div>'+
    '<div class="tp-attitudes">'+['Roll','Pitch',live?'Relative yaw':'Yaw'].map((label,i)=>'<div><span>'+label+'</span>'+out('att'+i)+'</div>').join('')+'</div>'+
    '<div class="tp-motors" aria-label="'+(live?'Reported motor pulses':'Simulated motor outputs')+'">'+['Front left','Front right','Rear right','Rear left'].map((pos,i)=>
      '<div title="'+pos+'"><div class="tp-motor-label"><b>M'+(i+1)+'</b>'+out('motor'+i)+'</div><div class="tp-bar"><i data-tp-bar="'+i+'"></i></div><small>'+out('motorDetail'+i,pos)+'</small></div>').join('')+'</div></section>';
}
function sticks(){
  const pad=(side,title)=>'<div><label>'+title+'</label><div class="tp-pad" data-pad="'+side+'" tabindex="0" role="group" aria-label="'+title+' joystick"><i></i></div></div>';
  return '<section class="tp-card tp-input"><div class="tp-card-head"><h3>Virtual transmitter</h3>'+out('receiver','Keyboard / sticks')+'</div>'+
    '<div class="tp-stick-pair">'+pad('left','Throttle / yaw')+pad('right','Pitch / roll')+'</div>'+
    '<label class="tp-range">Throttle '+out('throttle','1000 µs')+'<input data-tp="Throttle" aria-label="Virtual throttle" type="range" min="1000" max="2000" step="1" value="1000"></label>'+
    '<small>W / S throttle · A / D yaw · arrow keys pitch and roll</small></section>';
}
function gainTools(){
 const fields=terms.map(k=>field(k.toUpperCase(),'<input type="number" aria-label="Simulator '+k.toUpperCase()+'" data-gain="'+k+'" min="0" max="'+limits[k]+'" step="any">')).join('');
 return '<section class="tp-card"><div class="tp-card-head"><h3>Simulator gains</h3>'+select('PID bank',banks.map(n=>[n,bankName(n)]),'rateRoll')+'</div><div class="tp-gains">'+fields+'</div>'+
  '<div class="tp-actions">'+button('apply','Apply to simulator','cfg-primary')+button('load','Load kit gains')+button('defaults','Restore sim defaults')+'</div>'+
  '<p class="tp-note" role="status" data-tp-out="gainNote">Edits apply to the virtual model.</p></section>';
}
const conditions=[['batteryV','Battery','V',9,12.6,.1],['payloadG','Payload','g',0,650,10],['cgX','Roll CG offset','mm',-25,25,1],['cgY','Pitch CG offset','mm',-25,25,1],['wind','Wind','%',0,100,1],['lag','Motor lag','s',.04,.30,.01],['gyroNoise','Gyro noise','°/s',0,2,.01]];
function environment(){
 return '<details class="tp-card"><summary>Test conditions &amp; sound</summary><div class="tp-condition-grid">'+conditions.map(([k,label,unit,min,max,step])=>
   '<label class="tp-range">'+label+out(k)+'<input type="range" data-env="'+k+'" data-unit="'+unit+'" aria-label="'+label+'" min="'+min+'" max="'+max+'" step="'+step+'"></label>').join('')+'</div>'+
   '<div class="tp-actions">'+button('tilt','Drag to tilt')+button('level','Set level')+button('integrator','Reset integrators')+
   '<label><input type="checkbox" data-tp="Airflow" checked> Airflow</label><label><input type="checkbox" data-tp="Sound"> Motor sound</label></div></details>';
}
function comparison(){
 return '<details class="tp-card" data-comparison><summary>Compare two gains</summary><div class="tp-actions">'+field('Gain',select('Comparison term',terms.map(k=>[k,k.toUpperCase()]),'p'))+
  field('Value A','<input type="number" aria-label="Comparison A" data-tp="A" min="0" step="any" value=".5">')+
  field('Value B','<input type="number" aria-label="Comparison B" data-tp="B" min="0" step="any" value="1.4">')+button('compare','Compare responses')+
  '</div><p class="tp-note" data-tp-out="compare" role="status">Both runs use the selected PID bank and the same test conditions.</p><canvas data-tp-plot="compare" aria-label="Comparison of two simulated PID responses"></canvas></details>';
}
function simTracking(){
 return '<section class="tp-card tp-plot"><div class="tp-card-head"><h3>Response</h3>'+select('Plot',plotModes,'response')+'</div>'+
 '<div class="tp-plot-controls">'+select('Test axis',axes,'roll')+button('freeze','Freeze graph')+'<div class="tp-legend" data-tp-legend></div></div>'+
 '<canvas data-tp-plot="sim" role="img" aria-label="Virtual target and measured response"></canvas>'+
 '<div class="tp-plot-metrics">'+out('error')+out('peak')+'</div></section>';
}
export function tripodMarkup(live,tracking) {
  if(live)return '<div class="tp-work" data-tripod="live"><div class="tp-toolbar"><strong class="tp-tag tp-live-tag">Live FC</strong>'+
    out('link','Waiting for kit')+'<div class="tp-actions">'+button('record','Record 10 s','cfg-primary')+button('finish','Finish capture')+button('export','Export run CSV')+'</div></div>'+
    '<div class="tp-body">'+scene(true)+'<div class="tp-rail"><section class="tp-card"><div class="tp-card-head"><h3>Tripod test</h3>'+out('armed')+'</div>'+
    '<p>Secure the aircraft in the tuning stand. Use the selected transmitter for the test input.</p>'+
    '<div class="tp-live-facts">'+['Flight mode','Input','Roll rate','Pitch rate','Yaw rate'].map((p,i)=>'<div><span>'+p+'</span>'+out('live'+i)+'</div>').join('')+'</div><p class="tp-note" data-tp-out="capture" role="status">Waiting for live IMU data</p></section>'+
    tracking+'</div></div></div>';
  return '<div class="tp-work" data-tripod="sim"><div class="tp-toolbar"><strong class="tp-tag">Simulator</strong>'+
   select('Simulator input',[['local','Virtual sticks'],['receiver','Kit receiver · read only']],'local')+
   select('Flight mode',[['angle','Angle'],['acro','Rate / Acro']],'angle')+
   '<div class="tp-actions">'+button('run','Run simulator','cfg-primary')+button('stop','Stop')+button('pulse','Step test · 1500 µs')+button('reset','Reset')+'</div>'+
   '<span class="tp-status" role="status" data-tp-out="status">Ready</span></div>'+
   '<div class="tp-body">'+scene(false)+'<div class="tp-rail">'+sticks()+simTracking()+'</div></div>'+
   '<div class="tp-bank-row">'+gainTools()+'<section class="tp-card"><div class="tp-card-head"><h3>Tripod load</h3><small>Simulation estimate</small></div>'+
   '<div class="tp-load">'+['Thrust','Weight','Vertical travel','Motor spread'].map((v,i)=>'<div><span>'+v+'</span>'+out('load'+i)+'</div>').join('')+
   '</div></section></div><div class="tp-bank-row">'+environment()+comparison()+'</div></div>';
}
