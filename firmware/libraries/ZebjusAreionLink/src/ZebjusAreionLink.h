#pragma once
#include "AreionVersion.h"
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include "AreionEngine.h"
#include "AreionNvsStore.h"
#include <array>
#include <deque>

// One logical controller, up to two attached serial paths and two learned UDP paths.
// No built-in flight algorithm, input switching, motor output, or arming rules.
class ZebjusAreionLink {
 public:
  ZebjusAreionLink() = default;
  ZebjusAreionLink(const ZebjusAreionLink&) = delete;
  ZebjusAreionLink& operator=(const ZebjusAreionLink&) = delete;
  bool begin(uint32_t session = 0);
  bool attachStream(Stream& stream);
  bool beginAP(const char* ssid, const char* password, uint16_t port = 8080);
  bool beginSTA(const char* ssid, const char* password, uint16_t port = 8080);
  bool addGroup(areion::Group& group) { return engine_.addGroup(group); }
  areion::Engine& engine() { return engine_; }
  void process();
  void processPackets() { process(); } // Receiver-style spelling; same bounded processing.
  // False reserves CONTROL for learned UDP peers; serial settings/telemetry
  // remain enabled. Configure in setup. A policy change invalidates old control.
  void setControlFromSerial(bool allowed) {
    if (controlFromSerial_ != allowed) engine_.invalidateControl();
    controlFromSerial_ = allowed;
  }
  // False rejects UDP CONTROL before sequence/freshness/lease handling. HELLO,
  // settings, application ACTION and telemetry keep working on both routes.
  void setControlFromUDP(bool allowed) {
    if (controlFromUDP_ != allowed) engine_.invalidateControl();
    controlFromUDP_ = allowed;
  }
  bool sendGroup(uint16_t group);
  bool releaseOwner(); // explicit local action, only when write guard permits
  IPAddress apIP() const { return WiFi.softAPIP(); }
  IPAddress staIP() const { return WiFi.localIP(); }
  bool staConnected() const { return WiFi.status() == WL_CONNECTED; }
  uint32_t droppedFrames() const { return dropped_; }
  uint32_t rejectedFrames() const { return rejected_; }
 private:
  struct TxFrame { std::string bytes; bool priority; };
  struct SerialPath {
    Stream* stream = nullptr;
    areion::Decoder decoder;
    std::deque<TxFrame> queue;
    size_t offset = 0;
    uint32_t lastByte = 0;
  };
  struct UdpPath {
    bool active = false;
    IPAddress ip;
    uint16_t port = 0;
    std::deque<TxFrame> queue;
  };
  areion::Engine engine_;
  std::array<SerialPath, 2> serial_;
  std::array<UdpPath, 2> peers_;
  WiFiUDP udp_;
  bool begun_ = false, udpReady_ = false, apStarted_ = false, staStarted_ = false;
  bool controlFromSerial_ = true; // Backward-compatible default for USB/UART controls.
  bool controlFromUDP_ = true;
  uint16_t udpPort_ = 0;
  uint32_t dropped_ = 0, rejected_ = 0;
  uint32_t routedOwner_ = 0;
  uint8_t nextSerial_ = 0, nextPeer_ = 0;
  bool startUDP(uint16_t port);
  void syncOwnerRoutes();
  void broadcast(const areion::Message& message);
  void enqueue(std::deque<TxFrame>& queue, size_t offset, const std::string& frame, bool priority);
  void drainTx();
  bool addPeer(IPAddress ip, uint16_t port);
  int peerIndex(IPAddress ip, uint16_t port) const;
  void directUDP(IPAddress ip, uint16_t port, const areion::Message& message);
};
