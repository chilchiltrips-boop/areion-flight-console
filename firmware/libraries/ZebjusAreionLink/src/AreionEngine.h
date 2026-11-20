#ifndef ZEBJUS_AREION_ENGINE_H
#define ZEBJUS_AREION_ENGINE_H

#include "AreionProtocol.h"
#include <array>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace areion {

// Bindings refer to application-owned variables. Keep them and Group alive for
// the entire Engine lifetime. Configure all bindings before addGroup().
class Group {
public:
    typedef std::function<bool(const std::vector<Value>&)> Validator;
    typedef std::function<void()> Applied;

    Group(uint16_t id, uint16_t schema = 1, bool writable = false,
          bool persistent = false);
    // Float bounds are rounded to float32, just like the bound variable. Inputs
    // mapping to the same representable endpoint are accepted.
    Group& add(float& value, double minimum = -3.4028234663852886e38,
               double maximum = 3.4028234663852886e38);
    Group& add(double& value, double minimum = -1.7976931348623157e308,
               double maximum = 1.7976931348623157e308);
    Group& add(int& value, int64_t minimum = INT32_MIN,
               int64_t maximum = INT32_MAX);
    Group& add(uint32_t& value, uint32_t minimum = 0,
               uint32_t maximum = UINT32_MAX);
    Group& add(bool& value);
    Group& add(std::string& value, size_t maxBytes = 128);
    // SET validators see values normalized to the bound types (including
    // float32 rounding). Keep validators pure; they must not mutate bindings.
    Group& validateWith(Validator validator);
    Group& onApplied(Applied callback);

    uint16_t id() const { return id_; }
    uint16_t schema() const { return schema_; }
    bool writable() const { return writable_; }
    bool persistent() const { return persistent_; }
    bool valid() const { return valid_; }
    size_t size() const { return bindings_.size(); }
    bool values(std::vector<Value>& output) const;
    bool validate(const std::vector<Value>& values) const;

private:
    friend class Engine;
    enum class BindingType { Float, Double, Int, Uint32, Bool, String };
    struct Binding {
        BindingType type;
        void* pointer;
        double minimum;
        double maximum;
        size_t maxBytes;
    };
    Group& append(BindingType type, void* pointer, double minimum,
                  double maximum, size_t maxBytes = 0);
    bool validateBindings(const std::vector<Value>& values) const;
    bool normalized(const std::vector<Value>& input, std::vector<Value>& output) const;
    bool assign(const std::vector<Value>& values);
    uint16_t id_, schema_;
    bool writable_, persistent_, valid_, sealed_;
    std::vector<Binding> bindings_;
    Validator validator_;
    Applied applied_;
};

// Store implementations must persist one whole group and return false on any
// uncertain/failed write. Engine independently reads back and verifies SAVE.
class Store {
public:
    virtual ~Store() {}
    virtual bool load(uint16_t group, uint16_t schema, Message& output,
                      std::string& error) = 0;
    virtual bool save(const Message& snapshot, std::string& error) = 0;
};

struct Response {
    bool reply;
    bool acceptedHello;
    bool acceptedControl;
    Message message;
    Response() : reply(false), acceptedHello(false), acceptedControl(false) {}
};

// Application actions return one nonempty UTF-8 code (at most 128 bytes).
// A callback owns validation and all action-specific safety/authorization checks.
struct ActionResult {
    bool success;
    std::string code;
};

class Engine {
public:
    typedef std::function<bool()> Guard;
    typedef std::function<void(const int*, size_t)> ControlHandler;
    typedef std::function<ActionResult(const std::vector<Value>&, uint32_t)> ActionHandler;
    typedef std::function<bool(uint16_t, const std::vector<Value>&)> BeforeSet;

