import {active,copyReport,node,put} from './analysis-common.js';
import {loadManifest,loadRelease,reportsComponents} from './firmware-release.js';
import {flashAp} from './firmware-ota.js';
import {flashPort} from './firmware-flash.js';
import {mountWifi,wifiPanel} from './firmware-wifi.js';

const supportedVersions=['3.1.0','3.2.0','3.3.0','3.4.0'];
const labels=['Flight controller','Installed FC firmware','Available firmware','Installed Link library','Installed PPM library','Release libraries','Link protocol','Loop target','PWM outputs','PPM input'];
export function mount(root) {
  root.classList.add('ac-surface','fw-page');
  root.innerHTML='<div class="fw-grid"><section class="ac-box fw-card"><header><div><p class="fw-kicker">AREION FC A1</p><h3>Firmware update</h3></div><span class="fw-tag" data-release>Release</span></header>'+
    '<label class="fw-field">Operation<select data-mode><option value="update">Update via USB</option><option value="ap">Update via AP Wi-Fi</option><option value="install">Install / recover board</option></select></label>'+
    '<p class="ac-sub" data-mode-help></p><label class="fw-check"><input type="checkbox" data-safe> Areion FC A1 confirmed. Propellers removed and LiPo disconnected.</label>'+
    '<div class="ac-actions"><button class="fw-primary" data-flash disabled>Update firmware</button><button data-reconnect hidden>Reconnect over USB</button></div>'+
    '<progress data-progress max="100" value="0" aria-label="Firmware installation"></progress><p data-flash-message class="fw-message" role="status"></p></section>'+
    wifiPanel+'</div><section class="ac-box fw-card fw-info"><h3>Controller information</h3><dl class="ac-details"></dl><p class="ac-compat"></p>'+
    '<div class="ac-actions"><button data-read disabled>Read kit information</button><button data-copy>Copy diagnostics</button><a data-sources hidden download="areion-arduino.zip">Arduino sketch &amp; libraries</a></div><div class="ac-note" role="status"></div></section>';
  const find=name=>root.querySelector('[data-'+name+']');
  const details=root.querySelector('dl'),compat=root.querySelector('.ac-compat'),note=root.querySelector('.ac-note');
  const values=labels.map(label=>{const value=node('dd','—');details.append(node('dt',label),value);return value;});
  const wifi=mountWifi(root),mode=find('mode'),safe=find('safe'),read=find('read'),flash=find('flash');
  const reconnect=find('reconnect'),progress=find('progress'),stage=find('flash-message');
  let ctx=null,busy=false,flashing=false,generation=0,verified=null,expectedKit=null,flashHandle=null,waitForBoot=false;
  let releaseInfo=null,previousBoot=null,transferMode=null,connection=null;
  function showRelease(m){
    releaseInfo=m;put(find('release'),'Release '+m.version);
    const sources=find('sources');sources.hidden=!m.sources;
    if(m.sources)sources.href=new URL('firmware-release/'+m.sources.file,import.meta.url).href;
    if(ctx)update(ctx);
  }
  if(typeof window!=='undefined')loadManifest().then(showRelease).catch(()=>put(find('release'),'Package unavailable'));
  function flashControls() {
    const connected=ctx?.state==='connected',usb=connected && ctx.path==='USB' && ctx.link?.source===2;
    const idle=ctx?.state==='offline' || ctx?.state==='error';
    const wireless=mode.value==='ap',updateKit=mode.value!=='install',setup=ctx?.group(130,1500);
    const ready=connected&&ctx.group(120,1500)?.[0]===false&&setup&&!setup[8]&&![1,2].includes(setup[3]);
    const ap=ctx?.path==='AP'&&ctx?.link?.source===1;
    safe.disabled=mode.disabled=flashing;
    flash.disabled=flashing || !safe.checked || !ctx?.withFirmwarePort || ctx.replay ||
      (wireless ? !(ap&&ready&&ctx.group(141)?.[3]===true) : !!ctx?.browser?.usb || !(usb&&ready||!updateKit&&idle));
    put(flash,wireless?'Update via AP':updateKit?'Update firmware':'Flash board');
    let help=updateKit?'Connect the kit over USB. The update uses the spare app slot and keeps saved flight settings.':
      'For a new or recovering board. Reinstalls the bootloader and application. Saved settings on the Areion layout are preserved.';
    if(wireless){
      help='Use stable USB power. Join the kit Wi-Fi, connect over AP, then hold BOOT while starting the update. Release BOOT when writing starts.';
      if(ap&&connected&&!ctx.group(141)?.[3]){
        const installed=ctx.group(125)?.[0];
        help=installed&&!reportsComponents(installed)?'AP updates require firmware 3.4.0 or later. Update this kit once over USB.':
          'Waiting for kit capabilities. Choose Read kit information to retry.';
      }
    }
    put(find('mode-help'),help);
    if (!wireless && !stage.textContent && ctx?.browser?.usb) put(stage,ctx.browser.usb);
    put(reconnect,transferMode==='ap'?'Reconnect over AP':'Reconnect over USB');
    reconnect.hidden=!waitForBoot || flashing || !idle;
  }
  mode.onchange=()=>{safe.checked=false;flashControls();};safe.onchange=flashControls;
  reconnect.onclick=()=>transferMode==='ap'?ctx?.toggleUsb?.():ctx?.reconnectFirmwarePort?.(flashHandle);
  flash.onclick=async()=>{
    if (flash.disabled || flashing) return;
    transferMode=mode.value;previousBoot=ctx.link?.fcSession;
    const wireless=transferMode==='ap';
    const record=ctx.diagnosticScope?.();let lastStage='';
    const trace=(status,detail)=>record?.({kind:'firmware',name:(wireless?'AP':'USB')+' firmware '+transferMode,status,detail});
    flashing=true;waitForBoot=false;verified=null;expectedKit=null;flashHandle=null;progress.value=0;flashControls();
    put(stage,'Checking the firmware package…');
    try {
      const result=await ctx.withFirmwarePort(transferMode,loadRelease,async(port,release)=>{
        put(find('release'),'v'+release.version);
        const onProgress=(percent,message)=>{progress.value=percent;put(stage,message);if(message!==lastStage){lastStage=message;trace('progress',message);}};
        const outcome=wireless?await flashAp(port,release,onProgress):await flashPort(port,release,transferMode,onProgress);
        expectedKit=release.kitId || null;flashHandle=port;
        return {...outcome,version:release.version};
      });
      progress.value=100;verified=result.version;waitForBoot=true;
      put(stage,wireless?'Image verified on the kit. Release BOOT, rejoin its Wi-Fi after restart and reconnect to confirm the running version.':result.reset?'Images verified. Reconnect over USB to confirm the running version.':
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
    try {const info=await ctx.link.readGroup(125);
      if(request===generation&&reportsComponents(info[0]))await ctx.link.readGroup(141);
      if(request===generation)put(note,'Received firmware '+info[0]+'.');}
    catch(error){if(request===generation)put(note,error.message || 'Could not read kit information.');}
    finally{if(request===generation){busy=false;update(ctx);}}
  };
  function update(next) {
    if(!next)return;
    if(ctx && (ctx.model!==next.model || ctx.state!==next.state || ctx.link!==next.link)) {
      generation++;busy=false;note.replaceChildren();
    }
    ctx=next;
    if(!flashing&&ctx.state==='connected'&&!ctx.replay&&connection!==ctx.link.current){
      connection=ctx.link.current;mode.value=ctx.path==='AP'?'ap':'update';safe.checked=false;
    }
    wifi.update(next);flashControls();
    read.disabled=busy || flashing || ctx.replay || ctx.state!=='connected' || !ctx.link?.readGroup;
    const info=active(ctx)?ctx.group(125):null;
    const components=info?ctx.group(141):null,legacy=info?'Not reported':'—';
    const entries=[components?.[0]||'Areion FC A1',info?.[0] || '—',releaseInfo?.version||'—',components?.[1]||legacy,components?.[2]||legacy,releaseInfo?.libraries?'Link '+releaseInfo.libraries.ZebjusAreionLink+' · PPM '+releaseInfo.libraries.ZebjusPpm:'—','2',info?info[1]+' Hz':'—',info?info[7]+' Hz · '+info[8]+' bits':'—',info?'GPIO '+info[2]:'—'];
    entries.forEach((value,index)=>put(values[index],value));
    const match=supportedVersions.includes(info?.[0]);
    put(compat,!info?'Waiting for the kit firmware version.':ctx.replay?'Version reported in this recording.':releaseInfo?.version===info[0]?'Running the current release.':match&&releaseInfo?'Kit '+info[0]+' · available '+releaseInfo.version+'.':match?'Compatible with this console.':'Firmware version differs from the supported releases.');
    compat.dataset.state=!info?'Waiting':match?'Live':'Stale';
    if (waitForBoot && ctx.state==='connected' && (!previousBoot||previousBoot!==ctx.link.fcSession) && !ctx.replay && info && (!expectedKit || ctx.group(130))) {
      const sameBoard=expectedKit?ctx.group(130)[15]===expectedKit:ctx.link?.current?.port===flashHandle;
      if(!sameBoard){put(stage,'A different kit is connected. Reconnect the updated board to verify it.');return;}
      waitForBoot=false;
      put(stage,
        info[0]===verified?'Kit reports firmware '+verified+'. Update confirmed.':
        'Connected kit reports '+info[0]+'. Expected '+verified+'. Check the chosen port and boot status.');
      ctx.diagnosticScope?.()({kind:'firmware',name:'Verify running firmware',status:sameBoard&&info[0]===verified?'ok':'error',detail:stage.textContent});
    }
  }
  return {update,suspend(){wifi.reset();safe.checked=false;},reset(){generation++;busy=false;ctx=null;read.disabled=true;note.replaceChildren();wifi.reset();safe.checked=false;}};
}
