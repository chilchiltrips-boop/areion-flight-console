import {execFileSync} from 'node:child_process';
import {cp, mkdir, mkdtemp, readFile, rename, rm, writeFile} from 'node:fs/promises';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const repo = fileURLToPath(new URL('../../', import.meta.url));
if (!process.argv[2]) throw Error('Choose an output directory for the Android console assets.');
const out = resolve(process.argv[2]);
if (!out.endsWith('/console') || out === join(repo, 'android/console')) throw Error('Expected a generated console asset directory.');
await mkdir(dirname(out), {recursive:true});
const stage = await mkdtemp(join(dirname(out), '.console-'));
try {
  execFileSync('python3', ['android/scripts/prepare-firmware.py'], {cwd:repo, stdio:'inherit'});
  execFileSync(process.execPath, ['scripts/build-pages.mjs', stage, '--require-firmware'], {cwd:repo, stdio:'inherit'});
  await cp(join(repo, 'android/console'), join(stage, 'android-console'), {recursive:true});
  const entry = join(stage, 'index.html');
  const html = await readFile(entry, 'utf8');
  const script = '<script type="module" src="./app.js"></script>';
  if (!html.includes(script)) throw Error('Web console entry module changed.');
  await writeFile(entry, html.replace('</head>', '<link rel="stylesheet" href="./android-console/mobile.css">\n</head>')
    .replace(script, '<script src="./android-console/native-host.js"></script>\n<script type="module" src="./android-console/app-entry.js"></script>'));
  // The installed APK provides its own atomic, offline asset version.
  await rm(join(stage, 'offline-worker.js'), {force:true});
  await rm(out, {recursive:true, force:true});
  await rename(stage, out);
} finally {
  await rm(stage, {recursive:true, force:true});
}
