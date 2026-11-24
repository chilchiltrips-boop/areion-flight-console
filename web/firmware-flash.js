import {fixedPartitions,layout,sector,slotAddress} from './firmware-release.js';

const uintMax=0xffffffff;
const sameBytes=(a,b)=>a.length===b.length && a.every((v,i)=>v===b[i]);

// ESP-IDF bootloader_common_ota_select_crc uses esp_rom_crc32_le(UINT32_MAX, seq, 4).
export function selectionCrc(sequence) {
  let crc=0;
  for (let i=0;i<4;i++) {
    crc^=(sequence>>>(8*i))&255;
    for (let bit=0;bit<8;bit++) crc=(crc>>>1)^((crc&1)?0xedb88320:0);
  }
  return (~crc)>>>0;
}
export function nextSelection(bytes) {
  if (bytes.length!==2*sector) throw Error('Incomplete boot selection read.');
  const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  const records=[0,1].map(index=>{
    const p=index*sector,seq=view.getUint32(p,true),state=view.getUint32(p+24,true);
    return {index,seq,state,valid:seq!==uintMax && [0,1,2,uintMax].includes(state) &&
      view.getUint32(p+28,true)===selectionCrc(seq)};
  });
  const current=records.filter(r=>r.valid).sort((a,b)=>b.seq-a.seq)[0];
  if (!current || current.seq===0 || current.seq>=uintMax-1)
    throw Error('Boot selection is unavailable. Use Install / recover to install the release.');
  if (current.state===0 || current.state===1) throw Error('Boot the current firmware and reconnect before updating.');
  const seq=current.seq+1;
  const record=new Uint8Array(32).fill(255);
  const next=new DataView(record.buffer);
  next.setUint32(0,seq,true);
  next.setUint32(24,0,true); // ESP_OTA_IMG_NEW. The normal boot and rollback checks run on the kit.
  next.setUint32(28,selectionCrc(seq),true);
  return {record,appAddress:slotAddress[(seq-1)%2],recordAddress:layout.selector.address+(1-current.index)*sector};
}
export function checkTarget(chip,info) {
  if (chip?.CHIP_NAME!=='ESP32-C6' || chip.IMAGE_CHIP_ID!==13 || info?.chipId!==13)
    throw Error('Choose the USB port for an Areion FC A1 (ESP32-C6).');
  const count=info.flashCryptCnt;
  const encrypted=Number.isInteger(count) && (count.toString(2).match(/1/g)||[]).length%2===1;
  if (info.parsedFlags?.SECURE_BOOT_EN!==false || info.parsedFlags?.SECURE_DOWNLOAD_ENABLE!==false ||
      !Number.isInteger(count) || count<0 || count>255 || encrypted)
    throw Error('This release requires a board configured for standard, unencrypted development firmware.');
}

export async function programKit(loader,release,mode,progress=()=>{}) {
  if (!['update','install'].includes(mode)) throw Error('Choose a flash operation.');
  progress(4,'Identifying the USB board…');
  await loader.detectChip('default_reset',3);
  checkTarget(loader.chip,await loader.getSecurityInfo());
  await loader.chip.postConnect?.(loader);
  await loader.runStub();
  if (!loader.IS_STUB || !/^(4|8|16|32|64|128)MB$/.test(await loader.detectFlashSize()))
    throw Error('A compatible flash chip with at least 4 MB is required.');
  const images=release.images;
  const table=await loader.readFlash(layout.partitions.address,images.partitions.bytes);
  const known=fixedPartitions(table) && sameBytes(table,images.partitions.data);
  const blank=table.length===images.partitions.bytes && table.every(v=>v===255);
  if (!known && !(mode==='install' && blank))
    throw Error('The board has a different partition layout. No firmware was written.');
  const tasks=[];
  let selection=null;
  if (mode==='update') {
    selection=nextSelection(await loader.readFlash(layout.selector.address,2*sector));
    tasks.push(['application',selection.appAddress]);
  } else {
    tasks.push(['application',layout.application.address],['bootloader',0],
      ['partitions',layout.partitions.address],['selector',layout.selector.address]);
  }
  const total=tasks.reduce((sum,[name])=>sum+images[name].bytes,0);
  let done=0;
  async function writeAt(address,data,onProgress) {
    await loader.writeFlash({fileArray:[{address,data}],eraseAll:false,compress:true,flashSize:'keep',
      flashMode:'keep',flashFreq:'keep',reportProgress:(_,sent,size)=>onProgress?.(size?sent/size:0)});
  }
  for (const [name,address] of tasks) {
    const {data,bytes,md5}=images[name];
    const stage='Writing '+name+'…';
    const worked=fraction=>7+Math.floor(83*(done+bytes*fraction)/total);
    progress(worked(0),stage);
    await writeAt(address,data,fraction=>progress(worked(fraction),stage));
    progress(worked(1),'Verifying '+name+' on the board…');
    if ((await loader.flashMd5sum(address,bytes)).toLowerCase()!==md5)
      throw Error('Board readback failed for '+name+'. Retry over USB.');
    done+=bytes;
  }
  if (selection) {
    progress(94,'Selecting the verified firmware for the next boot…');
    await writeAt(selection.recordAddress,selection.record);
    if (!sameBytes(await loader.readFlash(selection.recordAddress,32),selection.record))
      throw Error('Boot selection readback failed. Reconnect over USB to check the installed version.');
  }
  progress(98,'Images verified. Restarting the board…');
  try { await loader.after('hard_reset'); return {reset:true}; }
  catch { return {reset:false}; }
}

export async function flashPort(port,release,mode,progress) {
  if (port.readable || port.writable) throw Error('Close the serial monitor or other connection using this port.');
  const {ESPLoader,Transport}=await import('./vendor/esptool-js-0.7.1.min.js');
  const transport=new Transport(port);
  const loader=new ESPLoader({transport,baudrate:115200,romBaudrate:115200,
    terminal:{clean(){},write(){},writeLine(){}}});
  try { return await programKit(loader,release,mode,progress); }
  finally {
    if (port.readable && transport.reader) await transport.disconnect();
    else if (port.readable && !port.readable.locked && !port.writable?.locked) await port.close();
  }
}
