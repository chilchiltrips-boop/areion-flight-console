import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {checkTarget,nextSelection,programKit,selectionCrc} from '../web/firmware-flash.js';
import {board,fixedPartitions,layout,loadRelease,sector,slotAddress} from '../web/firmware-release.js';
import {mountWifi,recoveryPassword} from '../web/firmware-wifi.js';
import {encodeCommand} from '../web/protocol.js';

const digest=(algorithm,b)=>createHash(algorithm).update(b).digest('hex');
const flashInfo={chipId:13,flashCryptCnt:0,parsedFlags:{SECURE_BOOT_EN:false,SECURE_DOWNLOAD_ENABLE:false}};
const chip={CHIP_NAME:'ESP32-C6',IMAGE_CHIP_ID:13};
function selector() {
  const bytes=new Uint8Array(2*sector).fill(255),view=new DataView(bytes.buffer);
  view.setUint32(0,1,true);view.setUint32(28,0x4743989a,true);view.setUint32(sector,0,true);
  return bytes;
}
function fixture() {
  const table=new Uint8Array(3072).fill(255),view=new DataView(table.buffer);
  [[1,2,0x9000,0x5000],[1,0,0xe000,0x2000],[0,16,0x10000,0x140000],[0,17,0x150000,0x140000],
    [1,130,0x290000,0x160000],[1,3,0x3f0000,0x10000]].forEach(([type,sub,addr,size],i)=>{
    const p=i*32;view.setUint16(p,0x50aa,true);table.set([type,sub],p+2);
    view.setUint32(p+4,addr,true);view.setUint32(p+8,size,true);view.setUint32(p+28,0,true);
  });
  view.setUint16(192,0xebeb,true);
  const executable=new Uint8Array(253);executable[0]=0xe9;executable[12]=13;
  const payload={partitions:table,application:executable,bootloader:executable,selector:selector()};
  const images={},manifest={schema:1,board,chip:'ESP32-C6',flashBytes:0x400000,version:'3.3.0',images:{}};
  for (const [key,data] of Object.entries(payload)) {
    const meta={file:key+'.bin',address:layout[key].address,bytes:data.length,sha256:digest('sha256',data),md5:digest('md5',data)};
    manifest.images[key]=meta;images[key]={...meta,data};
  }
  const flash=new Uint8Array(0x400000).fill(255),writes=[];
  const loader={chip,getSecurityInfo:async()=>flashInfo,detectChip:async()=>{},runStub:async()=>{loader.IS_STUB=true;},
    detectFlashSize:async()=>'4MB',readFlash:async(a,n)=>flash.slice(a,a+n),
    async writeFlash(options) {
      assert.equal(options.eraseAll,false);
      const {address,data}=options.fileArray[0];writes.push(address);
      flash.fill(255,address,address+Math.ceil(data.length/sector)*sector);flash.set(data,address);
      options.reportProgress(0,data.length,data.length);
    },
    flashMd5sum:async(a,n)=>digest('md5',flash.slice(a,a+n)),after:async()=>{}
  };
  return {flash,loader,writes,release:{version:'3.3.0',images},manifest,payload};
}
test('first install preserves NVS and verified updates switch between the two slots',async()=>{
  const {flash,loader,writes,release}=fixture();
  flash.fill(42,0x9000,0xe000);
  await programKit(loader,release,'install');
  assert.deepEqual(writes,[slotAddress[0],0,0x8000,0xe000]);
  writes.length=0;
  await programKit(loader,release,'update');
  assert.deepEqual(writes,[slotAddress[1],0xf000]);
  assert.equal(new DataView(flash.buffer).getUint32(0xf000+24,true),0);
  await assert.rejects(programKit(loader,release,'update'),/Boot the current/);
  new DataView(flash.buffer).setUint32(0xf000+24,2,true);
  writes.length=0;
  await programKit(loader,release,'update');
  assert.deepEqual(writes,[slotAddress[0],0xe000]);
  assert.ok(flash.subarray(0x9000,0xe000).every(v=>v===42));
});
test('interrupted write and failed app verification leave the old selection in place',async()=>{
  for (const error of ['write','hash']) {
    const {flash,loader,writes,release}=fixture();
    flash.set(release.images.partitions.data,0x8000);flash.set(selector(),0xe000);
    if (error==='write') loader.writeFlash=async()=>{throw Error('USB removed');};
    else loader.flashMd5sum=async()=>'0000';
    await assert.rejects(programKit(loader,release,'update'));
    assert.deepEqual(flash.slice(0xe000,0x10000),selector());
    assert.ok(!writes.includes(0xf000));
  }
});
test('wrong chip, protected board, unknown layout and invalid boot metadata stop before writing',async()=>{
  assert.throws(()=>checkTarget({...chip,IMAGE_CHIP_ID:5},flashInfo));
  for (const info of [{...flashInfo,flashCryptCnt:1},{...flashInfo,parsedFlags:{}},{...flashInfo,parsedFlags:{SECURE_BOOT_EN:true}},
    {...flashInfo,parsedFlags:{SECURE_DOWNLOAD_ENABLE:true}},null]) assert.throws(()=>checkTarget(chip,info));
  assert.doesNotThrow(()=>checkTarget(chip,{...flashInfo,flashCryptCnt:3}));
  const {flash,loader,writes,release}=fixture();flash[0x8000]=0;
  for (const mode of ['install','update']) await assert.rejects(programKit(loader,release,mode),/partition layout/);
  assert.deepEqual(writes,[]);
  assert.throws(()=>nextSelection(new Uint8Array(8192).fill(255)));
  assert.deepEqual([1,2,3].map(selectionCrc),[0x4743989a,0x55f63774,0xed4a5011]);
});
test('bundled release rejects tampering or redirected image paths before opening a USB port',async()=>{
  const {manifest,payload}=fixture();
  const fetcher=async url=>{
    const name=url.pathname.split('/').pop();
    return new Response(name==='manifest.json'?JSON.stringify(manifest):payload[name.split('.')[0]]);
  };
  assert.equal((await loadRelease(fetcher)).version,'3.3.0');
  payload.application[44]=8;
  await assert.rejects(loadRelease(fetcher),/integrity/);
  manifest.images.application.file='../anything.bin';
  await assert.rejects(loadRelease(fetcher),/entry/);
  assert.ok(fixedPartitions(payload.partitions));
});
test('credential commands validate Wi-Fi byte lengths, ASCII passwords and private recovery tokens',()=>{
  assert.match(recoveryPassword(),/^[A-Za-z0-9_-]{20}$/);
  assert.notEqual(recoveryPassword(),recoveryPassword());
  const send=values=>encodeCommand('ACTION',138,7,2,values);
  assert.doesNotThrow(()=>send(['SET_AP','ലാബ് Wi-Fi','A password with spaces']));
  for(const values of [['SET_AP','é'.repeat(17),'a'.repeat(8)],['SET_AP','','a'.repeat(8)],
    ['SET_AP','A','short'],['SET_AP','A','pass\nword'],['RECOVER_AP','a'.repeat(64)],['SHOW_OLD_KEY']])
    assert.throws(()=>send(values));
});
test('Wi-Fi recovery saves through USB, verifies the saved name and clears the secret on disconnect',async()=>{
  const nodes=new Map();
  const root={querySelector(key){if(!nodes.has(key))nodes.set(key,{value:'',textContent:'',hidden:true});return nodes.get(key);}};
  const get=n=>root.querySelector('[data-ap-'+n+']');
  const pane=mountWifi(root);
  const actions=[];
  const link={source:2,current:{},readGroup:async()=>['School','aerion drone',true,true],action:async(...args)=>actions.push(args)};
  const ctx={path:'USB',state:'connected',link,group:id=>id===125?['3.3.0']:[false]};
  pane.update(ctx);await new Promise(resolve=>setImmediate(resolve));
  get('recover').onclick();await get('confirm').onclick();
  assert.equal(actions.length,1);assert.deepEqual(actions[0],[138,['RECOVER_AP',get('secret').value]]);
  assert.equal(get('secret').type,'password');assert.equal(get('saved').textContent,'aerion drone');
  assert.match(get('message').textContent,/Access restored/);
  pane.update({...ctx,state:'offline'});assert.equal(get('secret').value,'');assert.ok(get('result').hidden);
});
