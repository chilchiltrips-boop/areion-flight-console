// The public console supplies a hash-verified release. Each owner-scoped Link v2
// action acknowledges the next byte offset before another chunk may be sent.
const hex=Array.from({length:256},(_,i)=>i.toString(16).padStart(2,'0'));
export async function flashAp(link,release,progress=()=>{}) {
  const image=release.images.application,session=link.session,boot=link.fcSession,run=link.current;
  const sameKit=()=>link.current===run&&link.session===session&&link.fcSession===boot&&link.state==='connected';
  const send=async(values,expected)=>{
    if(!sameKit())throw Error('AP connection changed during the update.');
    const ack=await link.action(140,values);
    if(!sameKit()||ack?.[0]!==expected)throw Error('Kit did not confirm '+values[0]+'.');
  };
  let started=false,finishing=false;
  try {
    progress(0,'Hold the kit BOOT button to authorize this update.');
    await send(['BEGIN',image.data.length,image.sha256],'OTA_READY');started=true;
    let percent=-1;
    for(let offset=0;offset<image.data.length;offset+=512){
      const end=Math.min(offset+512,image.data.length),values=['DATA',offset];
      for(let i=offset;i<end;i+=64)values.push(Array.from(image.data.subarray(i,Math.min(i+64,end)),b=>hex[b]).join(''));
      await send(values,'OTA_OFFSET_'+end);
      const next=Math.floor(98*end/image.data.length);
      if(next!==percent){percent=next;progress(percent,'Writing the spare app slot. Release BOOT and keep the kit powered.');}
    }
    progress(99,'Verifying the image on the kit…');finishing=true;
    await send(['FINISH'],'OTA_RESTART');
    return {reset:true,version:release.version};
  } catch(error) {
    if(started && sameKit())await link.action(140,['ABORT']).catch(()=>{});
    if(error.code==='OTA_HOLD_BOOT')throw Error('Hold BOOT on the powered kit while clicking Update via AP, then release it when writing starts.');
    if(finishing)throw Error('Final verification was not confirmed ('+error.message+'). Reconnect and read the running FC version.');
    throw error;
  }
}
