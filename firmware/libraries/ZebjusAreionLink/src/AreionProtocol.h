#ifndef AREION_PROTOCOL_H
#define AREION_PROTOCOL_H

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace areion {

static const size_t MAX_PAYLOAD = 1536;
static const size_t MAX_VALUES = 32;
static const size_t MAX_STRING_BYTES = 128;
static const size_t MAX_FRAME = MAX_PAYLOAD + 32;

enum class Type { Hello, Read, Data, Set, Save, Ack, Error, Control, Ping, Release, Action };
enum class ValueType { Integer, Float, Boolean, String };

struct Value {
  ValueType type = ValueType::Integer;
  int64_t integer = 0;
  double real = 0.0;
  bool boolean = false;
  std::string text;

  static Value fromInt(int64_t value);
  static Value fromFloat(double value);
  static Value fromBool(bool value);
  static Value fromString(const std::string& value);
};

struct Message {
  Type type = Type::Data;
  uint16_t group = 0;
  uint16_t schema = 1;
  uint32_t session = 1;
  uint32_t seq = 1;
  std::vector<Value> data;
};

const char* typeName(Type type);
bool parseType(const std::string& name, Type& type);
uint32_t crc32(const uint8_t* bytes, size_t length);
bool encodeFrame(const Message& message, std::string& frame,
                 std::string* error = nullptr);
bool decodeFrame(const std::string& frame, Message& message,
                 std::string* error = nullptr);

// Stream decoder accepts fragmented/coalesced frames and skips noise. The
// returned Message changes only after an entire validated frame arrives.
// Storage is bounded to MAX_FRAME bytes. No timing/ownership decisions here.
class Decoder {
 public:
  bool feed(uint8_t byte, Message& message);
  void reset();
  const std::string& lastFrame() const { return lastFrame_; }
 private:
  std::string buffer_;
  std::string lastFrame_;
};

}  // namespace areion
#endif
