/*
MIT License

Copyright (c) 2026 ZEBJUS LLP

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
// Zebjus PPM: independent PPM-SUM reader. Original implementation, MIT.
#pragma once
#define ZEBJUS_PPM_VERSION "1.0.1"
#include <Arduino.h>
#include <driver/rmt_rx.h>
#include <freertos/FreeRTOS.h>
namespace ppm_detail {
constexpr unsigned MAX_CHANNELS = 16;
struct Frame {
  uint16_t us[MAX_CHANNELS] = {};
  uint8_t count = 0;
  bool positivePulse = true;
};

}  // namespace ppm_detail

#if !defined(CONFIG_IDF_TARGET_ESP32C6)
#error "Zebjus PPM: unsupported board target."
#endif

class ZebjusPpm {
public:
  struct Config {
    uint8_t pin = 18;             // Zebjus PPM input: D10 / GPIO18
    uint8_t expectedChannels = 0; // Auto-detect 4..16; nonzero requires that count
    int edge = RISING;           // Measure rising-to-rising or falling-to-falling
    uint16_t syncIdleUs = 3000;   // Continuous idle level, not edge interval
    uint16_t lossTimeoutMs = 150;
  };
  struct Snapshot {
    ppm_detail::Frame frame;
    int64_t receivedAtUs = 0;     // RX-done callback time; diagnostic timestamp
    uint32_t validFrames = 0, invalidFrames = 0, captures = 0;
    uint32_t resyncDiscards = 0, receiveErrors = 0;
    uint32_t lastCallbackUs = 0, maxCallbackUs = 0;
    uint32_t lastSymbols = 0;
    uint32_t ageMs = UINT32_MAX;
    int32_t lastError = ESP_OK;
    bool running = false, fresh = false;
  };

  ZebjusPpm() = default;
  ZebjusPpm(const ZebjusPpm&) = delete;
  ZebjusPpm& operator=(const ZebjusPpm&) = delete;
  // Keep this object alive for the entire sketch (declare it globally).
  // Call begin/end from the Arduino loop task, never from an ISR.
  bool begin(const Config& config);
  void end();
  Snapshot snapshot(); // Atomically copies channels, timestamp and counters.

private:
  static bool IRAM_ATTR onReceive(rmt_channel_handle_t channel,
                                 const rmt_rx_done_event_data_t* event, void* context);
  bool IRAM_ATTR receiveDone(const rmt_rx_done_event_data_t* event);
  Config config_;
  Snapshot state_;
  portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;
  rmt_channel_handle_t channel_ = nullptr;
  rmt_symbol_word_t symbols_[48] = {};
  rmt_receive_config_t receiveConfig_ = {};
  bool enabled_ = false;
  volatile bool running_ = false;
  bool synchronized_ = false;
};

// PulsePosition-style interface for Zebjus PPM.
// Do not include the Teensy PulsePosition library alongside this header.
// Auto-detects frames; exposes at most eight channels for the example's float[8].
class PulsePositionInput {
public:
  explicit PulsePositionInput(int polarity = RISING);
  bool begin(uint8_t pin);
  int available();                 // Unread channel count, capped at 8; otherwise 0
  float read(uint8_t channel);     // 1-based; last exposed channel consumes frame
  ZebjusPpm::Snapshot diagnostics() { return reader_.snapshot(); }
  void end();
private:
  ZebjusPpm reader_;
  ZebjusPpm::Snapshot latched_;
  uint32_t lastSequence_ = 0;
  int polarity_;
  bool pending_ = false;
};
