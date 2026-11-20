#pragma once
#include "AreionEngine.h"
#include <nvs.h>

namespace areion {
// Separate namespace from ZA1. No automatic migration of the old wire/storage format.
// Each group is an independent transaction; SAVE does not commit other groups.
class NvsStore : public Store {
 public:
  NvsStore() = default;
  ~NvsStore() override { end(); }
  NvsStore(const NvsStore&) = delete;
  NvsStore& operator=(const NvsStore&) = delete;
  bool begin(const char* name = "zaLink2");
  void end();
  bool load(uint16_t group, uint16_t schema, Message& out, std::string& error) override;
  bool save(const Message& snapshot, std::string& error) override;
  bool uncertain() const { return uncertain_; }
 private:
  nvs_handle_t handle_ = 0;
  bool ready_ = false, uncertain_ = false;
  struct Head { uint32_t revision = 0, crc = 0; uint8_t slot = 0; };
  bool readHead(uint16_t group, Head& head, bool& exists);
  bool readSlot(uint16_t group, uint8_t slot, std::string& frame);
  bool verified(uint16_t group, uint16_t schema, const Head&, Message&, std::string* frame = nullptr);
};
}
