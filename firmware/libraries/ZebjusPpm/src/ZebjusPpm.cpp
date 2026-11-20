#include "ZebjusPpm.h"
#include <driver/gpio.h>
#include <esp_timer.h>

namespace ppm_detail {
// Durations are microseconds (RMT resolution must be 1 MHz).
// One short separator at the start of each channel, plus a final separator.
// A frame with N channels therefore needs N+1 separator pulses.
template<class Symbol>
inline IRAM_ATTR bool decode(const Symbol* symbols, size_t count, uint8_t expected,
                       uint16_t idleUs, Frame& output, int edge = RISING) {
  if (!symbols || count < 5 || count > 48 || expected > MAX_CHANNELS) return false;
  for (unsigned active = 0; active != 2; ++active) {
    Frame candidate;
    uint32_t elapsed = 0, previous = 0;
    unsigned markers = 0;
    bool bad = false, ended = false;
    for (size_t n = 0; n < count && !bad; ++n) {
      for (unsigned half = 0; half != 2; ++half) {
        const uint32_t duration = half ? symbols[n].duration1 : symbols[n].duration0;
        const unsigned level = half ? symbols[n].level1 : symbols[n].level0;
        if (!duration) {
          // Zero is the RMT end marker, not an extra channel.
          ended = true;
          continue;
        }
        if (ended) { bad = true; break; }
        if (level == active) {
          if (duration < 80 || duration > 650 || markers >= MAX_CHANNELS + 1) {
            bad = true; break;
          }
          // RISING/FALLING select an actual transition, not separator polarity.
          const bool trailingEdge = (edge == RISING && active == 0) ||
                                    (edge == FALLING && active == 1);
          const uint32_t edgeAt = elapsed + (trailingEdge ? duration : 0);
          if (markers) {
            const uint32_t width = edgeAt - previous;
            if (width < 750 || width > 2250) { bad = true; break; }
            candidate.us[markers - 1] = uint16_t(width);
          }
          previous = edgeAt;
          ++markers;
        } else {
          // Reject a capture starting halfway through a channel. A leading
          // full sync idle is harmless; internal sync gaps are not channels.
          if (!markers && duration < idleUs) { bad = true; break; }
          if (duration >= idleUs && markers) ended = true;
        }
        elapsed += duration;
      }
    }
    if (!bad && markers >= 5 && markers <= MAX_CHANNELS + 1) {
      const uint8_t channels = uint8_t(markers - 1);
      if (expected && channels != expected) continue;
      candidate.count = channels;
      candidate.positivePulse = active == 1;
      output = candidate;
      return true;
    }
  }
  return false;
}
}  // namespace ppm_detail


bool ZebjusPpm::begin(const Config& config) {
  if (channel_) return false; // Call end() before reconfiguration.
  state_ = Snapshot{};
  if (!GPIO_IS_VALID_GPIO(config.pin) ||
      (config.edge != RISING && config.edge != FALLING) ||
      (config.expectedChannels && (config.expectedChannels < 4 || config.expectedChannels > 16)) ||
      config.syncIdleUs < 2500 || config.syncIdleUs > 10000 ||
      config.lossTimeoutMs < 50 || config.lossTimeoutMs > 2000) {
    state_.lastError = ESP_ERR_INVALID_ARG;
    return false;
  }
  config_ = config;
  synchronized_ = false;
  pinMode(config_.pin, INPUT_PULLDOWN);
  rmt_rx_channel_config_t channelConfig = {};
  channelConfig.gpio_num = gpio_num_t(config_.pin);
  channelConfig.clk_src = RMT_CLK_SRC_DEFAULT;
  channelConfig.resolution_hz = 1000000;
  channelConfig.mem_block_symbols = 48;
  // 1 us hardware glitch filter; filter clock differs from channel clock.
  receiveConfig_ = {};
  receiveConfig_.signal_range_min_ns = 1000;
  receiveConfig_.signal_range_max_ns = uint32_t(config_.syncIdleUs) * 1000;
  esp_err_t error = rmt_new_rx_channel(&channelConfig, &channel_);
  if (error == ESP_OK) {
    rmt_rx_event_callbacks_t callbacks = {};
    callbacks.on_recv_done = &ZebjusPpm::onReceive;
    error = rmt_rx_register_event_callbacks(channel_, &callbacks, this);
  }
  if (error == ESP_OK) {
    error = rmt_enable(channel_);
    enabled_ = error == ESP_OK;
  }
  if (error == ESP_OK) {
    running_ = true;
    error = rmt_receive(channel_, symbols_, sizeof(symbols_), &receiveConfig_);
  }
  if (error != ESP_OK) {
    running_ = false;
    state_.lastError = error;
    ++state_.receiveErrors;
    end();
    return false;
  }
  return true;
}

