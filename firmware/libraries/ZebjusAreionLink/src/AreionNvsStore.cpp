#include "AreionNvsStore.h"
#include <cstdio>
#include <cstring>

namespace areion {
namespace {
void keyFor(char* key, uint16_t group, char suffix) { snprintf(key, 12, "g%04X%c", group, suffix); }
uint32_t u32(const uint8_t* b) { return uint32_t(b[0]) | (uint32_t(b[1]) << 8) | (uint32_t(b[2]) << 16) | (uint32_t(b[3]) << 24); }
void put32(uint8_t* b, uint32_t v) { for (int i = 0; i < 4; ++i) b[i] = uint8_t(v >> (i * 8)); }
uint32_t frameCRC(const std::string& f) { return crc32(reinterpret_cast<const uint8_t*>(f.data()), f.size()); }
}
bool NvsStore::begin(const char* name) {
  if (ready_) return false;
  if (!name || !*name || strlen(name) > 15) return false;
  ready_ = nvs_open(name, NVS_READWRITE, &handle_) == ESP_OK;
  uncertain_ = false; return ready_;
}
void NvsStore::end() { if (ready_) nvs_close(handle_); ready_ = false; }
bool NvsStore::readHead(uint16_t group, Head& h, bool& exists) {
  char key[12]; keyFor(key, group, 'h');
  size_t n = 0;
  esp_err_t result = nvs_get_blob(handle_, key, nullptr, &n);
  // Only an explicit NOT_FOUND result means a first save. Read/type errors must not
  // select slot A and overwrite a potentially committed value.
  exists = result != ESP_ERR_NVS_NOT_FOUND;
  if (result != ESP_OK || n != 20) return false;
  uint8_t b[20];
  if (nvs_get_blob(handle_, key, b, &n) != ESP_OK || n != sizeof(b) || memcmp(b, "ZAL2", 4) != 0 ||
      b[8] > 1 || b[9] || b[10] || b[11] || crc32(b, 16) != u32(b + 16)) return false;
  h.revision = u32(b + 4); h.slot = b[8]; h.crc = u32(b + 12);
  return h.revision != 0;
}
bool NvsStore::readSlot(uint16_t group, uint8_t slot, std::string& frame) {
  char key[12]; keyFor(key, group, slot ? 'b' : 'a');
  size_t n = 0;
  if (nvs_get_blob(handle_, key, nullptr, &n) != ESP_OK || !n || n > MAX_FRAME) return false;
  frame.resize(n);
  return nvs_get_blob(handle_, key, &frame[0], &n) == ESP_OK && n == frame.size();
}
bool NvsStore::verified(uint16_t group, uint16_t schema, const Head& h, Message& out, std::string* frame) {
  std::string f;
  if (!readSlot(group, h.slot, f) || frameCRC(f) != h.crc || !decodeFrame(f, out) ||
      out.type != Type::Data || out.group != group || out.schema != schema ||
      out.session != 1 || out.seq != h.revision) return false;
  if (frame) *frame = f;
  return true;
}
bool NvsStore::load(uint16_t group, uint16_t schema, Message& out, std::string& error) {
  if (!ready_) { error = "NO_STORAGE"; return false; }
  Head h; bool exists = false;
  if (!readHead(group, h, exists)) { error = exists ? "STORAGE_CORRUPT" : "NOT_SAVED"; return false; }
  Message result;
  if (!verified(group, schema, h, result)) { error = "STORAGE_CORRUPT_OR_SCHEMA"; return false; }
  out = result; error.clear(); return true;
}
bool NvsStore::save(const Message& snapshot, std::string& error) {
  if (!ready_) { error = "NO_STORAGE"; return false; }
  if (uncertain_) { error = "SAVE_UNCERTAIN_REBOOT"; return false; }
  Head previous; bool exists = false;
  bool headOK = readHead(snapshot.group, previous, exists);
  if (exists && !headOK) { error = "STORAGE_CORRUPT"; return false; }
  if (headOK && previous.revision == UINT32_MAX) { error = "REVISION_EXHAUSTED"; return false; }
  Message normalized = snapshot;
  normalized.type = Type::Data; normalized.session = 1;
  normalized.seq = headOK ? previous.revision : 1;
  std::string same;
  if (!encodeFrame(normalized, same, &error)) return false;
  if (headOK) {
    Message old; std::string oldFrame;
    if (verified(snapshot.group, snapshot.schema, previous, old, &oldFrame) && oldFrame == same) {
      error.clear(); return true; // no flash write for an unchanged group
    }
  }
  Head next;
  next.revision = headOK ? previous.revision + 1 : 1;
  next.slot = headOK ? uint8_t(1 - previous.slot) : 0;
  normalized.seq = next.revision;
  std::string frame;
  if (!encodeFrame(normalized, frame, &error)) return false;
  next.crc = frameCRC(frame);
  char slotKey[12]; keyFor(slotKey, snapshot.group, next.slot ? 'b' : 'a');
  if (nvs_set_blob(handle_, slotKey, frame.data(), frame.size()) != ESP_OK || nvs_commit(handle_) != ESP_OK) {
    error = "SAVE_FAILED"; return false;
  }
  Message check;
  if (!verified(snapshot.group, snapshot.schema, next, check)) { error = "SAVE_VERIFY_FAILED"; return false; }
  uint8_t head[20] = {'Z','A','L','2'};
  put32(head + 4, next.revision); head[8] = next.slot; put32(head + 12, next.crc);
  put32(head + 16, crc32(head, 16));
  char headKey[12]; keyFor(headKey, snapshot.group, 'h');
  // Once the commit head write is attempted, failures are ambiguous. Block further saves until reboot.
  esp_err_t wrote = nvs_set_blob(handle_, headKey, head, sizeof(head));
  esp_err_t committedResult = wrote == ESP_OK ? nvs_commit(handle_) : wrote;
  Head committed; bool committedExists = false;
  if (wrote != ESP_OK || committedResult != ESP_OK || !readHead(snapshot.group, committed, committedExists) ||
      committed.revision != next.revision || committed.slot != next.slot || committed.crc != next.crc ||
      !verified(snapshot.group, snapshot.schema, committed, check)) {
    uncertain_ = true; error = "SAVE_UNCERTAIN_REBOOT"; return false;
  }
  error.clear(); return true;
}
}
