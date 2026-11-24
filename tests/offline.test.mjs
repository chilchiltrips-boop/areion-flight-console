import test from 'node:test';
import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
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
        const bytes = await readFile(join(out, path));
        if (/\.(html|svg)$/.test(path)) assert.match(bytes.toString(), /data-areion-build="areion-asset-[a-f0-9]+"/);
        else assert.equal(request.integrity, 'sha256-' + createHash('sha256').update(bytes).digest('base64'));
        cacheEntries.set(request.url, bytes);
      }
    },
    async match(url) { return cacheEntries.has(url) ? new Response(cacheEntries.get(url)) : undefined; },
    async keys() { return [...cacheEntries.keys()].map(url => new Request(url)); }
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
  const index = (await readFile(join(out,'index.html'))).toString();
  const core = /name="areion-core" content="([0-9a-f]+)"/.exec(index)[1];
  async function check(repair=false, expected=core) {
    let work, status;
    events.get('message')({data:{type:'AREION_OFFLINE_CHECK',core:expected,repair},
      ports:[{postMessage(value){status=value;}}], waitUntil(promise){work=promise;}});
    await work;
    return status;
  }
  const first = await check();
  assert.equal(first.core,core);
  assert.equal(first.cached,first.total);
  assert(first.total > 100);
  for (const file of ['ap-session-port.js','ap-worker.js','wifi.js']) assert.ok(cacheEntries.has(scope+file),file);
  cacheEntries.delete(scope+'assembly/f450_bottom_pdb.glb');
  assert.equal((await check()).cached,first.total-1);
  assert.equal((await check(true,'different-release')).cached,first.total-1);
  assert.equal((await check(true)).cached,first.total);

  function fetchFromWorker(url, mode = 'cors') {
    let response;
    events.get('fetch')({
      request:{method:'GET', url, mode},
      respondWith(promise) { response = promise; }
    });
    return response;
  }
  for (const route of ['#welcome','#flight','#record','#assembly','#configuration/wizard','#configuration/imu','#configuration/esc','#configuration/pid-simulator','#system/connections','#scopes/spectrum','#firmware','?embed=1#flight','index.html?from=bookmark#system/values']) {
    const entry = await fetchFromWorker(scope + route, 'navigate');
    assert.equal(await entry.text(), (await readFile(join(out, 'index.html'))).toString());
  }
  const benchDocument = await fetchFromWorker(scope + 'assembly/viewer.html', 'navigate');
  assert.equal(await benchDocument.text(), await readFile(join(out,'assembly/viewer.html'),'utf8'));
  for (const [url, bytes] of cacheEntries) {
    assert.deepEqual(Buffer.from(await (await fetchFromWorker(url + '?embedded=1')).arrayBuffer()), bytes, url);
  }
  assert.equal(fetchFromWorker('http://192.168.4.1/telemetry'), undefined);
  assert.equal(fetchFromWorker('https://example.github.io/another-project/index.html','navigate'), undefined);
  assert.equal(missed, false);
});

test('an assembly-only release can activate with open tabs, while shared console changes still wait', async () => {
  const template = await readFile(new URL('../scripts/offline-worker.template',import.meta.url),'utf8');
  const files = ['index.html','app.js','assembly/viewer.html'];
  const worker = template.replace('__VERSION__','new').replace('__CORE__','core').replace('__FILES__',JSON.stringify(files)).replace('__INTEGRITY__','[]');
  const prefix = 'areion-console-/areion-flight-console/-';
  async function installsImmediately(oldFiles, failDownload = false) {
    const previous = {
      keys:async () => Object.keys(oldFiles).map(path => new Request(scope + path)),
      match:async url => {
        const body = oldFiles[url.slice(scope.length)];
        return body === undefined ? undefined : new Response(body);
      }
    };
    const next = {
      async addAll() { if (failDownload) throw Error('Download interrupted'); },
      match:async url => new Response(url.endsWith('app.js') ? 'app1' : 'new')
    };
    let install, work, activated = false, discarded = false;
    runInNewContext(worker, {
      URL, Request,
      self:{registration:{scope,active:{}},skipWaiting:async () => { activated=true; },
        addEventListener(name,listener) { if (name === 'install') install=listener; }},
      caches:{keys:async () => [prefix + 'old',prefix + 'new','unrelated-cache'],
        open:async name => name === prefix + 'new' ? next : previous,
        delete:async name => { assert.equal(name,prefix + 'new'); discarded=true; }}
    });
    install({waitUntil(promise) { work=promise; }});
    if (failDownload) await assert.rejects(work,/interrupted/);
    else await work;
    assert.equal(discarded,failDownload);
    return activated;
  }
  const old = {'index.html':'new','app.js':'app1','assembly/viewer.html':'old layout'};
  assert.equal(await installsImmediately(old), true);
  assert.equal(await installsImmediately({...old,'app.js':'app2'}), false);
  assert.equal(await installsImmediately({...old,'retired.js':'old module'}), false);
  assert.equal(await installsImmediately(old,true), false);
});
