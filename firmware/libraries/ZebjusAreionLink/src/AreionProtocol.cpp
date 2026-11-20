#include "AreionProtocol.h"

#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>

namespace areion {
namespace {
const int64_t MIN_INTEGER = -2147483648LL;
const int64_t MAX_INTEGER = 4294967295LL;

bool fail(std::string* error, const char* reason) {
  if (error) *error = reason;
  return false;
}
bool digit(char c) { return c >= '0' && c <= '9'; }
int hexDigit(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

// Reject overlong encodings, lone continuation bytes, surrogate code points
// and code points above U+10FFFF. JSON strings may contain embedded U+0000.
bool validUtf8(const std::string& value) {
  size_t i = 0;
  while (i < value.size()) {
    const uint8_t c = static_cast<uint8_t>(value[i++]);
    if (c < 0x80) continue;
    uint32_t cp = 0;
    size_t count = 0;
    uint32_t minimum = 0;
    if (c >= 0xC2 && c <= 0xDF) { cp = c & 0x1F; count = 1; minimum = 0x80; }
    else if (c >= 0xE0 && c <= 0xEF) { cp = c & 0x0F; count = 2; minimum = 0x800; }
    else if (c >= 0xF0 && c <= 0xF4) { cp = c & 0x07; count = 3; minimum = 0x10000; }
    else return false;
    if (count > value.size() - i) return false;
    for (size_t j = 0; j < count; ++j) {
      const uint8_t next = static_cast<uint8_t>(value[i++]);
      if ((next & 0xC0) != 0x80) return false;
      cp = (cp << 6) | (next & 0x3F);
    }
    if (cp < minimum || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) return false;
  }
  return true;
}
void appendUtf8(uint32_t cp, std::string& text) {
  if (cp <= 0x7F) text += static_cast<char>(cp);
  else if (cp <= 0x7FF) {
    text += static_cast<char>(0xC0 | (cp >> 6));
    text += static_cast<char>(0x80 | (cp & 0x3F));
  } else if (cp <= 0xFFFF) {
    text += static_cast<char>(0xE0 | (cp >> 12));
    text += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
    text += static_cast<char>(0x80 | (cp & 0x3F));
  } else {
    text += static_cast<char>(0xF0 | (cp >> 18));
    text += static_cast<char>(0x80 | ((cp >> 12) & 0x3F));
    text += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
    text += static_cast<char>(0x80 | (cp & 0x3F));
  }
}

class JsonParser {
 public:
  explicit JsonParser(const std::string& payload) : s_(payload), p_(0) {}
  bool parse(Message& output) {
    Message result;
    unsigned mask = 0;
    if (!take('{')) return false;
    do {
      std::string key;
      if (!string(key) || !take(':')) return false;
      unsigned bit = 0;
      if (key == "v") bit = 1;
      else if (key == "type") bit = 2;
      else if (key == "group") bit = 4;
      else if (key == "schema") bit = 8;
      else if (key == "session") bit = 16;
      else if (key == "seq") bit = 32;
      else if (key == "data") bit = 64;
      else return false;
      if (mask & bit) return false;
      mask |= bit;
      uint32_t number = 0;
      if (key == "type") {
        std::string name;
        if (!string(name) || !parseType(name, result.type)) return false;
      } else if (key == "data") {
        if (!array(result.data)) return false;
      } else {
        if (!unsignedNumber(number)) return false;
        if (key == "v" && number != 2) return false;
        if (key == "group") {
          if (number > 65535) return false;
          result.group = static_cast<uint16_t>(number);
        } else if (key == "schema") {
          if (number == 0 || number > 65535) return false;
          result.schema = static_cast<uint16_t>(number);
        } else if (key == "session") {
          if (number == 0) return false;
          result.session = number;
        } else if (key == "seq") {
          if (number == 0) return false;
          result.seq = number;
        }
      }
      whitespace();
      if (p_ < s_.size() && s_[p_] == ',') { ++p_; continue; }
      break;
    } while (true);
    if (!take('}') || mask != 127) return false;
    whitespace();
    if (p_ != s_.size()) return false;
    output = result;
    return true;
  }
 private:
  const std::string& s_;
  size_t p_;

  void whitespace() {
    while (p_ < s_.size() && (s_[p_] == ' ' || s_[p_] == '\t' || s_[p_] == '\r' || s_[p_] == '\n')) ++p_;
  }
  bool take(char c) {
    whitespace();
    if (p_ >= s_.size() || s_[p_] != c) return false;
    ++p_;
    return true;
  }
  bool hex4(uint32_t& cp) {
    if (s_.size() - p_ < 4) return false;
    cp = 0;
    for (size_t n = 0; n < 4; ++n) {
      const int v = hexDigit(s_[p_++]);
      if (v < 0) return false;
      cp = (cp << 4) | static_cast<unsigned>(v);
    }
    return true;
  }
  bool string(std::string& value) {
    value.clear();
    if (!take('"')) return false;
    while (p_ < s_.size()) {
      const uint8_t c = static_cast<uint8_t>(s_[p_++]);
      if (c == '"') return validUtf8(value);
      if (c < 0x20) return false;
      if (c != '\\') value += static_cast<char>(c);
      else {
        if (p_ >= s_.size()) return false;
        const char e = s_[p_++];
        switch (e) {
          case '"': value += '"'; break;
          case '\\': value += '\\'; break;
          case '/': value += '/'; break;
          case 'b': value += '\b'; break;
          case 'f': value += '\f'; break;
          case 'n': value += '\n'; break;
          case 'r': value += '\r'; break;
          case 't': value += '\t'; break;
          case 'u': {
            uint32_t cp = 0;
            if (!hex4(cp)) return false;
            if (cp >= 0xD800 && cp <= 0xDBFF) {
              if (s_.size() - p_ < 6 || s_[p_] != '\\' || s_[p_ + 1] != 'u') return false;
              p_ += 2;
              uint32_t low = 0;
              if (!hex4(low) || low < 0xDC00 || low > 0xDFFF) return false;
              cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
            } else if (cp >= 0xDC00 && cp <= 0xDFFF) return false;
            appendUtf8(cp, value);
            break;
          }
          default: return false;
        }
      }
      if (value.size() > MAX_STRING_BYTES) return false;
    }
    return false;
  }
  bool unsignedNumber(uint32_t& value) {
    whitespace();
    if (p_ == s_.size() || !digit(s_[p_])) return false;
    const size_t first = p_;
    uint64_t accumulated = 0;
    while (p_ < s_.size() && digit(s_[p_])) {
      accumulated = accumulated * 10 + static_cast<unsigned>(s_[p_++] - '0');
      if (accumulated > 4294967295ULL) return false;
    }
    if (p_ - first > 1 && s_[first] == '0') return false;
    value = static_cast<uint32_t>(accumulated);
    return true;
  }
  bool number(Value& value) {
    whitespace();
    const size_t first = p_;
    bool negative = false;
    if (p_ < s_.size() && s_[p_] == '-') { negative = true; ++p_; }
    if (p_ == s_.size() || !digit(s_[p_])) return false;
    if (s_[p_] == '0') ++p_;
    else while (p_ < s_.size() && digit(s_[p_])) ++p_;
    bool floating = false;
    if (p_ < s_.size() && s_[p_] == '.') {
      floating = true; ++p_;
      if (p_ == s_.size() || !digit(s_[p_])) return false;
      while (p_ < s_.size() && digit(s_[p_])) ++p_;
    }
    if (p_ < s_.size() && (s_[p_] == 'e' || s_[p_] == 'E')) {
      floating = true; ++p_;
      if (p_ < s_.size() && (s_[p_] == '+' || s_[p_] == '-')) ++p_;
      if (p_ == s_.size() || !digit(s_[p_])) return false;
      while (p_ < s_.size() && digit(s_[p_])) ++p_;
    }
    const std::string token = s_.substr(first, p_ - first);
    if (floating) {
      char* end = nullptr;
      errno = 0;
      const double parsed = std::strtod(token.c_str(), &end);
      if (end != token.c_str() + token.size() || !std::isfinite(parsed)) return false;
      // Reject underflow rather than silently converting a nonzero setting to zero.
      if (errno == ERANGE && parsed == 0.0) return false;
      value = Value::fromFloat(parsed);
    } else {
      uint64_t accumulated = 0;
      for (size_t i = negative ? 1 : 0; i < token.size(); ++i) {
        accumulated = accumulated * 10 + static_cast<unsigned>(token[i] - '0');
        if (accumulated > 4294967295ULL) return false;
      }
      const int64_t parsed = negative ? -static_cast<int64_t>(accumulated) : static_cast<int64_t>(accumulated);
      if (parsed < MIN_INTEGER || parsed > MAX_INTEGER) return false;
      value = Value::fromInt(parsed);
    }
    return true;
  }
  bool scalar(Value& value) {
    whitespace();
    if (p_ == s_.size()) return false;
    if (s_[p_] == '"') {
      std::string text;
      if (!string(text)) return false;
      value = Value::fromString(text);
      return true;
    }
    if (s_.compare(p_, 4, "true") == 0) { p_ += 4; value = Value::fromBool(true); return true; }
    if (s_.compare(p_, 5, "false") == 0) { p_ += 5; value = Value::fromBool(false); return true; }
    return number(value);
  }
  bool array(std::vector<Value>& data) {
    if (!take('[')) return false;
    whitespace();
    if (p_ < s_.size() && s_[p_] == ']') { ++p_; return true; }
    do {
      if (data.size() >= MAX_VALUES) return false;
      Value value;
      if (!scalar(value)) return false;
      data.push_back(value);
      whitespace();
      if (p_ < s_.size() && s_[p_] == ',') { ++p_; continue; }
      break;
    } while (true);
    return take(']');
  }
};

bool quote(const std::string& input, std::string& output) {
  if (input.size() > MAX_STRING_BYTES || !validUtf8(input)) return false;
  static const char* digits = "0123456789abcdef";
  output += '"';
  for (size_t i = 0; i < input.size(); ++i) {
    const uint8_t c = static_cast<uint8_t>(input[i]);
    if (c == '"' || c == '\\') { output += '\\'; output += static_cast<char>(c); }
    else if (c < 0x20) {
      output += "\\u00";
      output += digits[c >> 4];
      output += digits[c & 15];
    } else output += static_cast<char>(c);
  }
  output += '"';
  return true;
}
}  // namespace

Value Value::fromInt(int64_t v) { Value r; r.type = ValueType::Integer; r.integer = v; return r; }
Value Value::fromFloat(double v) { Value r; r.type = ValueType::Float; r.real = v; return r; }
Value Value::fromBool(bool v) { Value r; r.type = ValueType::Boolean; r.boolean = v; return r; }
Value Value::fromString(const std::string& v) { Value r; r.type = ValueType::String; r.text = v; return r; }

const char* typeName(Type type) {
  switch (type) {
    case Type::Hello: return "HELLO";
    case Type::Read: return "READ";
    case Type::Data: return "DATA";
    case Type::Set: return "SET";
    case Type::Save: return "SAVE";
    case Type::Ack: return "ACK";
    case Type::Error: return "ERROR";
    case Type::Control: return "CONTROL";
    case Type::Ping: return "PING";
    case Type::Release: return "RELEASE";
    case Type::Action: return "ACTION";
  }
  return nullptr;
}
bool parseType(const std::string& name, Type& type) {
  for (int i = static_cast<int>(Type::Hello); i <= static_cast<int>(Type::Action); ++i) {
    const Type candidate = static_cast<Type>(i);
    if (name == typeName(candidate)) { type = candidate; return true; }
  }
  return false;
}
uint32_t crc32(const uint8_t* bytes, size_t length) {
  uint32_t crc = 0xFFFFFFFFU;
  for (size_t i = 0; i < length; ++i) {
    crc ^= bytes[i];
    for (int bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xEDB88320U & (0U - (crc & 1U)));
  }
  return crc ^ 0xFFFFFFFFU;
}

bool encodeFrame(const Message& message, std::string& frame, std::string* error) {
  const char* name = typeName(message.type);
  if (!name || !message.schema || !message.session || !message.seq || message.data.size() > MAX_VALUES)
    return fail(error, "INVALID_ENVELOPE");
  char header[160];
  const int n = std::snprintf(header, sizeof(header),
      "{\"v\":2,\"type\":\"%s\",\"group\":%u,\"schema\":%u,\"session\":%lu,\"seq\":%lu,\"data\":[",
      name, static_cast<unsigned>(message.group), static_cast<unsigned>(message.schema),
      static_cast<unsigned long>(message.session), static_cast<unsigned long>(message.seq));
  if (n <= 0 || static_cast<size_t>(n) >= sizeof(header)) return fail(error, "ENCODE_FAILED");
  std::string payload(header, static_cast<size_t>(n));
  for (size_t i = 0; i < message.data.size(); ++i) {
    if (i) payload += ',';
    const Value& value = message.data[i];
    char number[64];
    switch (value.type) {
      case ValueType::Integer:
        if (value.integer < MIN_INTEGER || value.integer > MAX_INTEGER) return fail(error, "INTEGER_RANGE");
        std::snprintf(number, sizeof(number), "%lld", static_cast<long long>(value.integer));
        payload += number;
        break;
      case ValueType::Float: {
        if (!std::isfinite(value.real)) return fail(error, "NONFINITE_FLOAT");
        const int count = std::snprintf(number, sizeof(number), "%.17g", value.real);
        if (count <= 0 || static_cast<size_t>(count) >= sizeof(number)) return fail(error, "FLOAT_FORMAT");
        // JSON syntax always uses a dot, regardless of the host locale.
        for (int j = 0; j < count; ++j) if (number[j] == ',') number[j] = '.';
        payload += number;
        if (!std::strchr(number, '.') && !std::strchr(number, 'e') && !std::strchr(number, 'E')) payload += ".0";
        break;
      }
      case ValueType::Boolean: payload += value.boolean ? "true" : "false"; break;
      case ValueType::String:
        if (!quote(value.text, payload)) return fail(error, "INVALID_STRING");
        break;
      default: return fail(error, "INVALID_VALUE_TYPE");
    }
    if (payload.size() > MAX_PAYLOAD) return fail(error, "PAYLOAD_TOO_LARGE");
  }
  payload += "]}";
  if (payload.size() > MAX_PAYLOAD) return fail(error, "PAYLOAD_TOO_LARGE");
  char prefix[16], suffix[16];
  std::snprintf(prefix, sizeof(prefix), "$%u:", static_cast<unsigned>(payload.size()));
  std::snprintf(suffix, sizeof(suffix), "*%08lX\n", static_cast<unsigned long>(crc32(
      reinterpret_cast<const uint8_t*>(payload.data()), payload.size())));
  frame = prefix + payload + suffix;
  if (error) error->clear();
  return true;
}

bool decodeFrame(const std::string& frame, Message& message, std::string* error) {
  if (frame.size() > MAX_FRAME || frame.size() < 14 || frame[0] != '$') return fail(error, "INVALID_FRAME");
  size_t p = 1;
  if (!digit(frame[p]) || frame[p] == '0') return fail(error, "INVALID_LENGTH");
  size_t length = 0;
  while (p < frame.size() && digit(frame[p])) {
    length = length * 10 + static_cast<unsigned>(frame[p++] - '0');
    if (length > MAX_PAYLOAD) return fail(error, "PAYLOAD_TOO_LARGE");
  }
  if (p >= frame.size() || frame[p++] != ':' || frame.size() != p + length + 10)
    return fail(error, "LENGTH_MISMATCH");
  const size_t start = p;
  p += length;
  if (frame[p++] != '*') return fail(error, "INVALID_TRAILER");
  uint32_t suppliedCrc = 0;
  for (size_t i = 0; i < 8; ++i) {
    const char c = frame[p++];
    if (!digit(c) && !(c >= 'A' && c <= 'F')) return fail(error, "INVALID_CRC");
    suppliedCrc = (suppliedCrc << 4) | static_cast<unsigned>(hexDigit(c));
  }
  if (frame[p] != '\n') return fail(error, "INVALID_TRAILER");
  if (suppliedCrc != crc32(reinterpret_cast<const uint8_t*>(frame.data() + start), length)) return fail(error, "CRC_MISMATCH");
  const std::string payload = frame.substr(start, length);
  Message result;
  JsonParser parser(payload);
  if (!parser.parse(result)) return fail(error, "INVALID_JSON");
  message = result;
  if (error) error->clear();
  return true;
}

bool Decoder::feed(uint8_t byte, Message& message) {
  if (buffer_.empty() && byte != '$') return false;
  buffer_ += static_cast<char>(byte);
  if (buffer_.size() > MAX_FRAME) buffer_.erase(0, buffer_.size() - MAX_FRAME);
  if (byte != '\n') return false;
  // Scanning only on a potential terminator bounds work per input byte. Try
  // every '$' so a corrupt/truncated earlier length cannot swallow a new
  // valid frame. A '$' inside a legitimate JSON string is never discarded.
  size_t start = buffer_.find('$');
  while (start != std::string::npos) {
    if (decodeFrame(buffer_.substr(start), message)) {
      lastFrame_ = buffer_.substr(start);
      buffer_.clear();
      return true;
    }
    start = buffer_.find('$', start + 1);
  }
  return false;
}
void Decoder::reset() { buffer_.clear(); lastFrame_.clear(); }
}  // namespace areion