    Engine();
    // A fresh, nonzero boot/session ID is required. Calling begin resets owner,
    // sequence/caches/control freshness, but keeps registered groups and hooks.
    bool begin(uint32_t fcSession);
    bool addGroup(Group& group);
    // Up to eight actions. IDs must be unique across groups/actions and may
    // not be 0 or 9. Configure before processing traffic. Actions deliberately
    // bypass onWriteAllowed(): the callback must enforce its own guards.
    bool addAction(uint16_t group, uint16_t schema, ActionHandler handler);
    Group* findGroup(uint16_t id) const;
    void setStore(Store* store) { store_ = store; }
    void onWriteAllowed(Guard guard) { writeAllowed_ = guard; }
    // Optional ownership cleanup guard. A disarmed calibration may forbid
    // settings writes while allowing a new monitoring client after disconnect.
    // Without this hook, the existing write/disarmed guard remains authoritative.
    void onOwnerReleaseAllowed(Guard guard) { ownerReleaseAllowed_ = guard; }
    // Optional durable application guard, after validation and before SET assignment.
    void onBeforeSet(BeforeSet guard) { beforeSet_ = guard; }
    void onControlEnabled(Guard guard) { controlEnabled_ = guard; }
    void onControl(ControlHandler handler) { controlHandler_ = handler; }

    // originalFrame preserves exact-byte retry identity when supplied by the
    // transport. With an empty argument, canonical encoding is used instead.
    Response handle(const Message& request, uint32_t now,
                    const std::string& originalFrame = std::string());
    bool snapshot(uint16_t group, Message& output);
    // Explicit local startup action: restore does not require an owner/write
    // guard. Call before arming/hardware initialization, never from a flight ISR.
    bool restore(Group& group, std::string* error = nullptr);
    // Application-owned atomic assignment for guarded ACTION handlers. Validates
    // and normalizes the entire group, then invokes its onApplied callback. This
    // does not write storage or run remote SET guards: the caller owns safety,
    // persistence and control-loop scheduling (never call from an ISR).
    bool applyLocal(uint16_t group, const std::vector<Value>& values);
    bool releaseOwner(); // Explicit local reset; requires the owner-release guard.
    // Opt in before ownership is acquired. Zero disables expiry for legacy use.
    // A live owner must send fresh PING/commands/CONTROL within this interval.
    bool setOwnerLease(uint32_t timeoutMs);
    uint32_t ownerLease() const { return ownerLeaseMs_; }
    // Poll from process(). Expiry always invalidates CONTROL immediately, but
    // only clears ownership once the owner-release guard permits it.
    bool expireOwner(uint32_t now);

    uint32_t ownerSession() const { return ownerSession_; }
    uint32_t fcSession() const { return fcSession_; }
    uint32_t lastControlAt() const { return lastControlAt_; }
    bool hasControl() const { return hasControl_; }
    bool controlFresh(uint32_t now, uint32_t timeoutMs) const;
    void invalidateControl() { hasControl_ = false; }

private:
    static bool newer(uint32_t candidate, uint32_t previous);
    static bool equalData(const std::vector<Value>& a, const std::vector<Value>& b);
    static bool equalMessage(const Message& a, const Message& b);
    static Response error(const Message& request, const char* code);
    static Response ack(const Message& request, const char* code);
    static Message replyMessage(const Message& request, Type type);
    bool allowed() const { return writeAllowed_ && writeAllowed_(); }
    bool ownerReleaseAllowed() const { return ownerReleaseAllowed_ ? ownerReleaseAllowed_() : allowed(); }
    Response command(const Message& request, uint32_t now);
    bool storedValues(Group& group, Message& output, std::string& error);
    void resetOwnerState();
    void retireOwner();
    bool retired(uint32_t session) const;
    struct Action {
        uint16_t id, schema;
        ActionHandler handler;
    };
    const Action* findAction(uint16_t id) const;
    std::vector<Group*> groups_;
    std::vector<Action> actions_;
    Store* store_;
    Guard writeAllowed_, controlEnabled_, ownerReleaseAllowed_;
    ControlHandler controlHandler_;
    BeforeSet beforeSet_;
    uint32_t fcSession_, ownerSession_, txSeq_, commandSeq_, controlSeq_, lastControlAt_;
    bool started_, hasCommand_, hasControlSequence_, hasControl_;
    uint32_t ownerLeaseMs_, lastOwnerAt_;
    bool ownerExpired_;
    // Bounded replay protection, reset on FC reboot. New connections must use
    // a fresh random session, never the ID of a released/expired connection.
    std::array<uint32_t, 8> retiredSessions_;
    size_t nextRetired_;
    std::string releasedRequest_;
    Response releasedResponse_;
    std::string cachedRequest_;
    Response cachedResponse_;
};

} // namespace areion
#endif
