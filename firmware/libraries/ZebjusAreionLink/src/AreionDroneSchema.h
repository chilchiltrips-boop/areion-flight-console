#pragma once
#include "AreionEngine.h"
namespace areion {
// IDs used by the bundled current flight main. Constants do not register data.
namespace DroneGroup {
constexpr uint16_t ARMING_SETTINGS = 4;
constexpr uint16_t FLIGHT_SETTINGS = 7;
constexpr uint16_t RECEIVER_TIMEOUTS = 112;
constexpr uint16_t CONTROL_OUTPUT = 23;
constexpr uint16_t DEVICE_INFO = 125;
constexpr uint16_t RATE_PID = 2;
constexpr uint16_t ANGLE_PID = 3;
constexpr uint16_t IMU_SETTINGS = 6;
constexpr uint16_t ACCEL_OFFSETS = IMU_SETTINGS; // Same section, schema2.
constexpr uint16_t CONTROL = 9;
constexpr uint16_t IMU = 21;
constexpr uint16_t RECEIVER = 22;
constexpr uint16_t INPUT_SOURCE = 110;
constexpr uint16_t STATUS = 120;
constexpr uint16_t TRANSPORT_STATUS = 121;
constexpr uint16_t INPUT_STATUS = 122;
constexpr uint16_t ACTION = 123;
constexpr uint16_t ARM_DISARM = ACTION;
constexpr uint16_t SETUP_STATUS = 130;
constexpr uint16_t RAW_PPM = 131;
constexpr uint16_t RX_CALIBRATION = 132;
constexpr uint16_t SETUP_CONFIG = 134;
constexpr uint16_t SETUP_ACTION = 135;
constexpr uint16_t PID_STATUS = 136;
constexpr uint16_t PID_APPLY = 137;
constexpr uint16_t AP_FIRMWARE_UPDATE = 140;
constexpr uint16_t FIRMWARE_COMPONENTS = 141;
}
namespace DroneSchema {
constexpr uint16_t IMU_SETTINGS = 2;
constexpr uint16_t ACCEL_OFFSETS = IMU_SETTINGS;
constexpr uint16_t INPUT_STATUS = 2;
constexpr uint16_t SETUP_STATUS = 1;
constexpr uint16_t RAW_PPM = 1;
constexpr uint16_t RX_CALIBRATION = 1;
constexpr uint16_t SETUP_CONFIG = 1;
constexpr uint16_t SETUP_ACTION = 1;
constexpr uint16_t PID_STATUS = 1;
constexpr uint16_t PID_APPLY = 1;
}
// Optional settings-only demonstration bank. For an existing flight main bind
// its actual PID/offset globals instead; this object does not configure hardware,
// select an input, arm motors or register telemetry/actions. This demonstration binds18PID/offset values; the main has additional settings.
// Offsets are additive g: corrected acceleration = raw /4096 + offset.
struct DroneSettings {
  float PRateRoll = 0.9f;
  float PRatePitch = 0.9f;
  float PRateYaw = 3.0f;
  float IRateRoll = 15.0f;
  float IRatePitch = 15.0f;
  float IRateYaw = 15.0f;
  float DRateRoll = 0.03f;
  float DRatePitch = 0.03f;
  float DRateYaw = 0.0f;
  float PAngleRoll = 3.0f;
  float PAnglePitch = 3.0f;
  float IAngleRoll = 0.0f;
  float IAnglePitch = 0.0f;
  float DAngleRoll = 0.0f;
  float DAnglePitch = 0.0f;
  float AccelOffsetX = -0.1f;
  float AccelOffsetY = 0.03f;
  float AccelOffsetZ = 0.12f;
  Group group2{DroneGroup::RATE_PID, 1, true, true};
  Group group3{DroneGroup::ANGLE_PID, 1, true, true};
  Group group6{DroneGroup::IMU_SETTINGS, DroneSchema::IMU_SETTINGS, true, true};
  DroneSettings() {
    group2.add(PRateRoll, 0.0, 100.0);
    group2.add(PRatePitch, 0.0, 100.0);
    group2.add(PRateYaw, 0.0, 100.0);
    group2.add(IRateRoll, 0.0, 500.0);
    group2.add(IRatePitch, 0.0, 500.0);
    group2.add(IRateYaw, 0.0, 500.0);
    group2.add(DRateRoll, 0.0, 20.0);
    group2.add(DRatePitch, 0.0, 20.0);
    group2.add(DRateYaw, 0.0, 20.0);
    group3.add(PAngleRoll, 0.0, 100.0);
    group3.add(PAnglePitch, 0.0, 100.0);
    group3.add(IAngleRoll, 0.0, 500.0);
    group3.add(IAnglePitch, 0.0, 500.0);
    group3.add(DAngleRoll, 0.0, 20.0);
    group3.add(DAnglePitch, 0.0, 20.0);
    group6.add(AccelOffsetX, -0.5, 0.5);
    group6.add(AccelOffsetY, -0.5, 0.5);
    group6.add(AccelOffsetZ, -0.5, 0.5);
  }
  DroneSettings(const DroneSettings&) = delete;
  DroneSettings& operator=(const DroneSettings&) = delete;
  bool attach(Engine& engine) {
    bool ok = true;
    ok = engine.addGroup(group2) && ok;
    ok = engine.addGroup(group3) && ok;
    ok = engine.addGroup(group6) && ok;
    return ok;
  }
};
}
