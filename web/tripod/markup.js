import {banks,terms,limits} from './gains.js';
import {exercises} from './tripod-experiments.js';
import {inputNames} from './inputs.js';

const select=(name, entries, value)=>'<select data-tp="'+name+'" aria-label="'+name+'">'+entries.map(([k,label])=>
  '<option value="'+k+'"'+(k===value?' selected':'')+'>'+label+'</option>').join('')+'</select>';
const button=(name,label,cls='')=>'<button type="button" data-tp-action="'+name+'" class="cfg-btn '+cls+'">'+label+'</button>';
const out=(key,value='—')=>'<output data-tp-out="'+key+'">'+value+'</output>';
const field=(name,control)=>'<label class="tp-field"><span>'+name+'</span>'+control+'</label>';
const plotModes=[['response','Target / measured'],['terms','P / I / D terms'],['motors','Motor pulses'],['rpm','Motor RPM'],['travel','Slider travel']];
const cameraViews=[['isometric','Isometric'],['rear','Pilot view · rear'],['front','Front'],['left','Left'],['right','Right'],['top','Top'],['follow','Follow yaw'],['orbit','Free orbit']];
const axes=[['roll','Roll'],['pitch','Pitch'],['yaw','Yaw']];
function scene() {
  return '<section class="tp-card tp-model"><div class="tp-card-head"><h3>F450 tripod</h3>'+select('Camera view',cameraViews,'rear')+'</div>'+
    '<div class="tp-stage" data-tp-stage><span class="tp-stage-source">Simulated attitude</span><span class="tp-stage-mode" data-tp-out="sourceMode"></span><span class="tp-model-info" data-tp-out="model">Loading F450</span></div>'+
    '<div class="tp-attitudes">'+['Roll','Pitch','Yaw'].map((label,i)=>'<div><span>'+label+'</span>'+out('att'+i)+'</div>').join('')+'</div>'+
    '<div class="tp-motors" aria-label="Simulated motor outputs">'+['Front left','Front right','Rear right','Rear left'].map((pos,i)=>
      '<div title="'+pos+'"><div class="tp-motor-label"><b>M'+(i+1)+'</b>'+out('motor'+i)+'</div><div class="tp-bar"><i data-tp-bar="'+i+'"></i></div><small>'+out('motorDetail'+i,pos)+'</small></div>').join('')+'</div>'+effects()+'</section>';
}
function sticks(){
  const pad=(side,label,axes,caption)=>'<div class="tp-gimbal"><label>'+label+'</label><div class="tp-pad" data-pad="'+side+'" tabindex="0" role="group" aria-label="'+label+' joystick"><i></i></div>'+
    '<div class="tp-channels">'+axes.map(([key,name])=>'<div><span>'+name+'</span>'+out(key,'—')+'</div>').join('')+'</div><small>'+caption+'</small></div>';
  return '<section class="tp-card tp-input"><div class="tp-card-head"><h3>Transmitter</h3>'+select('Simulator input',Object.entries(inputNames),'local')+'</div>'+
    '<div class="tp-stick-pair">'+pad('left','Throttle / yaw',[['throttle','THR'],['yawCh','YAW']],'Throttle holds')+pad('right','Pitch / roll',[['pitchCh','PIT'],['rollCh','ROL']],'Spring return')+'</div>'+
    '<div class="tp-input-foot"><label class="tp-range">Virtual throttle<input data-tp="Throttle" aria-label="Virtual throttle" type="range" min="1000" max="2000" step="1" value="1000"></label>'+
    '<a class="tp-kit-input" data-kit-input-link href="#configuration/input" hidden>Kit input settings</a><small data-tp-out="receiver"></small><small data-tp-out="keys">Arrow keys · roll / pitch &nbsp; · &nbsp; A / D · yaw &nbsp; · &nbsp; W / S · throttle</small></div></section>';
}
function gainTools(){
  function matrix(title,names,note){
    return '<div class="tp-gain-panel" data-loop="'+(names.length===3?'rate':'angle')+'"><div class="tp-card-head"><h4>'+title+'</h4><small>'+note+'</small></div><table><thead><tr><td></td>'+
      names.map(n=>'<th scope="col">'+n.replace(/^(rate|angle)/,'')+'</th>').join('')+'</tr></thead><tbody>'+
      terms.map(k=>'<tr><th scope="row">'+k.toUpperCase()+'</th>'+names.map(n=>{
        const name=n.replace(/([A-Z])/,' $1');
        return '<td><input type="number" min="0" max="'+limits[k]+'" step="any" data-gain="'+n+'.'+k+'" aria-label="Simulator '+name+' '+k.toUpperCase()+'"></td>';
      }).join('')+'</tr>').join('')+'</tbody></table></div>';
  }
  return '<section class="tp-card tp-bank"><div class="tp-card-head"><h3>Practice gains</h3>'+out('loopState')+'</div><div class="tp-matrices">'+
    matrix('Rate PID',banks.slice(0,3),'Inner loop')+matrix('Attitude PID',banks.slice(3),'Outer loop')+'</div>'+
    '<div class="tp-actions">'+button('apply','Apply & compare','cfg-primary')+'<label><input type="checkbox" data-tp="Live preview" checked> Live preview</label>'+button('restore','Restore baseline')+button('defaults','Factory gains')+button('load','Read kit gains')+'</div>'+
    '<p class="tp-note" role="status" data-tp-out="gainNote">Yaw uses rate PID in both flight modes.</p></section>';
}
function effects(){
  return '<div class="tp-effects"><label class="tp-sound"><input type="checkbox" data-tp="Sound" checked> Motor sound</label>'+
    select('Motor sound profile',[['quiet','Quiet'],['normal','Normal'],['detailed','Detailed']],'normal')+
    '<label class="tp-volume">Volume <input type="range" min="0" max="100" step="1" data-tp="Volume" aria-label="Motor volume" value="55">'+out('volume','55%')+'</label>'+
    select('Airflow',[['normal','Airflow · normal'],['soft','Airflow · soft'],['off','Airflow off']],'normal')+
    '<small data-tp-out="audioState" role="status"></small></div>';
}
const conditions=[['batteryV','Battery','V',9,12.6,.1],['payloadG','Payload','g',0,650,10],['cgX','Roll CG offset','mm',-25,25,1],['cgY','Pitch CG offset','mm',-25,25,1],['wind','Wind','%',0,100,1],['lag','Motor lag','s',.04,.30,.01],['gyroNoise','Gyro noise','°/s',0,2,.01]];
function environment(){
 return '<details class="tp-card"><summary>Test conditions</summary><div class="tp-condition-grid">'+conditions.map(([k,label,unit,min,max,step])=>
   '<label class="tp-range">'+label+out(k)+'<input type="range" data-env="'+k+'" data-unit="'+unit+'" aria-label="'+label+'" min="'+min+'" max="'+max+'" step="'+step+'"></label>').join('')+'</div>'+
   '<div class="tp-actions">'+button('tilt','Drag to tilt')+button('level','Set level')+button('integrator','Reset integrators')+
   '</div></details>';
}
function comparison(){
  const scenarioChoices=Object.entries(exercises).map(([key,exercise])=>[key,exercise.label]);
  const metrics=['Tracking RMS','Final 0.5 s error','Peak movement','Final orientation'];
  return '<section class="tp-card tp-practice"><div class="tp-card-head"><h3>Before &amp; after</h3>'+out('practiceMode')+'</div>'+
    '<div class="tp-exercise">'+field('Exercise',select('Practice exercise',scenarioChoices,'step'))+field('Axis',select('Practice axis',axes,'roll'))+'</div>'+
    '<p class="tp-note" data-tp-out="lessonHint"></p>'+
    '<div class="tp-legend"><span style="--ink:#a8b8ff">Stick target</span><span style="--ink:#ffbd77">Baseline</span><span style="--ink:#70e3cb">Tuned</span></div>'+
    '<canvas data-tp-plot="compare" role="img" aria-label="Stick target, baseline response and tuned response over five seconds"></canvas>'+
    '<table class="tp-score"><thead><tr><th scope="col">Measurement</th><th scope="col">Baseline</th><th scope="col">Tuned</th></tr></thead><tbody>'+
    metrics.map((label,i)=>'<tr><th scope="row" data-metric="'+i+'">'+label+'</th><td>'+out('before'+i)+'</td><td>'+out('after'+i)+'</td></tr>').join('')+
    '</tbody></table><p class="tp-note" role="status" data-tp-out="compare"></p>'+
    '<div class="tp-actions">'+button('play','Play on stand','cfg-primary')+button('baseline','Use tuned gains as baseline')+'</div></section>';
}
function simTracking(){
 return '<section class="tp-card tp-plot"><div class="tp-card-head"><h3>Response</h3>'+select('Plot',plotModes,'response')+'</div>'+
 '<div class="tp-plot-controls">'+select('Test axis',axes,'roll')+select('Plot loop',[['auto','Flight response'],['rate','Inner rate loop']],'auto')+button('freeze','Freeze graph')+'<div class="tp-legend" data-tp-legend></div></div>'+
 '<canvas data-tp-plot="sim" role="img" aria-label="Virtual target and measured response"></canvas>'+
 '<div class="tp-targets">'+out('command')+out('measured')+'</div><div class="tp-plot-metrics">'+out('error')+out('peak')+'</div></section>';
}
export function tripodMarkup() {
  return '<div class="tp-work" data-tripod="sim"><div class="tp-toolbar"><strong class="tp-tag">Simulator</strong>'+
   field('Flight mode',select('Flight mode',[['angle','Angle'],['acro','Rate / Acro'],['follow','Follow receiver switch']],'angle'))+
   '<div class="tp-actions">'+button('run','Run simulator','cfg-primary')+button('stop','Stop')+button('reset','Reset stand')+button('practice','Tune gains ↓')+'</div>'+
   '<span class="tp-status" role="status" data-tp-out="status">Ready</span></div>'+
   '<p class="tp-mode-guide" data-tp-out="modeGuide"></p>'+
   '<div class="tp-body">'+scene()+'<div class="tp-rail">'+sticks()+simTracking()+'</div></div>'+
   '<div class="tp-lab">'+gainTools()+comparison()+'</div><div class="tp-bank-row"><section class="tp-card"><div class="tp-card-head"><h3>Tripod load</h3><small>Simulation estimate</small></div>'+
   '<div class="tp-load">'+['Thrust','Weight','Vertical travel','Motor spread'].map((v,i)=>'<div><span>'+v+'</span>'+out('load'+i)+'</div>').join('')+
   '</div></section><div class="tp-rail">'+environment()+'</div></div></div>';
}
