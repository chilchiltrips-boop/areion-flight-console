import {active,copyReport,node,put} from './analysis-common.js';
import {loadManifest,loadRelease} from './firmware-release.js';
import {flashPort} from './firmware-flash.js';
import {mountWifi,wifiPanel} from './firmware-wifi.js';

const supportedVersions=['3.1.0','3.2.0','3.3.0'];
const labels=['Flight controller','FC firmware','Link protocol','Loop target','PWM outputs','PPM input'];
export function mount(root) {
  root.classList.add('ac-surface','fw-page');
  root.innerHTML='<div class="fw-grid"><section class="ac-box fw-card"><header><div><p class="fw-kicker">AREION FC A1</p><h3>USB firmware installer</h3></div><span class="fw-tag" data-release>Release</span></header>'+
    '<label class="fw-field">Operation<select data-mode><option value="update">Update existing kit</option><option value="install">Install / recover board</option></select></label>'+
    '<p class="ac-sub" data-mode-help></p><label class="fw-check"><input type="checkbox" data-safe> Areion FC A1 confirmed. Propellers removed and LiPo disconnected.</label>'+
    '<div class="ac-actions"><button class="fw-primary" data-flash disabled>Update firmware</button><button data-reconnect hidden>Reconnect over USB</button></div>'+
    '<progress data-progress max="100" value="0" aria-label="Firmware installation"></progress><p data-flash-message class="fw-message" role="status"></p></section>'+
    wifiPanel+'</div><section class="ac-box fw-card fw-info"><h3>Controller information</h3><dl class="ac-details"></dl><p class="ac-compat"></p>'+
    '<div class="ac-actions"><button data-read disabled>Read kit information</button><button data-copy>Copy diagnostics</button></div><div class="ac-note" role="status"></div></section>';
  const find=name=>root.querySelector('[data-'+name+']');
  const details=root.querySelector('dl'),compat=root.querySelector('.ac-compat'),note=root.querySelector('.ac-note');
  const values=labels.map(label=>{const value=node('dd','—');details.append(node('dt',label),value);return value;});
  const wifi=mountWifi(root),mode=find('mode'),safe=find('safe'),read=find('read'),flash=find('flash');
  const reconnect=find('reconnect'),progress=find('progress'),stage=find('flash-message');
  let ctx=null,busy=false,flashing=false,generation=0,verified=null,expectedKit=null,flashHandle=null,waitForBoot=false;
  if (typeof window!=='undefined') {
    loadManifest().then(m=>put(find('release'),'Release '+m.version)).catch(()=>put(find('release'),'Package unavailable'));
  }
  function flashControls() {
    const connected=ctx?.state==='connected',usb=connected && ctx.path==='USB' && ctx.link?.source===2;
    const idle=ctx?.state==='offline' || ctx?.state==='error';
    const updateKit=mode.value!=='install';
    safe.disabled=mode.disabled=flashing;
    flash.disabled=flashing || !safe.checked || !ctx?.withFirmwarePort || !!ctx.browser?.usb || ctx.replay ||
      !(usb && ctx.group(120,1500)?.[0]===false || !updateKit && idle);
    put(flash,updateKit?'Update firmware':'Flash board');
    put(find('mode-help'),updateKit?'Connect the kit over USB. The update uses the spare app slot and keeps saved flight settings.':
      'For a new or recovering board. Reinstalls the bootloader and application. Saved settings on the Areion layout are preserved.');
    if (!stage.textContent && ctx?.browser?.usb) put(stage,ctx.browser.usb);
    reconnect.hidden=!waitForBoot || flashing || !idle;
  }
  mode.onchange=()=>{safe.checked=false;flashControls();};safe.onchange=flashControls;
  reconnect.onclick=()=>ctx?.reconnectFirmwarePort?.(flashHandle);
  flash.onclick=async()=>{
    if (flash.disabled || flashing) return;
    const record=ctx.diagnosticScope?.();let lastStage='';
    const trace=(status,detail)=>record?.({kind:'firmware',name:'USB firmware '+mode.value,status,detail});
    flashing=true;waitForBoot=false;verified=null;expectedKit=null;flashHandle=null;progress.value=0;flashControls();
    put(stage,'Preparing USB and checking the firmware package…');
    try {
      const result=await ctx.withFirmwarePort(mode.value,loadRelease,async(port,release)=>{
        put(find('release'),'v'+release.version);
        const outcome=await flashPort(port,release,mode.value,(percent,message)=>{progress.value=percent;put(stage,message);if(message!==lastStage){lastStage=message;trace('progress',message);}});
        expectedKit=release.kitId || null;flashHandle=port;
        return {...outcome,version:release.version};
      });
      progress.value=100;verified=result.version;waitForBoot=true;
      put(stage,result.reset?'Images verified. Reconnect over USB to confirm the running version.':
        'Images verified. Press RESET on the board, then reconnect over USB.');
    } catch (error) {
      put(stage,error.name==='NotFoundError'?'USB port selection cancelled.':
        /failed to connect|sync|timed out waiting for packet/i.test(error.message)?
        'Bootloader did not respond. Hold BOOT, tap RESET, release BOOT, then retry.':error.message || 'Firmware operation failed.');
    } finally {trace(verified?'ok':'error',stage.textContent);flashing=false;safe.checked=false;flashControls();}
  };
  find('copy').onclick=()=>ctx && copyReport(ctx,note).catch(error=>put(note,error.message));
  read.onclick=async()=>{
    if(!ctx || busy || ctx.replay || ctx.state!=='connected')return;
    const request=++generation;busy=true;read.disabled=true;put(note,'Reading kit information…');
    try {const info=await ctx.link.readGroup(125);if(request===generation)put(note,'Received firmware '+info[0]+'.');}
    catch(error){if(request===generation)put(note,error.message || 'Could not read kit information.');}
    finally{if(request===generation){busy=false;update(ctx);}}
  };
  function update(next) {
    if(!next)return;
    if(ctx && (ctx.model!==next.model || ctx.state!==next.state || ctx.link!==next.link)) {
      generation++;busy=false;note.replaceChildren();
    }
    ctx=next;wifi.update(next);flashControls();
    read.disabled=busy || flashing || ctx.replay || ctx.state!=='connected' || !ctx.link?.readGroup;
    const info=active(ctx)?ctx.group(125):null;
    const entries=['Areion FC A1',info?.[0] || '—','2',info?info[1]+' Hz':'—',info?info[7]+' Hz · '+info[8]+' bits':'—',info?'GPIO '+info[2]:'—'];
    entries.forEach((value,index)=>put(values[index],value));
    const match=supportedVersions.includes(info?.[0]);
    put(compat,!info?'Waiting for the kit firmware version.':ctx.replay?'Version reported in this recording.':match?'Compatible with this console.':'Firmware version differs from the supported releases.');
    compat.dataset.state=!info?'Waiting':match?'Live':'Stale';
    if (waitForBoot && ctx.state==='connected' && ctx.path==='USB' && !ctx.replay && info && (!expectedKit || ctx.group(130))) {
      waitForBoot=false;
      const sameBoard=expectedKit?ctx.group(130)[15]===expectedKit:ctx.link?.current?.port===flashHandle;
      put(stage,!sameBoard?'Connected kit reports '+info[0]+'. Verify the flashed board using its original USB port.':
        info[0]===verified?'Kit reports firmware '+verified+'. Update confirmed.':
        'Connected kit reports '+info[0]+'. Expected '+verified+'. Check the chosen port and boot status.');
      ctx.diagnosticScope?.()({kind:'firmware',name:'Verify running firmware',status:sameBoard&&info[0]===verified?'ok':'error',detail:stage.textContent});
    }
  }
  return {update,suspend(){wifi.reset();safe.checked=false;},reset(){generation++;busy=false;ctx=null;read.disabled=true;note.replaceChildren();wifi.reset();safe.checked=false;}};
}
