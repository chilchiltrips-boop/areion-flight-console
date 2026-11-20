import {createHash} from 'node:crypto';
import {cp, mkdir, readFile, readdir, writeFile} from 'node:fs/promises';
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
const hash = createHash('sha256').update(template);
for (const path of files) {
  hash.update(path).update(await readFile(join(source,path)));
  await mkdir(resolve(out,path,'..'),{recursive:true});
  await cp(join(source,path),join(out,path));
}
const version = hash.digest('hex').slice(0,20);
const worker = template.replace('__VERSION__',version).replace('__FILES__',JSON.stringify(files));
await writeFile(join(out,'offline-worker.js'),worker);
console.log('Built '+files.length+' application files · '+version);
