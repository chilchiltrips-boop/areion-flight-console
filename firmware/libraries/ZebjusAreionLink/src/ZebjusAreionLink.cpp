#include "ZebjusAreionLink.h"
#include <esp_random.h>
#include <algorithm>
#include <cstring>

bool ZebjusAreionLink::begin(uint32_t session) {
  if (begun_) return false;
  if (!session) { do { session = esp_random(); } while (!session); }
  engine_.begin(session); begun_ = true; return true;
}
bool ZebjusAreionLink::attachStream(Stream& stream) {
  for (auto& p : serial_) if (p.stream == &stream) return true;
  for (auto& p : serial_) if (!p.stream) { p.stream = &stream; return true; }
  return false;
}
bool ZebjusAreionLink::startUDP(uint16_t port) {
  if (!port) return false;
  if (udpReady_) return udpPort_ == port;
  if (!udp_.begin(port)) return false;
  udpReady_ = true; udpPort_ = port; return true;
}
bool ZebjusAreionLink::beginAP(const char* ssid, const char* password, uint16_t port) {
  if (!ssid || !password || !*ssid || strlen(password) < 8 || (udpReady_ && udpPort_ != port)) return false;
  if (!WiFi.mode(staStarted_ ? WIFI_AP_STA : WIFI_AP)) return false;
  if (!WiFi.softAP(ssid, password)) return false;
  apStarted_ = true; WiFi.setSleep(false); return startUDP(port);
}
bool ZebjusAreionLink::beginSTA(const char* ssid, const char* password, uint16_t port) {
  if (!ssid || !password || !*ssid || (udpReady_ && udpPort_ != port)) return false;
  if (!WiFi.mode(apStarted_ ? WIFI_AP_STA : WIFI_STA)) return false;
  WiFi.begin(ssid, password); staStarted_ = true; WiFi.setSleep(false);
  return startUDP(port); // association proceeds asynchronously; check staConnected()
}
int ZebjusAreionLink::peerIndex(IPAddress ip, uint16_t port) const {
  for (size_t i = 0; i < peers_.size(); ++i) if (peers_[i].active && peers_[i].ip == ip && peers_[i].port == port) return int(i);
  return -1;
}
bool ZebjusAreionLink::addPeer(IPAddress ip, uint16_t port) {
  if (peerIndex(ip, port) >= 0) return true;
  for (auto& p : peers_) if (!p.active) { p.active = true; p.ip = ip; p.port = port; return true; }
  return false;
}
void ZebjusAreionLink::directUDP(IPAddress ip, uint16_t port, const areion::Message& msg) {
  std::string frame;
  if (!areion::encodeFrame(msg, frame)) { ++rejected_; return; }
  if (!udp_.beginPacket(ip, port)) { ++dropped_; return; }
  bool written = udp_.write(reinterpret_cast<const uint8_t*>(frame.data()), frame.size()) == frame.size();
  bool ended = udp_.endPacket() == 1;
  if (!written || !ended) ++dropped_;
}
void ZebjusAreionLink::enqueue(std::deque<TxFrame>& queue, size_t offset, const std::string& frame, bool priority) {
  for (const auto& item : queue) if (item.bytes == frame) return;
  if (queue.size() >= 2) {
    bool removed = false;
    if (priority) {
      for (size_t i = queue.size(); i-- > 0;) {
        if (!queue[i].priority && !(i == 0 && offset != 0)) {
          queue.erase(queue.begin() + i); ++dropped_; removed = true; break;
        }
      }
    }
    if (!removed) { ++dropped_; return; }
  }
  TxFrame item{frame, priority};
  if (priority && (queue.empty() || offset == 0)) queue.push_front(item);
  else if (priority) queue.insert(queue.begin() + 1, item);
  else queue.push_back(item);
}
void ZebjusAreionLink::broadcast(const areion::Message& message) {
  std::string frame;
  if (!areion::encodeFrame(message, frame)) { ++rejected_; return; }
  // The exact same bytes/IDs are queued on every route. No received packet is forwarded.
  bool priority = message.type != areion::Type::Data || message.session == engine_.ownerSession();
  for (auto& p : serial_) if (p.stream) enqueue(p.queue, p.offset, frame, priority);
  for (auto& p : peers_) if (p.active) enqueue(p.queue, 0, frame, priority);
}
bool ZebjusAreionLink::sendGroup(uint16_t group) {
  if (privateGroup(group)) return false;
  if (begun_) { engine_.expireOwner(millis()); syncOwnerRoutes(); }
  if (!begun_ || !engine_.ownerSession()) return false;
  areion::Message msg;
  if (!engine_.snapshot(group, msg)) return false;
  std::string probe;
  if (!areion::encodeFrame(msg, probe)) { ++rejected_; return false; }
  broadcast(msg); return true;
}
void ZebjusAreionLink::drainTx() {
  for (auto& p : serial_) if (p.stream && !p.queue.empty()) {
    int room = p.stream->availableForWrite();
    if (room <= 0) continue;
    const std::string& frame = p.queue.front().bytes;
    size_t n = std::min(size_t(room), std::min(size_t(128), frame.size() - p.offset));
    size_t wrote = p.stream->write(reinterpret_cast<const uint8_t*>(frame.data() + p.offset), n);
    p.offset += std::min(n, wrote);
    if (p.offset == frame.size()) { p.queue.pop_front(); p.offset = 0; }
  }
  if (!udpReady_) return;
  // At most one UDP transmit per process call; round-robin prevents route starvation.
  for (size_t i = 0; i < peers_.size(); ++i) {
    size_t index = (nextPeer_ + i) % peers_.size(); auto& p = peers_[index];
    if (!p.active || p.queue.empty()) continue;
    const std::string& f = p.queue.front().bytes;
    bool ok = udp_.beginPacket(p.ip, p.port) == 1;
    if (ok) {
      bool written = udp_.write(reinterpret_cast<const uint8_t*>(f.data()), f.size()) == f.size();
      bool ended = udp_.endPacket() == 1; ok = written && ended;
    }
    if (!ok) ++dropped_;
    p.queue.pop_front(); nextPeer_ = uint8_t((index + 1) % peers_.size()); break;
  }
}
bool ZebjusAreionLink::releaseOwner() {
  if (!engine_.releaseOwner()) return false;
  syncOwnerRoutes();
  return true;
}
void ZebjusAreionLink::syncOwnerRoutes() {
  const uint32_t owner = engine_.ownerSession();
  if (routedOwner_ == owner) return;
  routedOwner_ = owner;
  for (auto& p : peers_) { p.active = false; p.queue.clear(); }
  for (auto& p : serial_) {
    // Finish an in-flight frame, then switch owner. Never splice a new frame into its bytes.
    if (p.offset && !p.queue.empty()) p.queue.erase(p.queue.begin() + 1, p.queue.end());
    else { p.queue.clear(); p.offset = 0; }
    p.decoder.reset();
  }
}
void ZebjusAreionLink::process() {
  if (!begun_) return;
  const uint32_t now = millis();
  // A stopped client must not reserve routes forever. The engine only releases
  // an expired owner while the application's write/disarmed guard permits it.
  engine_.expireOwner(now);
  syncOwnerRoutes();
  // Limit complete commands to two per call; bytes and packets also have fixed budgets.
  unsigned commands = 0;
  for (size_t i = 0; i < serial_.size() && commands < 1; ++i) {
    auto& p = serial_[(nextSerial_ + i) % serial_.size()];
    if (!p.stream) continue;
    if (uint32_t(now - p.lastByte) > 500) p.decoder.reset();
    unsigned budget = 256;
    while (budget-- && p.stream->available() > 0 && commands < 1) {
      int byte = p.stream->read(); if (byte < 0) break; p.lastByte = now;
      areion::Message msg;
      if (!p.decoder.feed(uint8_t(byte), msg)) continue;
      ++commands;
      // Rejected serial control does not consume its sequence, renew owner
      // activity, or disturb valid UDP control. An identical UDP packet may
      // still arrive and is then handled once by the common engine.
      if (msg.type == areion::Type::Control && !controlFromSerial_) {
        ++rejected_;
        continue;
      }
      const bool local = privateGroup(msg.group);
      if (local && p.stream != privateUsb_) { ++rejected_; continue; }
      auto response = engine_.handle(msg, now, p.decoder.lastFrame());
      syncOwnerRoutes();
      if (response.reply && local) {
        std::string frame;
        if (areion::encodeFrame(response.message, frame)) enqueue(p.queue, p.offset, frame, true);
      } else if (response.reply) broadcast(response.message);
    }
  }
  nextSerial_ = uint8_t((nextSerial_ + 1) % serial_.size());
  // Reserve the other command slot for UDP so continuous USB traffic cannot starve it.
  for (unsigned packets = 0; udpReady_ && packets < 2 && commands < 2; ++packets) {
    int n = udp_.parsePacket(); if (n <= 0) break;
    IPAddress ip = udp_.remoteIP(); uint16_t port = udp_.remotePort();
    if (size_t(n) > areion::MAX_FRAME) { udp_.clear(); ++rejected_; continue; }
    std::string frame(size_t(n), '\0');
    if (udp_.read(reinterpret_cast<uint8_t*>(&frame[0]), size_t(n)) != n) { ++rejected_; continue; }
    areion::Message msg;
    if (!areion::decodeFrame(frame, msg)) { ++rejected_; continue; }
    if (privateGroup(msg.group)) { ++rejected_; continue; }
    // RELEASE retries remain eligible after the releasing peer was removed.
    // The engine authenticates their session and exact-byte tombstone; a retry
    // never allocates a route or releases a newer owner.
    if (peerIndex(ip, port) < 0 && msg.type != areion::Type::Hello &&
        msg.type != areion::Type::Release) { ++rejected_; continue; }
    ++commands;
    // A selected serial receiver must not accept/renew from UDP CONTROL.
    // Route filters precede the shared sequence and owner activity updates.
    if (msg.type == areion::Type::Control && !controlFromUDP_) {
      ++rejected_;
      continue;
    }
    auto response = engine_.handle(msg, millis(), frame);
    syncOwnerRoutes();
    if (response.acceptedHello && !addPeer(ip, port)) {
      // A live owner keeps its existing routes. Evaluate ownership before
      // capacity so a full table from an expired owner cannot block reconnect.
      response.message.type = areion::Type::Error;
      response.message.data = {areion::Value::fromString("PEER_LIMIT")};
      ++rejected_;
    }
    if (response.reply) {
      if (peerIndex(ip, port) >= 0) broadcast(response.message);
      else {
        // The RELEASE reply must reach the departing UDP socket even though
        // route cleanup already ran. It is not re-learned as a telemetry peer.
        directUDP(ip, port, response.message);
        if (msg.type == areion::Type::Release &&
            response.message.type == areion::Type::Ack &&
            !engine_.ownerSession()) broadcast(response.message);
      }
    }
  }
  drainTx();
}
