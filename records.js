import { schemaFor, validGroup } from './protocol.js';

export const MAX_CSV_BYTES = 8 * 1024 * 1024;
export const MAX_RECORDS = 50_000;
const MAX_LINE_LENGTH = 16_384;
const HEADER = 'seconds_since_connect,group,schema,values_json';
const utf8 = new TextEncoder();

function rowError(line, message) {
  return new Error(`CSV line ${line}: ${message}`);
}

// The desktop uses csv.writer with a JSON array as its fourth column. Embedded
// newlines in string values are JSON escapes, so each packet occupies one line.
function valuesField(text, line) {
  if (text.length > MAX_LINE_LENGTH) throw rowError(line, 'packet is too large.');
  let json = text;
  if (text.startsWith('"')) {
    if (!/^"(?:[^"]|"")*"$/.test(text)) throw rowError(line, 'invalid CSV quoting.');
    json = text.slice(1, -1).replaceAll('""', '"');
  } else if (text.includes(',') || text.includes('"')) {
    throw rowError(line, 'quote the values_json field.');
  }
  try {
    return JSON.parse(json);
  } catch {
    throw rowError(line, 'invalid JSON in values_json.');
  }
}

export function parseCsv(text) {
  if (typeof text !== 'string') throw new Error('Choose an Areion telemetry CSV.');
  if (text.length > MAX_CSV_BYTES || utf8.encode(text).length > MAX_CSV_BYTES) {
    throw new Error('Recording exceeds the 8 MiB import limit.');
  }
  const records = [];
  let lineNumber = 0;
  let offset = text.startsWith('\uFEFF') ? 1 : 0;
  let firstAt;
  let previousAt;
  while (offset < text.length) {
    const newline = text.indexOf('\n', offset);
    const end = newline === -1 ? text.length : newline;
    const line = text.slice(offset, end).replace(/\r$/, '');
    offset = end + 1;
    lineNumber++;
    if (lineNumber === 1) {
      if (line !== HEADER) throw new Error('Choose a CSV exported by Areion Flight Console.');
      continue;
    }
    if (records.length >= MAX_RECORDS) throw new Error('Recording exceeds 50,000 packets.');
    if (line.length > MAX_LINE_LENGTH) throw rowError(lineNumber, 'packet is too large.');
    const match = /^(\d+(?:\.\d+)?),(\d+),(\d+),(.+)$/.exec(line);
    if (!match) throw rowError(lineNumber, 'expected a time, group, schema and values_json.');
    const at = Number(match[1]) * 1000;
    if (!Number.isFinite(at) || at > Number.MAX_SAFE_INTEGER || at < previousAt) {
      throw rowError(lineNumber, 'invalid or out-of-order timestamp.');
    }
    const group = Number(match[2]);
    const schema = Number(match[3]);
    const values = valuesField(match[4], lineNumber);
    if (!validGroup(group, schema, values)) throw rowError(lineNumber, `invalid data or schema for group ${group}.`);
    firstAt ??= at;
    records.push({ group, values, at: at - firstAt });
    previousAt = at;
  }
  if (!records.length) throw new Error('The file contains no telemetry packets.');
  return records;
}

export function serialize(records) {
  if (!Array.isArray(records) || !records.length) throw new Error('No telemetry packets to export.');
  if (records.length > MAX_RECORDS) throw new Error('Recording exceeds 50,000 packets.');
  const lines = [HEADER];
  const firstAt = records[0]?.at;
  let previousAt;
  let bytes = HEADER.length + 2;
  for (const [index, record] of records.entries()) {
    const { group, values, at } = record ?? {};
    const schema = schemaFor(group);
    if (!Number.isFinite(at) || at < 0 || at > Number.MAX_SAFE_INTEGER || at < previousAt ||
        !validGroup(group, schema, values)) {
      throw new Error(`Invalid telemetry packet at row ${index + 1}.`);
    }
    const seconds = ((at - firstAt) / 1000).toFixed(6);
    const json = JSON.stringify(values).replaceAll('"', '""');
    const line = `${seconds},${group},${schema},"${json}"`;
    bytes += utf8.encode(line).length + 2;
    if (bytes > MAX_CSV_BYTES) throw new Error('Recording exceeds the 8 MiB export limit.');
    lines.push(line);
    previousAt = at;
  }
  return lines.join('\r\n') + '\r\n';
}
