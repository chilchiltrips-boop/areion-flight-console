// Areion Link protocol 2. Lengths and the CRC cover UTF-8 bytes.
const encoder = new TextEncoder();
const utf8 = new TextDecoder("utf-8", {fatal: true});
const MAX_PAYLOAD = 1536;
const MAX_FRAME = MAX_PAYLOAD + 16;
const UINT32 = 0xffffffff;
const allowedKeys = new Set(["v", "type", "group", "schema", "session", "seq", "data"]);
const incomingTypes = new Set(["ACK", "ERROR", "DATA"]);
const outgoingTypes = new Set(["HELLO", "PING", "READ", "RELEASE"]);
export const newer = (value, prior) => ((value - prior) >>> 0) > 0 && ((value - prior) >>> 0) < 0x80000000;
const inRange = (v, min, max) => Number.isInteger(v) && v >= min && v <= max;

function boundedString(value) {
  return typeof value === "string" && encoder.encode(value).length <= 128
    && !/[\uD800-\uDFFF]/u.test(value);
}

const checksumTable = Uint32Array.from({length: 256}, (_, value) => {
  for (let i = 0; i < 8; i++) value = (value >>> 1) ^ ((value & 1) ? 0xedb88320 : 0);
  return value >>> 0;
});

function checksum(bytes) {
  let crc = UINT32;
  for (const byte of bytes) crc = checksumTable[(crc ^ byte) & 255] ^ (crc >>> 8);
  return ((crc ^ UINT32) >>> 0).toString(16).toUpperCase().padStart(8, "0");
}

function frame(json) {
  const bytes = encoder.encode(json);
  if (bytes.length > MAX_PAYLOAD) throw Error("Link v2 payload exceeds its size limit");
  return encoder.encode("$" + bytes.length + ":" + json + "*" + checksum(bytes) + "\n");
}

export function encodeRequest(type, group, schema, session, seq) {
  if (!outgoingTypes.has(type) || !inRange(session, 1, UINT32) || !inRange(seq, 1, UINT32)
      || !inRange(group, 0, 65535) || !inRange(schema, 1, 65535)
      || (type === "READ" ? schemaFor(group) !== schema : group !== 0 || schema !== 1)) {
    throw new Error("Invalid telemetry request");
  }
  return frame(JSON.stringify({v: 2, type, group, schema, session, seq, data: []}));
}

function decode(bytes) {
  const colon = bytes.indexOf(58);
  if (colon < 2 || colon > 5 || bytes[0] !== 36) return null;
  const digits = utf8.decode(bytes.subarray(1, colon));
  if (!/^[1-9][0-9]{0,3}$/.test(digits)) return null;
  const size = Number(digits);
  const end = colon + 1 + size;
  if (size > MAX_PAYLOAD || end + 10 !== bytes.length || bytes[end] !== 42 || bytes.at(-1) !== 10) return null;
  const payload = bytes.subarray(colon + 1, end);
  if (utf8.decode(bytes.subarray(end + 1, end + 9)) !== checksum(payload)) return null;
  const json = utf8.decode(payload);
  const msg = JSON.parse(json);
  if (!msg || typeof msg !== "object" || Array.isArray(msg) || Object.keys(msg).length !== allowedKeys.size) return null;
  const seen = new Set();
  // JSON.parse silently accepts duplicate fields. Require literal integer metadata, too.
  for (const token of json.matchAll(/"(?:\\[\s\S]|[^"\\])*"/g)) {
    const following = json.slice(token.index + token[0].length);
    if (!/^\s*:/.test(following)) continue;
    const key = JSON.parse(token[0]);
    if (!allowedKeys.has(key) || seen.has(key)) return null;
    if (key !== "type" && key !== "data" && !/^\s*:\s*(?:0|[1-9]\d*)\s*[,}]/.test(following)) return null;
    seen.add(key);
  }
  if (seen.size !== allowedKeys.size || msg.v !== 2 || !incomingTypes.has(msg.type)
      || !inRange(msg.group, 0, 65535) || !inRange(msg.schema, 1, 65535)
      || !inRange(msg.session, 1, UINT32) || !inRange(msg.seq, 1, UINT32)
      || !Array.isArray(msg.data) || msg.data.length > 32
      || !msg.data.every(v => typeof v === "boolean" || Number.isFinite(v) || boundedString(v))) return null;
  Object.defineProperty(msg,'byteLength',{value:bytes.length});
  return msg;
}

export class FrameDecoder {
  constructor() {
    this.buffer = new Uint8Array(MAX_FRAME);
    this.size = 0;
  }
  push(chunk) {
    const messages = [];
    for (const byte of chunk) {
      if (!this.size && byte !== 36) continue;
      if (this.size === MAX_FRAME) {
        const next = this.buffer.indexOf(36, 1);
        if (next < 0) this.size = 0;
        else {
          this.buffer.copyWithin(0, next);
          this.size -= next;
        }
        if (!this.size && byte !== 36) continue;
      }
      this.buffer[this.size++] = byte;
      if (byte !== 10) continue;
      const line = this.buffer.subarray(0, this.size);
      for (let start = 0; start >= 0; start = line.indexOf(36, start + 1)) {
        try {
          const msg = decode(line.subarray(start));
          if (msg) { messages.push(msg); break; }
        } catch { /* Ignore boot chatter or a corrupt frame. */ }
      }
      this.size = 0;
    }
    return messages;
  }
}

