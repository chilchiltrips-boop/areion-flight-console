// Areion FC A1, Arduino ESP32-C6, 4 MB default OTA partition scheme.
export const board = 'Areion FC A1';
export const reportsComponents=version=>/^3\.(?:[4-9]|[1-9]\d+)\.\d+$/.test(String(version));
export const sector = 0x1000;
export const layout = {
  bootloader: {address:0, limit:0x8000},
  partitions: {address:0x8000, limit:sector},
  selector: {address:0xe000, limit:2*sector},
  application: {address:0x10000, limit:0x140000}
};
export const slotAddress = [0x10000,0x150000];
const partitions = [[1,2,0x9000,0x5000],[1,0,0xe000,0x2000],[0,16,0x10000,0x140000],
  [0,17,0x150000,0x140000],[1,130,0x290000,0x160000],[1,3,0x3f0000,0x10000]];
export function fixedPartitions(bytes) {
  if (bytes.length<224) return false;
  const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  return partitions.every(([type,subtype,address,size],i)=>{
    const p=i*32;
    return view.getUint16(p,true)===0x50aa && bytes[p+2]===type && bytes[p+3]===subtype &&
      view.getUint32(p+4,true)===address && view.getUint32(p+8,true)===size && view.getUint32(p+28,true)===0;
  }) && view.getUint16(192,true)===0xebeb;
}
export function validateManifest(m) {
  if (m?.schema!==1 || m.board!==board || m.chip!=='ESP32-C6' || m.flashBytes!==0x400000 ||
      !/^\d+\.\d+\.\d+$/.test(m.version) || Object.keys(m.images||{}).length!==4)
    throw Error('Unsupported Areion firmware package.');
  for (const [key,{address,limit}] of Object.entries(layout)) {
    const image=m.images[key];
    if (!image || image.file!==key+'.bin' || image.address!==address || !Number.isInteger(image.bytes) ||
        image.bytes<32 || image.bytes>limit || key==='selector' && image.bytes!==limit ||
        !/^[a-f0-9]{64}$/.test(image.sha256) || !/^[a-f0-9]{32}$/.test(image.md5))
      throw Error('Invalid firmware image entry: '+key);
  }
  if(m.libraries && !['ZebjusAreionLink','ZebjusPpm'].every(name=>/^\d+\.\d+\.\d+$/.test(m.libraries[name])))throw Error('Invalid Arduino library versions.');
  if(m.sources && (m.sources.file!=='arduino-sources.zip'||!Number.isInteger(m.sources.bytes)||m.sources.bytes<=0||!/^[a-f0-9]{64}$/.test(m.sources.sha256)))throw Error('Invalid source archive.');
  return m;
}
export const digestHex = async bytes => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),
  b=>b.toString(16).padStart(2,'0')).join('');
export function imageMatchesBoard(key,bytes) {
  if (key==='partitions') return fixedPartitions(bytes);
  if (key==='application' || key==='bootloader') return bytes[0]===0xe9 && bytes[12]===13 && bytes[13]===0;
  return true;
}
async function asset(name,fetcher) {
  const base=new URL('firmware-release/',import.meta.url);
  const response=await fetcher(new URL(name,base));
  if (!response.ok) throw Error('Firmware package unavailable. Open the console online to prepare it for offline use.');
  return response;
}
export async function loadManifest(fetcher=fetch) {
  return validateManifest(await (await asset('manifest.json',fetcher)).json());
}
export async function loadRelease(fetcher=fetch) {
  const manifest=await loadManifest(fetcher);
  const images={};
  await Promise.all(Object.entries(manifest.images).map(async ([key,meta])=>{
    const bytes=new Uint8Array(await (await asset(meta.file,fetcher)).arrayBuffer());
    if (bytes.length!==meta.bytes || await digestHex(bytes)!==meta.sha256 || !imageMatchesBoard(key,bytes))
      throw Error('Firmware integrity check failed for '+key+'. Reload before flashing.');
    images[key]={...meta,data:bytes};
  }));
  return {version:manifest.version,images};
}
