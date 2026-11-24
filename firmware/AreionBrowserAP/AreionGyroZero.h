#pragma once
#include <cmath>
#include <cstdint>
#include <string>

// On-demand gyro bias is a boot-local estimate, just like startup calibration.
// Keep a candidate separate from the live bias until an independent hold verifies it.
struct AreionGyroZero {
  enum { Boot, Sampling, Verified, Failed, Cancelled };
  static constexpr int fitSamples = 500, totalSamples = 750;
  int state = Boot, samples = 0, target = totalSamples;
  uint32_t run = 0, owner = 0, last = 0, started = 0;
  std::string detail;
  float candidate[3] = {}, residual[3] = {}, referenceAcc[3] = {};
  float low[3] = {}, high[3] = {};

  bool busy() const { return state == Sampling; }
  void start(uint32_t session, uint32_t now) {
    owner = session; started = last = now; ++run;
    state = Sampling; samples = 0; detail.clear();
    for (int i = 0; i < 3; ++i) candidate[i] = residual[i] = 0;
  }
  void stop(int result, const char* reason) { state = result; owner = 0; detail = reason; }
  void cancel() { if (busy()) stop(Cancelled, "Cancelled"); }
  bool sample(uint32_t now, uint32_t session, bool healthy, const float rates[3],
              const float accel[3], const float previous[3]) {
    if (!busy()) return false;
    if (!owner || owner != session) { stop(Cancelled, "Connection changed"); return false; }
    const uint32_t gap = now - last;
    if (!healthy || gap > 100 || now - started > 10000) {
      stop(Failed, "IMU samples interrupted"); return false;
    }
    if (gap < 3) return false;
    last = now;
    float gravity2 = 0;
    for (int i = 0; i < 3; ++i) {
      if (!std::isfinite(rates[i]) || !std::isfinite(accel[i]) || !std::isfinite(previous[i])) {
        stop(Failed, "Invalid IMU reading"); return false;
      }
      gravity2 += accel[i] * accel[i];
      if (samples == 0) { low[i] = high[i] = rates[i]; referenceAcc[i] = accel[i]; }
      if (rates[i] < low[i]) low[i] = rates[i];
      if (rates[i] > high[i]) high[i] = rates[i];
      if (fabsf(rates[i] - previous[i]) > 5.f || high[i] - low[i] > 2.0f ||
          fabsf(accel[i] - referenceAcc[i]) > .075f) {
        stop(Failed, "Movement detected. Keep the frame still and retry."); return false;
      }
    }
    if (gravity2 < .65f*.65f || gravity2 > 1.4f*1.4f) {
      stop(Failed, "Rest the frame on a firm surface"); return false;
    }
    ++samples;
    for (int i = 0; i < 3; ++i) {
      if (samples <= fitSamples) candidate[i] += (rates[i] - candidate[i]) / samples;
      else residual[i] += (rates[i] - candidate[i] - residual[i]) / (samples - fitSamples);
    }
    if (samples < totalSamples) return false;
    for (float rate : residual) if (fabsf(rate) > .5f) {
      stop(Failed, "Gyro drift exceeded the verification limit"); return false;
    }
    stop(Verified, "Verified for this boot"); return true;
  }
};
