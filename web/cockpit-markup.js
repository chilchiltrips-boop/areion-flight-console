const stick=(side,label,caption)=>{
  const ticks=Array.from({length:36},(_,i)=>'<path d="M80 7v'+(i%3?3:6)+'" transform="rotate('+i*10+' 80 80)"/>').join('');
  return '<div class="stick-column"><strong>'+label+'</strong><div class="tx-stick" data-side="'+side+'" aria-label="'+label+' joystick">'+
    '<svg viewBox="0 0 160 160" aria-hidden="true"><circle cx="80" cy="80" r="77" class="dial-edge"/><circle cx="80" cy="80" r="69" class="dial-bed"/><circle cx="80" cy="80" r="42" class="dial-ring"/>'+
    '<g class="dial-ticks">'+ticks+'</g><path d="M8 80h144M80 8v144" class="dial-cross"/><path d="M80 8v6M80 146v6M8 80h6M146 80h6" class="dial-points"/>'+
    '<g data-stick-dot><path d="M80 80v0" class="dial-stem"/><g><circle r="16" class="dial-handle"/><circle r="4.2" class="dial-nub"/></g></g></svg></div><small>'+caption+'</small></div>';
};
const v=(name)=>'<b data-v="'+name+'">—</b>';
const button=(action,label,extra='')=>'<button type="button" data-do="'+action+'" '+extra+'>'+label+'</button>';
const channel=(i)=>'<div class="tx-channel"><small data-ch-name="'+i+'">'+(i+1)+'</small><b data-ch-value="'+i+'">—</b><i><em></em></i></div>';
const motor=i=>'<div><span>M'+(i+1)+'</span><b>—</b><i><em></em></i></div>';
export const HEALTH_ROWS=[['FLIGHT',[['ARM','ARMING'],['MODE','MODE'],['IMU','I²C / IMU'],['OUTPUT','OUTPUT']]],['INPUTS',[['INPUT','INPUT'],['PPM','PPM'],['AP','AP'],['USB','USB']]],['SYSTEM',[['TELEMETRY','TELEMETRY'],['LOOP','LOOP'],['CONFIG','CONFIG'],['STORAGE','STORAGE']]]];
const lights=HEALTH_ROWS.map(([group,tiles])=>'<div class="health-row"><small>'+group+'</small>'+tiles.map(([key,name])=>'<div data-tile="'+key+'" data-tone="idle"><strong>'+name+'</strong><span>OFFLINE</span></div>').join('')+'</div>').join('');
export function cockpitMarkup(){
return `<header class="cockpit-heading"><div><h1>Flight Data</h1><span id="cockpit-tx-badge"></span></div>
<div class="cockpit-source"><span data-v="source">Active: — · Saved: —</span><select aria-label="Flight input source" data-input><option value="0">PPM receiver</option><option value="2">USB channels</option><option value="1">AP Wi-Fi channels</option></select>${button('save-input','Save input','disabled')}</div></header>
<div class="cockpit-grid">
<section class="tx-cabinet" aria-label="Transmitter and GPS"><div class="tx-view-row">${button('joystick','Joystick TX','aria-pressed="true"')}${button('map','GPS map','aria-pressed="false"')}<span data-v="sender">SENDER OFF</span></div>
<div data-view="joystick" class="tx-main"><div class="tx-title"><img src="./assets/console/launch-input.svg" alt=""><h2 data-v="tx-title">Virtual transmitter</h2><small data-v="input-note">Offline</small></div>
<div class="tx-chamber"><div class="tx-stick-row">${stick('left','THROTTLE / YAW','Throttle holds')}${stick('right','PITCH / ROLL','Spring return')}</div><small data-v="stick-note">Local TX channels</small></div>
<div class="tx-mode"><strong data-v="mode">FC MODE: UNKNOWN / STALE</strong>${button('angle','ANGLE','disabled')}${button('rate','RATE / ACRO','disabled')}</div>
<div class="tx-drive">${button('send','Start sender · 50 Hz','disabled')}${button('arm','ARM','disabled')}</div>
<div class="tx-tabs" aria-label="Transmitter controls">${button('channels','Channels 1–8','aria-pressed="true"')}${button('aux','Auxiliary','aria-pressed="false"')}${button('controls','Controls','aria-pressed="false"')}</div>
<div class="tx-detail" data-pane="channels"><div class="tx-channels">${Array.from({length:8},(_,i)=>channel(i)).join('')}</div><small data-v="channel-label">TX command / received FC value</small></div>
<div class="tx-detail" data-pane="aux" hidden><div class="aux-grid">${[4,5,6,7].map(i=>'<label>CH'+(i+1)+' <output>1000</output><input data-aux="'+i+'" type="range" aria-label="Channel '+(i+1)+'" min="1000" max="2000" step="1" value="1000"></label>').join('')}</div><small data-v="switch-info">Flight mode · offline</small></div>
<div class="tx-detail tx-controls" data-pane="controls" hidden><div><label><input data-keyboard type="checkbox" checked> Keyboard control</label> ${button('keys','Configure keys')}</div><small data-v="key-summary"></small><small data-v="pilot-note"></small>${button('record','Recordings')}</div></div>
<div class="gps-cockpit" data-view="map" hidden><h2>GPS map</h2><div><img src="./assets/world-land-110m.svg" alt="World map"></div><strong>Waiting for GPS</strong><small>Position unavailable</small></div></section>
<section class="instrument-deck" aria-label="Flight instruments"><header><h2>Flight instruments</h2>${button('zero','Zero yaw','disabled')}${button('expand','Expand health','aria-pressed="false"')}</header>
<section class="pfd" aria-label="Primary flight display"><div class="yaw-tape"><span>REL YAW</span><canvas aria-hidden="true"></canvas>${v('yaw')}</div><div class="pfd-field"><canvas role="img" aria-label="Artificial horizon"></canvas><strong data-wait>Waiting for live IMU</strong></div>
<div class="pfd-status">${v('armed')}<span data-v="reason">FC disconnected</span><small data-v="flight-mode"></small></div><div class="pfd-angles">${['ROLL','PITCH','TILT'].map(k=>'<div><small>'+k+'</small>'+v(k)+'</div>').join('')}</div></section>
<div class="instrument-lower"><section class="pose-panel" aria-label="IMU attitude"><header><h3>IMU attitude</h3><small data-v="pose-state">OFFLINE</small></header><div class="pose-viewport"><canvas aria-label="Quad X attitude"></canvas><span>Waiting for IMU</span></div>
<div class="pose-numbers">${['ROLL','PITCH','REL YAW'].map(k=>'<div><small>'+k+'</small>'+v('pose-'+k)+'</div>').join('')}</div></section>
<section class="health-panel"><header><h3>System health</h3><div class="health-legend"><i data-tone="good"></i> OK <i data-tone="warn"></i> Warning <i data-tone="bad"></i> Error <i data-tone="idle"></i> Inactive</div></header><div class="health-board">${lights}</div></section></div>
<div class="motor-strip" aria-label="Motor output commands"><small>MOTORS · µs</small>${[0,1,2,3].map(motor).join('')}</div></section></div>
<p data-feedback role="status" hidden></p>
<dialog class="keys-dialog" aria-label="Configure transmitter keys"><h2>Configure keys</h2><div class="key-grid"></div><p role="status"></p><div>${button('cancel-keys','Cancel')}${button('save-keys','Save keys')}</div></dialog>`;
}
