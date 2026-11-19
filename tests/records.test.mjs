import assert from 'node:assert/strict';
import test from 'node:test';
import { parseCsv, serialize, MAX_CSV_BYTES, MAX_RECORDS } from '../web/records.js';

const header = 'seconds_since_connect,group,schema,values_json';
const channels = [1483, 1503, 1010, 1500, 1000, 1000, 1500, 1500];

test('reads desktop csv.writer records with time normalized to first frame', () => {
  const csv = '\uFEFF' + header + '\r\n20.010005,110,1,[0]\r\n20.011005,22,1,"[1483, 1503, 1010, 1500, 1000, 1000, 1500, 1500]"\r\n';
  const [first, second] = parseCsv(csv);
  assert.deepEqual(first, { at: 0, group: 110, values: [0] });
  assert.deepEqual(second.values, channels);
  assert.ok(Math.abs(second.at - 1) < 1e-7);
});

test('exports and reads strings with commas, escapes, quotes and Unicode', () => {
  const ipString = 'kit,"desk"\nമലയാളം';
  const rows = [
    { group: 121, at: 234.5, values: [true, ipString, 8080, 5000] },
    { group: 22, at: 400.75, values: channels },
  ];
  const csv = serialize(rows);
  assert.ok(csv.startsWith(header + '\r\n'));
  assert.deepEqual(parseCsv(csv), [{ ...rows[0], at: 0 }, { ...rows[1], at: 166.25 }]);
});

test('rejects malformed rows, mismatched schemas, ranges, timestamps and invalid exports', () => {
  for (const body of ['0,110,2,[0]', '0,110,1,[true]', '0,110,1,[9]', '0,110,1,"[0]', '0,110,1,"[0,1]"', 'NaN,110,1,[0]', '1,110,1,[0]\n0,110,1,[0]']) {
    assert.throws(() => parseCsv(header + '\n' + body), /line [2-3]/);
  }
  assert.throws(() => parseCsv(header + '\n'), /no telemetry/);
  assert.throws(() => parseCsv('time,group,schema,data\n'), /Areion/);
  assert.throws(() => parseCsv('a'.repeat(MAX_CSV_BYTES + 1)), /limit/);
  assert.throws(() => serialize([]), /No telemetry/);
  assert.throws(() => serialize([{ at: NaN, group: 110, values: [0] }]), /Invalid/);
  assert.throws(() => serialize(Array(MAX_RECORDS + 1)), /50,000/);
});
