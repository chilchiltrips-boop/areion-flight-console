import assert from 'node:assert/strict';
import test from 'node:test';
import {mobileFiles} from '../android/console/mobile-files.js';

test('Android exports preserve bytes and keep each bridge call below binder limits', async () => {
  const bytes = Uint8Array.from({length: 120003}, (_, i) => i % 251);
  const chunks = [];
  const bridge = {
    beginExport(name,size) { assert.equal(name,'session.csv'); assert.equal(size,bytes.length); return 7; },
    appendExport(token,chunk) {
      assert.equal(token,7);
      assert.ok(chunk.length <= 65536);
      chunks.push(Buffer.from(chunk, 'base64'));
      return true;
    },
    finishExport(token) { return token === 7; },
    cancelExport() { assert.fail('Unexpected cancellation'); }
  };
  await mobileFiles(bridge).saveFile(new Blob([bytes]),'session.csv');
  assert.deepEqual(Buffer.concat(chunks), Buffer.from(bytes));
});

test('an interrupted Android write discards the draft before a retry', async () => {
  let cancelled = false, offered = false;
  const bridge = {
    beginExport: () => 8,
    appendExport: () => false,
    finishExport: () => { offered = true; return true; },
    cancelExport: token => { assert.equal(token,8); cancelled = true; }
  };
  await assert.rejects(mobileFiles(bridge).saveFile(new Blob(['sample']),'session.csv'),/interrupted/);
  assert.equal(cancelled,true);
  assert.equal(offered,false);
});

test('Android clipboard limits keep oversized diagnostics available for manual copying', () => {
  let copied = '';
  const files = mobileFiles({copyText(text){ copied = text; return true; }});
  files.copyText('kit response');
  assert.equal(copied,'kit response');
  assert.throws(() => files.copyText('x'.repeat(128 * 1024 + 1)),/diagnostics CSV/);
  assert.equal(copied,'kit response');
});
