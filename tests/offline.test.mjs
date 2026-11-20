import test from 'node:test';
import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {promisify} from 'node:util';
import {runInNewContext} from 'node:vm';

const build = fileURLToPath(new URL('../scripts/build-pages.mjs', import.meta.url));
const scope = 'https://example.github.io/areion-flight-console/';

test('installed Pages release opens flight, the assembly viewer and scopes with the kit offline from the internet', async t => {
  const out = await mkdtemp(join(tmpdir(), 'areion-pages-'));
  t.after(() => rm(out, {recursive:true, force:true}));
  await promisify(execFile)(process.execPath, [build, out]);
  const worker = await readFile(join(out, 'offline-worker.js'), 'utf8');
  const cacheEntries = new Map();
  const events = new Map();
  let claimed = false;
  let missed = false;
  const cache = {
    async addAll(requests) {
      for (const request of requests) {
        assert.ok(request.url.startsWith(scope));
        const path = decodeURIComponent(request.url.slice(scope.length));
        cacheEntries.set(request.url, await readFile(join(out, path)));
      }
    },
    async match(url) { return cacheEntries.get(url); }
  };
  runInNewContext(worker, {
    URL, Request,
    self:{
      registration:{scope},
      clients:{async claim() { claimed = true; }},
      addEventListener:(name, handler) => events.set(name, handler)
    },
    caches:{open:async () => cache, keys:async () => []},
    fetch:async () => { missed = true; throw Error('Internet offline'); }
  });

  for (const name of ['install', 'activate']) {
    let work;
    events.get(name)({waitUntil(promise) { work = promise; }});
    assert.ok(work);
    await work;
  }
  assert.equal(claimed, true);

  function fetchFromWorker(url, mode = 'cors') {
    let response;
    events.get('fetch')({
      request:{method:'GET', url, mode},
      respondWith(promise) { response = promise; }
    });
    return response;
  }
  for (const route of ['#flight', '#assembly', '#scopes/spectrum', 'index.html?from=bookmark#system/connection']) {
    const entry = await fetchFromWorker(scope + route, 'navigate');
    assert.equal(entry.toString(), (await readFile(join(out, 'index.html'))).toString());
  }
  const benchDocument = await fetchFromWorker(scope + 'assembly/viewer.html', 'navigate');
  assert.deepEqual(benchDocument, await readFile(join(out,'assembly/viewer.html')));
  for (const path of [
    'app.js','scopes.js','scope-data.js','analysis.css','assets/airframes/areion450.obj',
    'assembly/page.js','assembly/viewer.js','assembly/viewer.css','assembly/wiring.js',
    'assembly/three.module.min.js','assembly/js/canvas-renderer.js','assembly/f450_bottom_pdb.glb'
  ]) {
    const asset = await fetchFromWorker(scope + path);
    assert.ok(asset?.length, path + ' must be available in the offline project scope');
  }
  assert.equal(fetchFromWorker('http://192.168.4.1/telemetry'), undefined);
  assert.equal(fetchFromWorker('https://example.github.io/another-project/index.html','navigate'), undefined);
  assert.equal(missed, false);
});
