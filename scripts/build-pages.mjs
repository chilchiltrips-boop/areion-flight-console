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
files.sort();
const template = await readFile(new URL('./offline-worker.template',import.meta.url),'utf8');
const releaseHash = createHash('sha256').update(template);
const coreHash = releaseHash.copy();
const contents = new Map();
for (const path of files) {
  const bytes = await readFile(join(source, path));
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