void ZebjusPpm::end() {
  running_ = false;
  if (channel_) {
    if (enabled_) rmt_disable(channel_);
    rmt_del_channel(channel_);
    channel_ = nullptr;
  }
  enabled_ = false;
}

ZebjusPpm::Snapshot ZebjusPpm::snapshot() {
  portENTER_CRITICAL(&mux_);
  Snapshot copy = state_;
  copy.running = running_;
  portEXIT_CRITICAL(&mux_);
  const int64_t now = esp_timer_get_time();
  if (copy.validFrames) {
    const uint64_t age = uint64_t(now - copy.receivedAtUs) / 1000;
    copy.ageMs = age > UINT32_MAX ? UINT32_MAX : uint32_t(age);
    copy.fresh = copy.running && age <= config_.lossTimeoutMs;
  }
  return copy;
}

bool IRAM_ATTR ZebjusPpm::onReceive(rmt_channel_handle_t,
                                      const rmt_rx_done_event_data_t* event, void* context) {
  return static_cast<ZebjusPpm*>(context)->receiveDone(event);
}

bool IRAM_ATTR ZebjusPpm::receiveDone(const rmt_rx_done_event_data_t* event) {
  if (!running_) return false;
  const int64_t callbackAt = esp_timer_get_time();
  ppm_detail::Frame decoded;
  // Discard the first capture: begin() can occur halfway through a PPM frame.
  // Buffer-full packets are not proof of an idle delimiter, so resynchronize.
  const bool terminated = event->num_symbols > 0 && event->num_symbols < 48;
  const bool eligible = synchronized_ && terminated;
  const bool good = eligible && ppm_detail::decode(event->received_symbols,
      event->num_symbols, config_.expectedChannels, config_.syncIdleUs, decoded, config_.edge);
  synchronized_ = terminated;

  portENTER_CRITICAL_ISR(&mux_);
  ++state_.captures;
  state_.lastSymbols = event->num_symbols;
  if (!eligible) ++state_.resyncDiscards;
  else if (good) {
    state_.frame = decoded;
    state_.receivedAtUs = callbackAt;
    ++state_.validFrames;
  } else if (event->num_symbols > 1) ++state_.invalidFrames;
  portEXIT_CRITICAL_ISR(&mux_);

  // Parsing is complete before this same buffer is reused. No Serial, heap
  // allocation or network operations in the callback. RMT must be rearmed.
  const esp_err_t error = rmt_receive(channel_, symbols_, sizeof(symbols_), &receiveConfig_);
  const uint32_t spent = uint32_t(esp_timer_get_time() - callbackAt);
  portENTER_CRITICAL_ISR(&mux_);
  state_.lastCallbackUs = spent;
  if (spent > state_.maxCallbackUs) state_.maxCallbackUs = spent;
  if (error != ESP_OK) {
    ++state_.receiveErrors;
    state_.lastError = error;
    running_ = false; // Report error to Serial; do not abort/reboot here.
  }
  portEXIT_CRITICAL_ISR(&mux_);
  return false; // No higher-priority task was woken by this callback.
}

PulsePositionInput::PulsePositionInput(int polarity) : polarity_(polarity) {}

bool PulsePositionInput::begin(uint8_t pin) {
  ZebjusPpm::Config config;
  config.pin = pin;
  config.expectedChannels = 0;
  config.edge = polarity_;
  const bool ok = reader_.begin(config);
  if (ok) { latched_ = {}; lastSequence_ = 0; pending_ = false; }
  return ok;
}

int PulsePositionInput::available() {
  const auto latest = reader_.snapshot();
  if (!latest.fresh) {
    pending_ = false;
    return 0;
  }
  // Preserve a single frame across all read() calls, even if an ISR
  // captures a newer packet between them. Expire an abandoned snapshot.
  if (pending_ && esp_timer_get_time() - latched_.receivedAtUs > 150000) pending_ = false;
  if (!pending_) {
    if (latest.validFrames == lastSequence_) return 0;
    latched_ = latest;
    lastSequence_ = latest.validFrames;
    pending_ = true;
  }
  return latched_.frame.count > 8 ? 8 : latched_.frame.count;
}

float PulsePositionInput::read(uint8_t channel) {
  const uint8_t exposed = latched_.frame.count > 8 ? 8 : latched_.frame.count;
  if (!pending_ || !channel || channel > exposed) return 0.0f;
  if (esp_timer_get_time() - latched_.receivedAtUs > 150000) {
    pending_ = false;
    return 0.0f;
  }
  const float value = float(latched_.frame.us[channel - 1]);
  if (channel == exposed) pending_ = false;
  return value;
}

void PulsePositionInput::end() {
  reader_.end(); pending_ = false; lastSequence_ = 0; latched_ = {};
}
