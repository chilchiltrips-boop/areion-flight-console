import {validateManifest,imageMatchesBoard} from '../web/firmware-release.js';
import {createHash} from 'node:crypto';
import {mkdir, readFile, readdir, writeFile} from 'node:fs/promises';
import {join, relative, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../',import.meta.url));
const source = join(root,'web');
const out = resolve(process.argv[2] || join(root,'dist'));
if ([resolve(root),resolve(source)].includes(out)) throw Error('Choose a separate build directory.');
await mkdir(out,{recursive:true});
const files = [];
async function walk(directory) {
  for (const item of await readdir(directory,{withFileTypes:true})) {
    const child = join(directory,item.name);
    if (item.isDirectory()) await walk(child);
    else if (item.isFile()) files.push(relative(source,child).split('\\').join('/'));
  }
}
await walk(source);
const generated=new Map();
const deps=join(root,'node_modules');
for (const [target,file] of [
  ['vendor/esptool-js-0.7.1.min.js','esptool-js/bundle.js'],
  ['vendor/esptool-license.txt','esptool-js/LICENSE'],
  ['vendor/pako-license.txt','pako/LICENSE'],
  ['vendor/atob-lite-license.txt','atob-lite/LICENSE.md']
]) generated.set(target,await readFile(join(deps,file)));
const firmware=join(root,'build','firmware-release');
try {
  const m=validateManifest(JSON.parse(await readFile(join(firmware,'manifest.json'),'utf8')));
  for (const [key,meta] of Object.entries(m.images)) {
    const bytes=await readFile(join(firmware,meta.file));
    if (bytes.length!==meta.bytes || createHash('sha256').update(bytes).digest('hex')!==meta.sha256 ||
        !imageMatchesBoard(key,bytes)) throw Error('Incorrect release image: '+key);
    generated.set('firmware-release/'+meta.file,bytes);
  }
  generated.set('firmware-release/manifest.json',Buffer.from(JSON.stringify(m)));
} catch (error) {
  if (error.code!=='ENOENT' || process.argv.includes('--require-firmware') || generated.has('firmware-release/bootloader.bin')) throw error;
  console.warn('Local UI build without firmware images. Use package-firmware.mjs for USB flashing.');
}
files.push(...generated.keys());
files.sort();
const template = await readFile(new URL('./offline-worker.template',import.meta.url),'utf8');
const releaseHash = createHash('sha256').update(template);
const coreHash = releaseHash.copy();
const contents = new Map();
for (const path of files) {
  const bytes = generated.get(path) ?? await readFile(join(source, path));
  contents.set(path, bytes);
  releaseHash.update(path).update(bytes);
  if (!path.startsWith('assembly/')) coreHash.update(path).update(bytes);
}
const version = releaseHash.digest('hex').slice(0, 20);
const core = coreHash.digest('hex').slice(0, 20);
const integrity = [];
for (const [path, sourceBytes] of contents) {
  let bytes = path === 'index.html' ? Buffer.from(sourceBytes.toString().replace('__AREION_CORE__', core)) : sourceBytes;
  const digest = createHash('sha256').update(bytes);
  if (/\.(html|svg)$/.test(path)) {
    // Embedding proxies may add markup. Identify the shipped document itself.
    const marker = 'areion-asset-' + digest.digest('hex').slice(0, 24);
    const tag = path.endsWith('.html') ? '<html' : '<svg';
    const markup = bytes.toString();
    if (!markup.includes(tag)) throw Error('Missing document element in ' + path);
    bytes = Buffer.from(markup.replace(tag, tag + ' data-areion-build="' + marker + '"'));
    integrity.push(marker);
  } else {
    integrity.push('sha256-' + digest.digest('base64'));
  }
  await mkdir(resolve(out, path, '..'), {recursive:true});
  await writeFile(join(out, path), bytes);
}
const worker = template.replace('__VERSION__', version).replace('__CORE__', core)
  .replace('__FILES__', JSON.stringify(files)).replace('__INTEGRITY__', JSON.stringify(integrity));
await writeFile(join(out, 'offline-worker.js'), worker);
console.log('Built ' + files.length + ' application files · ' + version);