// Readable group schemas from the desktop SDK. Fields keep their firmware order.
const integer = (min = -2147483648, max = UINT32) => v => inRange(v, min, max);
const number = (min = -Infinity, max = Infinity) => v => Number.isFinite(v) && v >= min && v <= max;
const bool = v => typeof v === "boolean";
const entries = new Map([
  [2, [1, [number(0, 100), number(0, 100), number(0, 100), number(0, 500), number(0, 500), number(0, 500), number(0, 20), number(0, 20), number(0, 20)]]], // RATE_PID
  [3, [1, [number(0, 100), number(0, 100), number(0, 500), number(0, 500), number(0, 20), number(0, 20)]]], // ANGLE_PID
  [4, [2, [integer(1001, 1200), integer(1700, 2000), integer(1000, 1300), integer(1, 200), integer(1, 15), integer(1, 10), integer(1, 300)]]], // ARMING_SETTINGS
  [6, [2, [number(-0.5, 0.5), number(-0.5, 0.5), number(-0.5, 0.5)]]], // IMU_SETTINGS
  [7, [3, [integer(1, 8), number(0.01, 0.3), number(0.01, 1), number(0.01, 1), integer(0, 1), integer(0, 1)]]], // FLIGHT_SETTINGS
  [21, [1, Array(10).fill(number())]], // IMU
  [22, [1, Array(8).fill(integer())]], // RECEIVER
  [23, [2, Array(12).fill(number())]], // CONTROL_OUTPUT
  [110, [1, [integer(0, 2)]]], // INPUT_SOURCE
  [112, [1, [integer(50, 1000), integer(100, 500)]]], // RECEIVER_TIMEOUTS
  [120, [1, [bool, bool, bool, integer(), number(), integer(), integer(), bool, bool, bool]]], // STATUS
  [121, [1, [bool, boundedString, integer(), integer()]]], // LINK_STATUS
  [122, [2, [integer(), integer(), bool, bool, bool, integer(), integer(), integer(), bool]]], // INPUT_STATUS
  [125, [1, [boundedString, integer(), integer(), integer(), integer(), integer(), integer(), integer(), integer(), integer(), integer(), integer()]]], // DEVICE_INFO
  [130, [1, [bool, bool, integer(0, 7), integer(0, 6), integer(0, 15), bool, bool, bool, bool, integer(1000, 1500), integer(1000, 1500), integer(1000, 1500), integer(1000, 1500), integer(0, 4294967295), boundedString, boundedString]]], // SETUP_STATUS
  [131, [1, [integer(0, 2100), integer(0, 2100), integer(0, 2100), integer(0, 2100), integer(0, 2100), integer(0, 2100), integer(0, 2100), integer(0, 2100), integer(0, 8), bool, integer(0, 4294967295)]]], // RAW_PPM
  [132, [1, Array.from({length: 8}, () => [integer(900, 1500), integer(900, 2100), integer(1500, 2100), integer(0, 1)]).flat()]], // RX_CALIBRATION
  [134, [1, [integer(0, 3), integer(0, 2), integer(1, 8), integer(1, 8), integer(1, 8), integer(1, 8), integer(0, 50), integer(1000, 1500), integer(1000, 1500), integer(1000, 1500), integer(1000, 1500)]]], // SETUP_CONFIG
  [142, [1, [integer(0,4), integer(0,750), integer(750,750), integer(0,4294967295), boundedString, number(), number(), number()]]],
  [141, [1, [boundedString, boundedString, boundedString, bool]]], // Board, Link library, PPM library, AP update capability
  [139, [1, [boundedString, boundedString, bool, bool]]], // USB AP status (on demand)
  [136, [1, [bool, integer(0, 4294967295), integer(0, 4294967295), boundedString]]], // PID_STATUS
]);

export function schemaFor(group) {
  return entries.get(group)?.[0];
}

export function validGroup(group, schema, values) {
  const entry = entries.get(group);
  return Boolean(entry && entry[0] === schema && Array.isArray(values)
    && entry[1].length === values.length && entry[1].every((test, index) => test(values[index])));
}

