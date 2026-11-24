import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {basename,join} from 'node:path';
import {createHash} from 'node:crypto';
import {board,imageMatchesBoard,layout,validateManifest} from '../web/firmware-release.js';

const [build,out,initializer]=process.argv.slice(2);
if (!build || !out || !initializer) throw Error('Expected Arduino build directory, output directory and boot_app0.bin path.');
const args=await readFile(join(build,'flash_args'),'utf8');
const flags=args.split(/\r?\n/)[0];
if (!/--flash-mode dio\b/.test(flags) || !/--flash-freq 80m\b/.test(flags) || !/--flash-size 4MB\b/.test(flags))
  throw Error('Unexpected ESP32-C6 flash settings.');
const files=new Map([...args.matchAll(/^(0x[\da-f]+)\s+(\S+)\s*$/gim)].map(m=>[Number(m[1]),m[2]]));
if (files.size!==4) throw Error('Expected four separate flash images.');
const source=await readFile(new URL('../firmware/AreionBrowserAP/AreionSerialIntegration.h',import.meta.url),'utf8');
const version=source.match(/AreionFirmwareVersion="(\d+\.\d+\.\d+)"/)?.[1];
const manifest={schema:1,board,chip:'ESP32-C6',flashBytes:0x400000,version,images:{}};
const output=[];
for (const [key,{address}] of Object.entries(layout)) {
  const file=files.get(address);
  if (!file || basename(file)!==file || key==='selector' && file!=='boot_app0.bin') throw Error('Unexpected flash address or file for '+key);
  const bytes=await readFile(key==='selector'?initializer:join(build,file));
  if (!imageMatchesBoard(key,bytes)) throw Error('Wrong board image or partition layout: '+key);
  manifest.images[key]={file:key+'.bin',address,bytes:bytes.length,
    sha256:createHash('sha256').update(bytes).digest('hex'),md5:createHash('md5').update(bytes).digest('hex')};
  output.push([key+'.bin',bytes]);
}
validateManifest(manifest);
await mkdir(out,{recursive:true});
for (const [name,bytes] of output) await writeFile(join(out,name),bytes);
await writeFile(join(out,'manifest.json'),JSON.stringify(manifest,null,2)+'\n');
console.log(board+' '+version+' packaged with four verified images.');
