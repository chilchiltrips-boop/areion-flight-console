#pragma once
#include <stddef.h>
#include <stdint.h>

namespace gateway {
constexpr uint8_t POLL = 0x50, FRAME = 0x46, REPLY = 0x41;
constexpr size_t MAX_FRAME = 1552, BURST = 4;
constexpr uint32_t CREDIT_MS = 120, MAX_POLL_GAP_MS = 250;

inline uint32_t read32(const uint8_t* p) {
  return (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) | (uint32_t(p[2]) << 8) | p[3];
}
inline void write32(uint8_t* p, uint32_t value) {
  p[0] = uint8_t(value >> 24); p[1] = uint8_t(value >> 16);
  p[2] = uint8_t(value >> 8); p[3] = uint8_t(value);
}

struct Credits {
  struct Ticket { uint32_t value = 0, at = 0; };
  Ticket tickets[8]{};
  unsigned index = 0;
  void issue(uint32_t value, uint32_t now) {
    tickets[index] = {value, now};
    index = (index + 1) % 8;
  }
  bool valid(uint32_t value, uint32_t now) const {
    if (!value) return false;
    for (const Ticket& t : tickets)
      if (t.value == value && uint32_t(now - t.at) <= CREDIT_MS) return true;
    return false;
  }
};
}