// The controller preserves JSON number types. An integral PID gain must be
// serialized as 3.0 rather than 3, just as the Python SDK serializes a float.
const persistent = new Set([2, 3, 4, 6, 7, 112, 132, 134]);
const setupAcks = new Map([
  ['BEGIN','SETUP_LOCKED'], ['STOP','STOPPED'], ['MOTOR_STOP','STOPPED'],
  ['GYRO_ZERO','GYRO_STARTED'], ['GYRO_CANCEL','GYRO_STOPPED'],
  ['SENSOR_OK','SETUP_UPDATED'], ['RX_OK','SETUP_UPDATED'], ['FAILSAFE_OK','SETUP_UPDATED'],
  ['ESC_SCHEDULE','SETUP_UPDATED'], ['ESC_SKIP','SETUP_UPDATED'], ['ESC_VERIFY','SETUP_UPDATED'],
  ['MOTOR_START','MOTOR_TEST_STARTED'], ['MOTOR_SET','MOTOR_TEST_UPDATED'], ['MOTOR_OK','MOTORS_VERIFIED'],
  ['FINALIZE','SETUP_SAVED_ARM_AVAILABLE'], ['RESET_ALL','RESET_DEFAULTS_SAVED'], ['INPUT_SAVE','INPUT_SAVED']
]);
function actionValid(group, values) {
  if (group === 140) {
    const [command,offset,...chunks]=values;
    if(command==='BEGIN')return values.length===3&&inRange(offset,32,0x140000)&&typeof values[2]==='string'&&/^[a-f0-9]{64}$/.test(values[2]);
    if(command==='DATA')return inRange(offset,0,0x140000-1)&&chunks.length>0&&chunks.length<=8&&
      chunks.every(s=>typeof s==='string'&&/^(?:[0-9a-f]{2}){1,64}$/.test(s));
    return values.length===1&&['FINISH','ABORT'].includes(command);
  }
  if (group === 138) {
    const password = values.at(-1);
    if (typeof password !== 'string' || !/^[\x20-\x7e]{8,63}$/.test(password)) return false;
    if (values[0] === 'RECOVER_AP') return values.length === 2;
    const name=values[1];
    return values[0]==='SET_AP' && values.length===3 && boundedString(name) && name.length>0 &&
      encoder.encode(name).length<=32 && !/[\x00-\x1f\x7f]/.test(name);
  }
  if (group === 123) return values.length === 1 && ['ARM','DISARM'].includes(values[0]);
  if (group === 135) return values.length === 5 && setupAcks.has(values[0])
    && values.slice(1).every(v => inRange(v,0,1500));
  if (group !== 137 || values.length !== 11 || ![2,3].includes(values[0]) || typeof values[1] !== "boolean") return false;
  const count = values[0] === 2 ? 9 : 6;
  return validGroup(values[0], 1, values.slice(2, 2 + count)) && values.slice(2 + count).every(v => v === 0);
}
function isFloat(group, index) {
  return [2,3,6].includes(group) || (group === 137 && index >= 2) || (group === 7 && index >= 1 && index <= 3);
}
export function encodeCommand(type, group, session, seq, values = []) {
  if (!inRange(session,1,UINT32) || !inRange(seq,1,UINT32) || !Array.isArray(values)) throw Error("Invalid Link v2 request");
  const schema = schemaFor(group) ?? 1;
  let valid = false;
  if (type === 'READ') valid = schemaFor(group) != null && (!values.length || (persistent.has(group) && values.length === 1 && values[0] === 'saved'));
  if (type === 'SET') valid = (persistent.has(group) || group === 110) && validGroup(group, schema, values);
  if (type === 'SAVE') valid = persistent.has(group) && !values.length;
  if (type === 'ACTION') valid = actionValid(group, values);
  if (type === 'CONTROL') valid = group === 9 && values.length === 8 && values.every(v => inRange(v,1000,2000));
  if (!valid) throw Error("Invalid " + type + " request for group " + group);
  const fields = values.map((v,i) => {
    const literal = JSON.stringify(v);
    return typeof v === 'number' && isFloat(group,i) && Number.isInteger(v) ? literal + '.0' : literal;
  });
  return frame('{"v":2,"type":'+JSON.stringify(type)+',"group":'+group+',"schema":'+schema+
    ',"session":'+session+',"seq":'+seq+',"data":['+fields.join(',')+']}');
}
export function matchesAck(request, reply) {
  if (reply.type !== 'ACK' || reply.data.length !== 1) return false;
  const ack = reply.data[0];
  if (request.type === 'SET') return ack === 'APPLIED_UNSAVED';
  if (request.type === 'SAVE') return ack === 'SAVED';
  if (request.type !== 'ACTION') return false;
  if(request.group===140){
    const [command,offset,...chunks]=request.values;
    if(command==='DATA')return ack==='OTA_OFFSET_'+(offset+chunks.reduce((bytes,s)=>bytes+s.length/2,0));
    return ack===({BEGIN:'OTA_READY',FINISH:'OTA_RESTART',ABORT:'OTA_ABORTED'})[command];
  }
  if (request.group === 138) return ack === (request.values[0] === 'RECOVER_AP' ? 'AP_RECOVERED' : 'AP_SAVED');
  if (request.group === 123) return ack === (request.values[0] === 'ARM' ? 'ARMED' : 'DISARMED');
  if (request.group === 135) return ack === setupAcks.get(request.values[0]);
  return request.group === 137 && ['PID_SAVED','PID_APPLIED_PENDING_SAVE'].includes(ack);
}
