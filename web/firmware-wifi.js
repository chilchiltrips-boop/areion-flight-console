import {put} from './analysis-common.js';

export const wifiPanel = '<section class="ac-box fw-card"><header><div><p class="fw-kicker">NETWORK</p><h3>Kit Wi-Fi</h3></div><span class="fw-tag">USB only</span></header>'+
  '<div class="fw-network"><span>Active network <strong data-ap-active>—</strong></span><span>Saved network <strong data-ap-saved>—</strong></span></div>'+
  '<label class="fw-field">Wi-Fi name (SSID)<input data-ap-name autocomplete="off" placeholder="aerion drone" maxlength="32" spellcheck="false"></label>'+
  '<label class="fw-field">New password<input data-ap-key type="password" autocomplete="new-password" maxlength="63" placeholder="8–63 printable characters" spellcheck="false"></label>'+
  '<div class="ac-actions"><button data-ap-save disabled>Save Wi-Fi</button><button data-ap-read disabled>Read Wi-Fi</button><button data-ap-recover disabled>Recover access</button></div>'+
  '<div data-ap-recovery class="fw-recovery" hidden><p>Restore <b>aerion drone</b> with a new password. Restart the kit after saving.</p>'+
  '<div class="ac-actions"><button data-ap-confirm>Restore Wi-Fi</button><button data-ap-cancel>Cancel</button></div></div>'+
  '<div data-ap-result class="fw-recovery" hidden><label class="fw-field">New recovery password<input data-ap-secret type="password" autocomplete="off" readonly></label>'+
  '<button data-ap-show>Show password</button></div><p data-ap-message class="fw-message" role="status"></p></section>';

export function recoveryPassword() {
  const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  return Array.from(crypto.getRandomValues(new Uint8Array(20)),byte=>alphabet[byte&63]).join('');
}
const asciiPassword=value=>typeof value==='string' && /^[\x20-\x7e]{8,63}$/.test(value);
export function mountWifi(root) {
  const el=name=>root.querySelector('[data-ap-'+name+']');
  const name=el('name'),key=el('key'),secret=el('secret'),result=el('result'),recovery=el('recovery'),message=el('message');
  let ctx=null,identity=null,busy=false,seq=0,readOnce=false,notice='',dirty=false;
  const usable=()=>ctx?.state==='connected' && !ctx.replay && ctx.path==='USB' && ctx.link?.source===2;
  const compatible=()=>{
    const parts=String(ctx?.group(125)?.[0]||'').split('.').map(Number);
    return parts[0]===3 && parts[1]>=3;
  };
  function draw() {
    const can=usable() && compatible() && !ctx.firmwareBusy && !busy;
    const disarmed=can && ctx.group(120,1500)?.[0]===false;
    el('read').disabled=!can;
    el('save').disabled=!disarmed || !name.value || new TextEncoder().encode(name.value).length>32 ||
      /[\x00-\x1f\x7f]/.test(name.value) || !asciiPassword(key.value);
    el('recover').disabled=el('confirm').disabled=!disarmed;
    name.disabled=key.disabled=!can;
    put(message,notice || (!usable()?'Connect the kit over USB.':!compatible()?'USB Wi-Fi settings require firmware 3.3.0 or later.':
      !disarmed?'Waiting for a disarmed kit.':'Changes take effect at the next restart.'));
  }
  function clear() {
    seq++; busy=false; readOnce=false; dirty=false; notice='';
    key.value=name.value=secret.value=''; secret.type='password';
    put(el('show'),'Show password'); recovery.hidden=result.hidden=true;
    put(el('active'),'—');put(el('saved'),'—');
  }
  async function perform(operation) {
    if (busy || !usable() || !compatible()) return;
    const ticket=++seq, link=ctx.link, identityAtStart=identity;
    const current=()=>ticket===seq && identity===identityAtStart && link.current===identityAtStart;
    busy=true;notice=operation==='read'?'Reading Wi-Fi settings…':'Saving Wi-Fi settings…';draw();
    let acknowledged=false;
    try {
      if (operation!=='read') {
        if (ctx.group(120,1500)?.[0]!==false) throw Error('Disarm the kit first.');
        if (operation==='recover') {
          secret.value=recoveryPassword();secret.type='password';put(el('show'),'Show password');
          recovery.hidden=true;result.hidden=false;
          await link.action(138,['RECOVER_AP',secret.value]);
        } else await link.action(138,['SET_AP',name.value,key.value]);
        acknowledged=true;
      }
      if (!current()) return;
      const [active,saved,configured,restart]=await link.readGroup(139);
      if (!current()) return;
      put(el('active'),active || 'Off');put(el('saved'),configured?saved:'Unconfigured');
      if (!dirty || operation!=='read') {name.value=saved || 'aerion drone';dirty=false;}
      if (operation!=='read') {
        key.value='';
        if (operation==='save') {result.hidden=true;secret.value='';}
      }
      notice=restart?(operation==='recover'?'Access restored. Keep the new password, then restart the kit.':'Saved. Restart the kit to use these credentials.'):
        configured?'Saved network is available on the kit.':'Set a Wi-Fi name and password to enable the access point.';
    } catch (error) {
      if (current()) notice=acknowledged?'Kit acknowledged the save. Use Read Wi-Fi to verify.':
        error.code==='BUSY'?'The kit is busy. Choose Read Wi-Fi or try again.':(error.message || 'USB request failed.');
    } finally {if (current()) {busy=false;draw();}}
  }
  name.oninput=()=>{dirty=true;draw();};key.oninput=draw;
  el('read').onclick=()=>perform('read');el('save').onclick=()=>perform('save');
  el('recover').onclick=()=>{recovery.hidden=false;};el('cancel').onclick=()=>{recovery.hidden=true;};
  el('confirm').onclick=()=>perform('recover');
  el('show').onclick=()=>{secret.type=secret.type==='password'?'text':'password';put(el('show'),secret.type==='text'?'Hide password':'Show password');};
  return {
    update(next) {
      ctx=next;
      const nextId=usable()?next.link.current:null;
      if (nextId!==identity) {clear();identity=nextId;}
      draw();
      if (nextId && compatible() && !readOnce && !ctx.firmwareBusy) {readOnce=true;void perform('read');}
    },
    reset(){clear();ctx=null;identity=null;draw();}
  };
}
