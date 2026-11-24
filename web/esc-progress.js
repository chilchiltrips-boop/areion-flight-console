export const ESC_STEP=5;
export const escStates=['Not scheduled','Scheduled for next power-up','Running endpoint sequence','Awaiting ESC response','ESC response confirmed','Calibration skipped','Sequence interrupted'];
const key=id=>'areion.setup.esc.'+id;

export function markEsc(id,remember,storage) {
  if(!id)return;
  try {
    const store=storage??globalThis.localStorage;
    if(remember)store.setItem(key(id),'1');else store.removeItem(key(id));
  } catch { /* Live controller state also supports recovery without browser storage. */ }
}

export function resumeEsc(setup,storage) {
  if(!setup?.[15] || setup[0]!==true || setup[1]!==false)return false;
  if([1,2,3,6].includes(setup[3]))return true;
  if(!setup[5] || setup[2]<1)return false;
  try {return (storage??globalThis.localStorage).getItem(key(setup[15]))==='1';}catch{return false;}
}

export function escPrerequisite(setup,config) {
  if(!setup || !config)return 'Waiting for kit settings.';
  if(!setup[5])return 'Complete the Sensors check on this kit.';
  if(config[1]===0&&!setup[6])return 'Complete the PPM receiver check on this kit.';
  return '';
}

export function escInstruction(setup,config,imuReady) {
  if(!setup)return 'Reconnect the kit over USB or AP Wi-Fi to read its saved ESC state.';
  switch(setup[3]){
    case 1:return 'Request saved. Disconnect USB and LiPo, then power up following your ESC instructions. Reconnect here.';
    case 2:return 'The controller is running the endpoint sequence. Keep power connected.';
    case 3:return imuReady?'The controller finished the sequence. Confirm only if you heard the expected ESC response.':'Sequence finished. Waiting for the controller IMU to finish starting.';
    case 4:return 'ESC response confirmed. Continue to motor outputs.';
    case 5:return 'Endpoint calibration was skipped. Continue to motor outputs.';
    case 6:return 'Sequence interrupted'+(setup[14]?' · '+setup[14]:'')+'. Review the ESCs before scheduling a new attempt.';
    default:return escPrerequisite(setup,config)||'Schedule calibration for the next kit startup.';
  }
}
