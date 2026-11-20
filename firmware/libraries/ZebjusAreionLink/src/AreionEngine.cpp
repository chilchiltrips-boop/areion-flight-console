#include "AreionEngine.h"
#include <cmath>
#include <limits>
#include <utility>

namespace areion {
namespace {
const size_t kMaxBindings = 32;
const size_t kMaxGroups = 24;
const size_t kMaxActions = 8;
const size_t kMaxStringBytes = 128;

bool validUtf8(const std::string& value) {
    const unsigned char* p = reinterpret_cast<const unsigned char*>(value.data());
    const size_t n = value.size();
    for (size_t i = 0; i < n;) {
        const unsigned char c = p[i++];
        if (c < 0x80) continue;
        uint32_t point;
        size_t extra;
        if (c >= 0xC2 && c <= 0xDF) { point = c & 0x1F; extra = 1; }
        else if (c >= 0xE0 && c <= 0xEF) { point = c & 0x0F; extra = 2; }
        else if (c >= 0xF0 && c <= 0xF4) { point = c & 0x07; extra = 3; }
        else return false;
        if (extra > n - i) return false;
        for (size_t j = 0; j < extra; ++j) {
            if ((p[i] & 0xC0) != 0x80) return false;
            point = (point << 6) | (p[i++] & 0x3F);
        }
        if ((extra == 1 && point < 0x80) || (extra == 2 && point < 0x800) ||
            (extra == 3 && point < 0x10000) || point > 0x10FFFF ||
            (point >= 0xD800 && point <= 0xDFFF)) return false;
    }
    return true;
}

void setError(std::string* error, const std::string& value) {
    if (error) *error = value;
}
}

Group::Group(uint16_t id, uint16_t schema, bool writable, bool persistent)
    : id_(id), schema_(schema), writable_(writable), persistent_(persistent),
      valid_(id != 0 && id != 9 && schema != 0 && (!persistent || writable)),
      sealed_(false) {}

Group& Group::append(BindingType type, void* pointer, double minimum,
                     double maximum, size_t maxBytes) {
    if (sealed_ || bindings_.size() >= kMaxBindings || !pointer ||
        !std::isfinite(minimum) || !std::isfinite(maximum) || minimum > maximum ||
        (type == BindingType::String && (maxBytes == 0 || maxBytes > kMaxStringBytes))) {
        valid_ = false;
        return *this;
    }
    for (size_t i = 0; i < bindings_.size(); ++i) {
        if (bindings_[i].pointer == pointer) {
            valid_ = false;
            return *this;
        }
    }
    Binding b = {type, pointer, minimum, maximum, maxBytes};
    bindings_.push_back(b);
    return *this;
}

Group& Group::add(float& value, double minimum, double maximum) {
    if (!std::isfinite(minimum) || !std::isfinite(maximum) || minimum > maximum ||
        minimum < -std::numeric_limits<float>::max() ||
        maximum > std::numeric_limits<float>::max()) valid_ = false;
    return append(BindingType::Float, &value, static_cast<float>(minimum), static_cast<float>(maximum));
}
Group& Group::add(double& value, double minimum, double maximum) {
    return append(BindingType::Double, &value, minimum, maximum);
}
Group& Group::add(int& value, int64_t minimum, int64_t maximum) {
    static_assert(sizeof(int) == 4, "ZebjusAreionLink integer bindings require 32-bit int");
    if (minimum < INT32_MIN || maximum > INT32_MAX) valid_ = false;
    return append(BindingType::Int, &value, static_cast<double>(minimum), static_cast<double>(maximum));
}
Group& Group::add(uint32_t& value, uint32_t minimum, uint32_t maximum) {
    return append(BindingType::Uint32, &value, minimum, maximum);
}
Group& Group::add(bool& value) { return append(BindingType::Bool, &value, 0, 1); }
Group& Group::add(std::string& value, size_t maxBytes) {
    return append(BindingType::String, &value, 0, 0, maxBytes);
}
Group& Group::validateWith(Validator validator) {
    if (sealed_) valid_ = false;
    else validator_ = std::move(validator);
    return *this;
}
Group& Group::onApplied(Applied callback) {
    if (sealed_) valid_ = false;
    else applied_ = std::move(callback);
    return *this;
}

bool Group::validateBindings(const std::vector<Value>& values) const {
    if (!valid_ || values.size() != bindings_.size() || values.empty()) return false;
    for (size_t i = 0; i < bindings_.size(); ++i) {
        const Binding& b = bindings_[i];
        const Value& v = values[i];
        switch (b.type) {
        case BindingType::Float:
        case BindingType::Double: {
            if (v.type != ValueType::Integer && v.type != ValueType::Float) return false;
            double number = v.type == ValueType::Integer ? static_cast<double>(v.integer) : v.real;
            if (!std::isfinite(number)) return false;
            if (b.type == BindingType::Float) {
                const float narrowed = static_cast<float>(number);
                if (!std::isfinite(narrowed) || (number != 0 && narrowed == 0)) return false;
                number = narrowed;
            }
            if (number < b.minimum || number > b.maximum) return false;
            break;
        }
        case BindingType::Int:
        case BindingType::Uint32:
            if (v.type != ValueType::Integer || v.integer < b.minimum || v.integer > b.maximum) return false;
            break;
        case BindingType::Bool:
            if (v.type != ValueType::Boolean) return false;
            break;
        case BindingType::String:
            if (v.type != ValueType::String || v.text.size() > b.maxBytes || !validUtf8(v.text)) return false;
            break;
        }
    }
    return true;
}

bool Group::validate(const std::vector<Value>& values) const {
    return validateBindings(values) && (!validator_ || validator_(values));
}

bool Group::normalized(const std::vector<Value>& input, std::vector<Value>& output) const {
    if (!validateBindings(input)) return false;
    std::vector<Value> result(input);
    for (size_t i = 0; i < bindings_.size(); ++i) {
        if (bindings_[i].type == BindingType::Float || bindings_[i].type == BindingType::Double) {
            double number = input[i].type == ValueType::Integer ? static_cast<double>(input[i].integer) : input[i].real;
            if (bindings_[i].type == BindingType::Float) number = static_cast<float>(number);
            result[i] = Value::fromFloat(number);
        }
    }
    // Validate what will actually be stored in the references. Rounding to
    // float32 can cross a custom bound, so incoming validation alone is not
    // sufficient. The application validator runs exactly once, on this form.
    if (!validate(result)) return false;
    output.swap(result);
    return true;
}

bool Group::values(std::vector<Value>& output) const {
    std::vector<Value> result;
    result.reserve(bindings_.size());
    for (size_t i = 0; i < bindings_.size(); ++i) {
        const Binding& b = bindings_[i];
        switch (b.type) {
        case BindingType::Float: result.push_back(Value::fromFloat(*static_cast<float*>(b.pointer))); break;
        case BindingType::Double: result.push_back(Value::fromFloat(*static_cast<double*>(b.pointer))); break;
        case BindingType::Int: result.push_back(Value::fromInt(*static_cast<int*>(b.pointer))); break;
        case BindingType::Uint32: result.push_back(Value::fromInt(*static_cast<uint32_t*>(b.pointer))); break;
        case BindingType::Bool: result.push_back(Value::fromBool(*static_cast<bool*>(b.pointer))); break;
        case BindingType::String: result.push_back(Value::fromString(*static_cast<std::string*>(b.pointer))); break;
        }
    }
    if (!validate(result)) return false;
    output.swap(result);
    return true;
}

bool Group::assign(const std::vector<Value>& values) {
    // Private operation: both callers validate the entire array before entering
    // here. Do not invoke the application validator again after the write guard.
    if (!valid_ || values.size() != bindings_.size()) return false;
    // All types, ranges, strings and cross-field constraints are checked above.
    // No callback or variable update occurs before the complete array passes.
    for (size_t i = 0; i < bindings_.size(); ++i) {
        const Binding& b = bindings_[i];
        const Value& v = values[i];
        switch (b.type) {
        case BindingType::Float:
            *static_cast<float*>(b.pointer) = static_cast<float>(v.type == ValueType::Integer ? static_cast<double>(v.integer) : v.real); break;
        case BindingType::Double:
            *static_cast<double*>(b.pointer) = v.type == ValueType::Integer ? static_cast<double>(v.integer) : v.real; break;
        case BindingType::Int: *static_cast<int*>(b.pointer) = static_cast<int>(v.integer); break;
        case BindingType::Uint32: *static_cast<uint32_t*>(b.pointer) = static_cast<uint32_t>(v.integer); break;
        case BindingType::Bool: *static_cast<bool*>(b.pointer) = v.boolean; break;
        case BindingType::String: *static_cast<std::string*>(b.pointer) = v.text; break;
        }
    }
    if (applied_) applied_();
    return true;
}

Engine::Engine()
    : store_(nullptr), fcSession_(0), ownerSession_(0), txSeq_(0), commandSeq_(0),
      controlSeq_(0), lastControlAt_(0), started_(false), hasCommand_(false),
      hasControlSequence_(false), hasControl_(false), ownerLeaseMs_(0),
      lastOwnerAt_(0), ownerExpired_(false), retiredSessions_(), nextRetired_(0) {}

void Engine::resetOwnerState() {
    ownerSession_ = 0;
    commandSeq_ = 0;
    controlSeq_ = 0;
    lastControlAt_ = 0;
    lastOwnerAt_ = 0;
    ownerExpired_ = false;
    hasCommand_ = false;
    hasControlSequence_ = false;
    hasControl_ = false;
    cachedRequest_.clear();
    cachedResponse_ = Response();
}

bool Engine::begin(uint32_t fcSession) {
    if (fcSession == 0) return false;
    fcSession_ = fcSession;
    txSeq_ = 0;
    started_ = true;
    resetOwnerState();
    retiredSessions_.fill(0);
    nextRetired_ = 0;
    releasedRequest_.clear();
    releasedResponse_ = Response();
    return true;
}

bool Engine::addGroup(Group& group) {
    if (!group.valid() || group.size() == 0 || groups_.size() >= kMaxGroups ||
        findGroup(group.id()) || findAction(group.id())) return false;
    // A variable must not have two writable owners; this would undermine a
    // group's validation through an overlapping second group. Read-only mirror
    // groups are allowed for convenient telemetry.
    if (group.writable()) {
        for (size_t g = 0; g < groups_.size(); ++g) {
            if (!groups_[g]->writable()) continue;
            for (size_t i = 0; i < group.bindings_.size(); ++i)
                for (size_t j = 0; j < groups_[g]->bindings_.size(); ++j)
                    if (group.bindings_[i].pointer == groups_[g]->bindings_[j].pointer) return false;
        }
    }
    group.sealed_ = true;
    groups_.push_back(&group);
    return true;
}

Group* Engine::findGroup(uint16_t id) const {
    for (size_t i = 0; i < groups_.size(); ++i) if (groups_[i]->id() == id) return groups_[i];
    return nullptr;
}

const Engine::Action* Engine::findAction(uint16_t id) const {
    for (size_t i = 0; i < actions_.size(); ++i)
        if (actions_[i].id == id) return &actions_[i];
    return nullptr;
}

bool Engine::addAction(uint16_t group, uint16_t schema, ActionHandler handler) {
    if (group == 0 || group == 9 || schema == 0 || !handler ||
        actions_.size() >= kMaxActions || findGroup(group) || findAction(group)) return false;
    actions_.push_back(Action{group, schema, std::move(handler)});
    return true;
}

bool Engine::newer(uint32_t candidate, uint32_t previous) {
    const uint32_t delta = candidate - previous;
    return delta != 0 && delta < 0x80000000UL;
}

bool Engine::equalData(const std::vector<Value>& a, const std::vector<Value>& b) {
    if (a.size() != b.size()) return false;
    for (size_t i = 0; i < a.size(); ++i) {
        if (a[i].type != b[i].type) return false;
        switch (a[i].type) {
        case ValueType::Integer: if (a[i].integer != b[i].integer) return false; break;
        case ValueType::Float: if (a[i].real != b[i].real) return false; break;
        case ValueType::Boolean: if (a[i].boolean != b[i].boolean) return false; break;
        case ValueType::String: if (a[i].text != b[i].text) return false; break;
        }
    }
    return true;
}
bool Engine::equalMessage(const Message& a, const Message& b) {
    return a.type == b.type && a.group == b.group && a.schema == b.schema &&
           a.session == b.session && a.seq == b.seq && equalData(a.data, b.data);
}
Message Engine::replyMessage(const Message& request, Type type) {
    Message result;
    result.type = type;
    result.group = request.group;
    result.schema = request.schema;
    result.session = request.session;
    result.seq = request.seq;
    return result;
}
Response Engine::error(const Message& request, const char* code) {
    Response result;
    result.reply = true;
    result.message = replyMessage(request, Type::Error);
    result.message.data.push_back(Value::fromString(code));
    return result;
}
Response Engine::ack(const Message& request, const char* code) {
    Response result;
    result.reply = true;
    result.message = replyMessage(request, Type::Ack);
    result.message.data.push_back(Value::fromString(code));
    return result;
}

bool Engine::storedValues(Group& group, Message& output, std::string& errorText) {
    if (!group.persistent()) { errorText = "NON_PERSISTENT"; return false; }
    if (!store_) { errorText = "NO_STORAGE"; return false; }
    if (!store_->load(group.id(), group.schema(), output, errorText)) {
        if (errorText.empty()) errorText = "LOAD_FAILED";
        return false;
    }
    if (output.type != Type::Data || output.group != group.id() || output.schema != group.schema() ||
        !group.validate(output.data)) { errorText = "INVALID_SAVED_DATA"; return false; }
    std::string wire;
    if (!encodeFrame(output, wire)) { errorText = "INVALID_SAVED_DATA"; return false; }
    return true;
}

Response Engine::command(const Message& request, uint32_t now) {
    if (request.type == Type::Ping) {
        if (request.group != 0 || request.schema != 1 || !request.data.empty()) return error(request, "BAD_REQUEST");
        return ack(request, "PONG");
    }
    if (request.type == Type::Action) {
        const Action* action = findAction(request.group);
        if (!action) return error(request, "UNKNOWN_GROUP");
        if (action->schema != request.schema) return error(request, "SCHEMA_MISMATCH");
        // Owner, lease and exact-byte command sequence checks have already
        // passed. The application validates data and guards the side effect.
        // Do not use the SET/SAVE guard here: e.g. a DISARM action must still
        // be executable when settings are write-locked while armed.
        const ActionResult result = action->handler(request.data, now);
        if (result.code.empty() || result.code.size() > kMaxStringBytes ||
            !validUtf8(result.code) || result.code.find('\0') != std::string::npos)
            return error(request, "INVALID_ACTION_RESULT");
        return result.success ? ack(request, result.code.c_str()) : error(request, result.code.c_str());
    }
    Group* group = findGroup(request.group);
    if (!group) return error(request, "UNKNOWN_GROUP");
    if (!group->valid()) return error(request, "INVALID_GROUP");
    if (group->schema() != request.schema) return error(request, "SCHEMA_MISMATCH");

    if (request.type == Type::Read) {
        Response result;
        result.reply = true;
        result.message = replyMessage(request, Type::Data);
        if (request.data.empty()) {
            if (!group->values(result.message.data)) return error(request, "INVALID_STATE");
        } else if (request.data.size() == 1 && request.data[0].type == ValueType::String && request.data[0].text == "saved") {
            Message saved;
            std::string why;
            if (!storedValues(*group, saved, why)) return error(request, why.size() <= 128 ? why.c_str() : "LOAD_FAILED");
            result.message.data = saved.data;
        } else return error(request, "BAD_REQUEST");
        std::string wire;
        if (!encodeFrame(result.message, wire)) return error(request, "FRAME_TOO_LARGE");
        return result;
    }
    if (request.type == Type::Set) {
        if (!group->writable()) return error(request, "READ_ONLY");
        if (!allowed()) return error(request, "WRITE_LOCKED");
        Message normalized = replyMessage(request, Type::Data);
        if (!group->normalized(request.data, normalized.data)) return error(request, "INVALID_VALUES");
        // A successful SET must remain readable/savable even when future IDs
        // use their maximum decimal width. Float32 conversion and int-to-float
        // bindings can produce a larger JSON representation than the SET.
        normalized.session = UINT32_MAX;
        normalized.seq = UINT32_MAX;
        std::string wire;
        if (!encodeFrame(normalized, wire)) return error(request, "FRAME_TOO_LARGE");
        // Recheck after the application validator, before any assignment.
        if (!allowed()) return error(request, "WRITE_LOCKED");
        if (beforeSet_ && !beforeSet_(group->id(), normalized.data)) return error(request, "SETUP_WRITE_LOCKED");
        if (!group->assign(normalized.data)) return error(request, "INVALID_VALUES");
        return ack(request, "APPLIED_UNSAVED");
    }
    if (request.type == Type::Save) {
        if (!request.data.empty()) return error(request, "BAD_REQUEST");
        if (!group->persistent()) return error(request, "NON_PERSISTENT");
        if (!allowed()) return error(request, "WRITE_LOCKED");
        if (!store_) return error(request, "NO_STORAGE");
        Message stored = replyMessage(request, Type::Data);
        if (!group->values(stored.data)) return error(request, "INVALID_STATE");
        std::string wire;
        if (!encodeFrame(stored, wire)) return error(request, "FRAME_TOO_LARGE");
        if (!allowed()) return error(request, "WRITE_LOCKED");
        std::string why;
        if (!store_->save(stored, why)) return error(request, why.empty() || why.size() > 128 ? "SAVE_FAILED" : why.c_str());
        Message verified;
        if (!storedValues(*group, verified, why) || !equalData(stored.data, verified.data))
            return error(request, "SAVE_VERIFY_FAILED");
        // No runtime assignment occurs during SAVE. A verified commit remains
        // SAVED even if the application guard changed while storage was busy.
        return ack(request, "SAVED");
    }
    return error(request, "BAD_REQUEST");
}

Response Engine::handle(const Message& request, uint32_t now, const std::string& originalFrame) {
    Response silent;
    if (!started_) return silent;
    std::string identity;
    if (!encodeFrame(request, identity)) return silent;
    if (!originalFrame.empty()) {
        Message decoded;
        if (!decodeFrame(originalFrame, decoded) || !equalMessage(request, decoded)) return silent;
        identity = originalFrame;
    }
    expireOwner(now);
    // A lost RELEASE acknowledgement may be retried on either route after
    // ownership changed. Return only the exact old acknowledgement; never
    // disturb the current owner or refresh its lease.
    if (request.type == Type::Release && !releasedRequest_.empty() &&
        identity == releasedRequest_) return releasedResponse_;
    if (request.type == Type::Hello) {
        if (request.group != 0 || request.schema != 1 || !request.data.empty()) return error(request, "BAD_HELLO");
        if (request.session == fcSession_) return error(request, "SESSION_COLLISION");
        if (retired(request.session)) return error(request, "SESSION_RETIRED");
        if (ownerSession_ != 0 && ownerSession_ != request.session) return error(request, "BUSY");
        if (ownerSession_ == 0) {
            resetOwnerState();
            ownerSession_ = request.session;
            lastOwnerAt_ = now;
        }
        if (ownerExpired_) return error(request, "SESSION_EXPIRED");
        Response result = ack(request, "HELLO");
        result.message.data.push_back(Value::fromInt(fcSession_));
        result.acceptedHello = true;
        return result;
    }
    // Never answer responses/events: two endpoint engines cannot form an
    // ERROR-to-ERROR or DATA-to-ERROR echo loop.
    if (request.type == Type::Data || request.type == Type::Ack || request.type == Type::Error) return silent;
    if (ownerSession_ == 0 || request.session != ownerSession_) {
        if (request.type == Type::Control) return silent;
        return error(request, "NOT_OWNER");
    }
    if (ownerExpired_) {
        if (request.type == Type::Control) return silent;
        return error(request, "SESSION_EXPIRED");
    }
    if (request.type == Type::Control) {
        if (request.group != 9 || request.schema != 1 || request.data.size() != 8) return silent;
        int channels[8];
        for (size_t i = 0; i < 8; ++i) {
            if (request.data[i].type != ValueType::Integer || request.data[i].integer < 1000 || request.data[i].integer > 2000) return silent;
            channels[i] = static_cast<int>(request.data[i].integer);
        }
        if (hasControlSequence_ && !newer(request.seq, controlSeq_)) return silent;
        // Consume valid control sequence even when LINK input is disabled, so
        // a delayed duplicate cannot become fresh after switching input source.
        controlSeq_ = request.seq;
        hasControlSequence_ = true;
        lastOwnerAt_ = now;
        if (!controlEnabled_ || !controlEnabled_() || !controlHandler_) {
            invalidateControl();
            return silent;
        }
        lastControlAt_ = now;
        hasControl_ = true;
        controlHandler_(channels, 8);
        silent.acceptedControl = true;
        return silent;
    }
    if (hasCommand_) {
        if (request.seq == commandSeq_) {
            return identity == cachedRequest_ ? cachedResponse_ : error(request, "SEQUENCE_CONFLICT");
        }
        if (!newer(request.seq, commandSeq_)) return error(request, "STALE_SEQUENCE");
    }
    Response result;
    if (request.type == Type::Release) {
        if (request.group != 0 || request.schema != 1 || !request.data.empty())
            result = error(request, "BAD_REQUEST");
        else if (!ownerReleaseAllowed()) result = error(request, "WRITE_LOCKED");
        else {
            result = ack(request, "RELEASED");
            releasedRequest_ = identity;
            releasedResponse_ = result;
            retireOwner();
            resetOwnerState();
            return result;
        }
    } else result = command(request, now);
    if (result.reply && result.message.type != Type::Error) lastOwnerAt_ = now;
    commandSeq_ = request.seq;
    hasCommand_ = true;
    cachedRequest_.swap(identity);
    cachedResponse_ = result;
    return result;
}

bool Engine::snapshot(uint16_t id, Message& output) {
    Group* group = findGroup(id);
    if (!started_ || !group) return false;
    Message result;
    result.type = Type::Data;
    result.group = id;
    result.schema = group->schema();
    result.session = fcSession_;
    result.seq = txSeq_ == UINT32_MAX ? 1 : txSeq_ + 1;
    if (!group->values(result.data)) return false;
    std::string wire;
    if (!encodeFrame(result, wire)) return false;
    txSeq_ = result.seq;
    output = result;
    return true;
}

bool Engine::restore(Group& group, std::string* errorOutput) {
    if (findGroup(group.id()) != &group) { setError(errorOutput, "UNKNOWN_GROUP"); return false; }
    Message saved;
    std::string why;
    if (!storedValues(group, saved, why)) { setError(errorOutput, why); return false; }
    if (!group.assign(saved.data)) { setError(errorOutput, "INVALID_SAVED_DATA"); return false; }
    setError(errorOutput, "");
    return true;
}

bool Engine::applyLocal(uint16_t id, const std::vector<Value>& values) {
    Group* group = findGroup(id);
    std::vector<Value> normalized;
    return group && group->writable() && group->normalized(values, normalized)
        && group->assign(normalized);
}

bool Engine::setOwnerLease(uint32_t timeoutMs) {
    if (timeoutMs >= 0x80000000UL || ownerSession_ != 0) return false;
    ownerLeaseMs_ = timeoutMs;
    return true;
}

bool Engine::retired(uint32_t session) const {
    for (size_t i = 0; i < retiredSessions_.size(); ++i)
        if (retiredSessions_[i] == session) return true;
    return false;
}

void Engine::retireOwner() {
    if (!ownerSession_ || retired(ownerSession_)) return;
    retiredSessions_[nextRetired_] = ownerSession_;
    nextRetired_ = (nextRetired_ + 1) % retiredSessions_.size();
}

bool Engine::expireOwner(uint32_t now) {
    if (!ownerSession_ || !ownerLeaseMs_) return false;
    if (!ownerExpired_ && static_cast<uint32_t>(now - lastOwnerAt_) < ownerLeaseMs_) return false;
    ownerExpired_ = true;
    invalidateControl();
    if (!ownerReleaseAllowed()) return false;
    retireOwner();
    resetOwnerState();
    return true;
}

bool Engine::releaseOwner() {
    if (!ownerReleaseAllowed()) return false;
    resetOwnerState();
    return true;
}
bool Engine::controlFresh(uint32_t now, uint32_t timeoutMs) const {
    return hasControl_ && timeoutMs > 0 && timeoutMs < 0x80000000UL &&
           controlEnabled_ && controlEnabled_() && static_cast<uint32_t>(now - lastControlAt_) <= timeoutMs;
}
} // namespace areion
