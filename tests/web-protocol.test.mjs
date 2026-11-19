import test from "node:test";
import assert from "node:assert/strict";
import { crc32 } from "node:zlib";
import { UsbTelemetry } from "../web/usb.js";
import { FrameDecoder, encodeRequest, newer, schemaFor, validGroup } from "../web/protocol.js";

const utf8 = new TextEncoder();
const decode = new TextDecoder();
const FC = 993;
const fields = {v: 2, type: "DATA", group: 110, schema: 1, session: FC, seq: 2, data: [0]};
function frameFromJson(json) {
  const body = utf8.encode(json);
  return utf8.encode("$" + body.length + ":" + json + "*" + crc32(body).toString(16).toUpperCase().padStart(8, "0") + "\n");
}
const frame = (overrides = {}) => frameFromJson(JSON.stringify({...fields, ...overrides}));

test("outgoing bytes match the desktop Python SDK; writes are limited to telemetry operations", () => {
  const expected = '$74:{"v":2,"type":"HELLO","group":0,"schema":1,"session":16,"seq":1,"data":[]}*C4461740\n';
  assert.equal(decode.decode(encodeRequest("HELLO", 0, 1, 16, 1)), expected);
  for (const type of ["ACTION", "CONTROL", "SET", "SAVE", "DATA"])
    assert.throws(() => encodeRequest(type, 0, 1, 16, 1));
  assert.throws(() => encodeRequest("READ", 9, 1, 16, 1));
  assert.throws(() => encodeRequest("READ", 500, undefined, 16, 1));
});

test("fragmented Python UTF-8 and FC frames stream through noise and truncation", () => {
  const python = '$152:{"v":2,"type":"DATA","group":130,"schema":1,"session":993,"seq":1,"data":[false,true,6,4,15,true,true,false,false,1000,1000,1000,1000,4,"","Areion$é"]}*DD743A3A\n';
  const firmware = '$162:{"v":2,"type":"DATA","group":130,"schema":1,"session":270544961,"seq":17,"data":[false,true,0,5,15,true,true,false,false,1000,1000,1000,1000,1,"","A1-HOST-TEST"]}*AA5B5C91\n';
  const packet = utf8.encode("reset\n$123:garbled\n$123:partial" + python + firmware);
  const parser = new FrameDecoder(), received = [];
  for (let offset = 0; offset < packet.length; offset += 5)
    received.push(...parser.push(packet.subarray(offset, offset + 5)));
  assert.deepEqual(received.map(m => m.data[15]), ["Areion$é", "A1-HOST-TEST"]);
  assert(received.every(m => validGroup(m.group, m.schema, m.data)));
  assert.deepEqual(parser.push(utf8.encode("$" + "x".repeat(5100) + firmware)).map(m => m.seq), [17]);
});

test("invalid checksum, duplicate key, metadata, group shape and sequence order", () => {
  const parser = new FrameDecoder();
  const wrongCrc = frame();
  wrongCrc[wrongCrc.length - 2] ^= 5;
  assert.deepEqual(parser.push(wrongCrc), []);
  for (const replacement of ['"v":2,"v":2', '"v":2.0', '"v":2,"other":7'])
    assert.deepEqual(parser.push(frameFromJson(JSON.stringify(fields).replace('"v":2', replacement))), []);
  assert(!validGroup(120, 1, Array(10).fill(0)));
  assert(!validGroup(22, 2, Array(8).fill(1500)));
  assert(!validGroup(123, 1, ["ARM"]));
  assert.equal(schemaFor(7), 3);
  assert(newer(1, 0xffffffff));
  assert(!newer(0xffffffff, 1));
});

test("manual USB handshake gates DATA, rejects stale/wrong sessions and closes without flight commands", async () => {
  const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  const originalSecure = Object.getOwnPropertyDescriptor(globalThis, "isSecureContext");
  let controller, opens = 0, closes = 0;
  const writes = [], statuses = [], received = [];
  const port = {
    async open(options) { assert.equal(options.baudRate, 115200); opens++; },
    async close() { closes++; },
    readable: new ReadableStream({start(s) { controller = s; }}),
    writable: new WritableStream({write(chunk) {
      const text = decode.decode(chunk);
      writes.push(JSON.parse(text.slice(text.indexOf(":") + 1, -10)));
    }})
  };
  Object.defineProperty(globalThis, "navigator", {configurable: true, value: {serial: {async requestPort() { return port; }}}});
  Object.defineProperty(globalThis, "isSecureContext", {configurable: true, value: true});
  const link = new UsbTelemetry({onStatus: s => statuses.push(s.state), onData: m => received.push(m)});
  const flush = () => new Promise(r => setTimeout(r, 0));
  try {
    assert.equal(writes.length, 0);
    await link.connect();
    await flush();
    const hello = writes[0];
    assert.equal(hello.type, "HELLO");
    assert.equal(opens, 1);
    controller.enqueue(frame());
    controller.enqueue(frame({type: "ACK", session: hello.session, seq: hello.seq + 1, group: 0, data: ["HELLO", FC]}));
    await flush();
    assert.equal(link.state, "handshake");
    assert.equal(received.length, 0);
    controller.enqueue(frame({type: "ACK", session: hello.session, seq: hello.seq, group: 0, data: ["HELLO", FC]}));
    for (const sample of [frame({session: FC + 1}), frame(), frame(), frame({seq: 1}), frame({seq: 3, data: [2]})])
      controller.enqueue(sample);
    await flush();
    assert.equal(link.state, "connected");
    assert.deepEqual(received.map(m => m.values), [[0], [2]]);
    const run = link.current;
    run.lastRx = performance.now() - 1300;
    link.tick(run);
    assert.equal(link.state, "stale");
    controller.enqueue(frame({seq: 4}));
    await flush();
    link.tick(run);
    assert.equal(link.state, "connected");
    await flush();
    await link.disconnect();
    assert.equal(closes, 1);
    assert.equal(link.state, "offline");
    assert(writes.every(m => ["HELLO", "READ", "PING", "RELEASE"].includes(m.type)));
    assert.equal(writes.at(-1).type, "RELEASE");
  } finally {
    await link.disconnect();
    if (originalNavigator) Object.defineProperty(globalThis, "navigator", originalNavigator);
    else delete globalThis.navigator;
    if (originalSecure) Object.defineProperty(globalThis, "isSecureContext", originalSecure);
    else delete globalThis.isSecureContext;
  }
});
