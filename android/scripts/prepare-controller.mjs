import {copyFile, mkdir, mkdtemp, readFile, rename, rm, writeFile} from 'node:fs/promises';
import {basename, dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const repo = fileURLToPath(new URL('../../', import.meta.url));
const source = join(repo, 'android/controller');
if (!process.argv[2]) throw Error('Specify the output controller directory.');
const output = resolve(process.argv[2]);
if (basename(output) !== 'controller' || output === source) throw Error('Expected a generated controller directory.');
const local = ['index.html', 'app.js', 'controller.js', 'controller.css', 'native-host.js', 'touch-input.js'];
const shared = JSON.parse(await readFile(join(repo, 'android/shared-modules.json'), 'utf8'));

await mkdir(dirname(output), {recursive: true});
const stage = await mkdtemp(join(dirname(output), '.controller-'));
try {
  await mkdir(join(stage, 'shared'));
  for (const name of shared) {
    if (!/^[a-z][a-z0-9-]*\.js$/.test(name)) throw Error('Invalid shared module name: ' + name);
    await copyFile(join(repo, 'web', name), join(stage, 'shared', name));
  }
  for (const name of local) {
    const target = join(stage, name);
    if (name === 'controller.js') {
      const code = await readFile(join(source, name), 'utf8');
      const localImports = code.replace(/(['"])\.\.\/\.\.\/web\/([\w-]+\.js)\1/g, (_, quote, module) => {
        if (!shared.includes(module)) throw Error('Unbundled controller dependency: ' + module);
        return quote + './shared/' + module + quote;
      });
      await writeFile(target, localImports);
    } else {
      await copyFile(join(source, name), target);
    }
  }
  await rm(output, {recursive: true, force: true});
  await rename(stage, output);
} finally {
  await rm(stage, {recursive: true, force: true});
}
