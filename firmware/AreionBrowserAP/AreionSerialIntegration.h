#pragma once
// Sketch-specific group bindings and input state. AP settings/object live in .ino.
// Requires the supplied ZebjusAreionLink v3.2.0 or a compatible v3 API.
// Flight math and hardware remain in the sketch.
#if !defined(ZEBJUS_AREION_LINK_API_LEVEL) || ZEBJUS_AREION_LINK_API_LEVEL < 30100
#error "Install the supplied ZebjusAreionLink 3.2.0 library; remove older duplicate installations."
#endif
#if !defined(ZEBJUS_AREION_LINK_VERSION_MAJOR) || ZEBJUS_AREION_LINK_VERSION_MAJOR != 3
#error "This Areion FC A1 sketch requires the matching ZebjusAreionLink v3 library."
#endif
#include <cmath>
#include <algorithm>
static_assert(D0==0 && D1==1 && D2==2 && D3==21 && D10==18 && D4==22 && D5==23,
  "Areion FC A1 board pin mapping mismatch. Select the correct ESP32-C6 board variant; do not change PCB pins.");
static_assert(pwmFreq==250 && pwmResolution==12 && minDuty==1024 && maxDuty==2048,
  "Areion FC A1 requires the fixed 250 Hz / 12-bit ESC configuration.");
void reset_pid(void);
static_assert(expectedArrayLength == 8, "CONTROL schema1 requires exactly8 channels");
static areion::NvsStore AreionStorage;
static areion::Group AreionRatePID(2,1,true,true), AreionAnglePID(3,1,true,true);
static areion::Group AreionAccelOffsets(6,2,true,true);
static areion::Group AreionArmingSettings(4,2,true,true), AreionFlightSettings(7,3,true,true);
static areion::Group AreionTimeoutSettings(112,1,true,true), AreionOutputs(23,2), AreionDevice(125,1);
static std::string AreionFirmwareVersion="3.2.0";
static int AreionTargetHz=250, AreionControlHz=50, AreionPpmPin=D10;
static int AreionMotorPins[4]={MOTOR_PINS[0],MOTOR_PINS[1],MOTOR_PINS[2],MOTOR_PINS[3]};
static int AreionPwmHz=pwmFreq, AreionPwmBits=pwmResolution;
static int AreionMinDuty=minDuty, AreionMaxDuty=maxDuty;
static areion::Group AreionIMU(21,1), AreionChannels(22,1), AreionStatus(120,1);
static areion::Group AreionTransportStatus(121,1), AreionSourceGroup(110,1,true,false);
static areion::Group AreionInputStatus(122,2);
static int AreionUDPPort=port;
static uint32_t AreionOwnerLeaseMs=5000;
static bool AreionAPReady=false;
static std::string AreionAPAddress="";
static int AreionReportCH[expectedArrayLength]={0};
static uint32_t AreionSampleMs=0;
static bool AreionStorageOK=false, AreionRateRestored=false, AreionAngleRestored=false;
static bool AreionLinkReady=false, AreionSetupComplete=false;
static bool AreionOffsetsRestored=false, AreionRebaseAttitude=false;
static uint32_t AreionImuSampleMs=0;
static std::string AreionRateRestoreError, AreionAngleRestoreError, AreionOffsetsRestoreError;

// One selection value makes simultaneous PPM/AP/USB activation impossible.
// Runtime selection is independent of the saved boot source in group134.
static int AreionInputSource=0; // 0=PPM, 1=AP, 2=USB
static int AreionActiveSource=0; // 0=NONE, 1=PPM, 2=AP, 3=USB
static bool AreionPPMFresh=false, AreionAPFresh=false, AreionUSBFresh=false, AreionInputReady=false;
static bool AreionInputNewFrame=false;
static int AreionInputChannelCount=0;
static uint32_t AreionInputAgeMs=UINT32_MAX, AreionOwnerSession=0;
static float AreionPPMValues[expectedArrayLength]={0};
static int AreionDigitalValues[expectedArrayLength]={0};
static bool AreionHasPPM=false, AreionHasDigital=false, AreionDiscardPPM=false;
static int AreionPPMCount=0;
static uint32_t AreionPPMAt=0, AreionDigitalAt=0, AreionDigitalSession=0;
static uint32_t AreionDigitalGeneration=0, AreionDigitalConsumedGeneration=0;
static int AreionDigitalSource=0;

static void areion_neutral_values() {
  for(int i=0;i<expectedArrayLength;++i) ReceiverValue[i]=1000;
  ReceiverValue[0]=ReceiverValue[1]=ReceiverValue[3]=1500;
  ChannelNumber=0;
}
static void areion_reset_gate() {
  Armed=false;
  HoldGesture=0; HoldStart=millis(); GestureConsumed=false;
  LastThrottleMovement=1000; ThrottleMovementTimer=millis();
  AreionInputReady=false; AreionInputNewFrame=false; AreionActiveSource=0;
  AreionInputChannelCount=0; AreionInputAgeMs=UINT32_MAX;
  areion_neutral_values();
  MotorInput1=MotorInput2=MotorInput3=MotorInput4=1000;
  reset_pid();
}
static void areion_reset_input(bool sourceChange=false) {
  areion_reset_gate();
  AreionHasDigital=false; AreionAPFresh=false; AreionUSBFresh=false; AreionDigitalSession=0;
  AreionDigitalSource=0;
  AreionDigitalConsumedGeneration=AreionDigitalGeneration;
  receiver.engine().invalidateControl();
  if(sourceChange && AreionInputSource==0) AreionDiscardPPM=true;
}
static bool areion_setup_cancel(const char* why);
static bool areion_motor_safe_stop() {
  const bool cancelled=areion_setup_cancel("DISARM_OR_SENSOR_STOP");
  areion_reset_input();
  for(int i=0;i<4;++i) ledcWrite(MOTOR_PINS[i],minDuty);
  return cancelled;
}
static bool areion_neutral_frame(const float* values) {
  return values[2]<ThrottleLow && values[0]>=1400 && values[0]<=1600
    && values[1]>=1400 && values[1]<=1600 && values[3]>=1400 && values[3]<=1600;
}
static bool areion_digital_fresh(uint32_t now) {
  return (AreionInputSource==1 || AreionInputSource==2)
    && AreionDigitalSource==AreionInputSource && AreionHasDigital
    && AreionDigitalSession!=0 && AreionDigitalSession==receiver.engine().ownerSession()
    && receiver.engine().controlFresh(now,DigitalTimeoutMs)
    && uint32_t(now-AreionDigitalAt)<DigitalTimeoutMs
    && uint32_t(now-receiver.engine().lastControlAt())<DigitalTimeoutMs;
}
static bool areion_imu_ready(uint32_t now) {
  if(!AreionSetupComplete || !ImuReadOK || ValidCalibrationSamples<=0
     || AreionRebaseAttitude || uint32_t(now-AreionImuSampleMs)>=inputTimeoutMs) return false;
  const float values[]={RateRoll,RatePitch,RateYaw,RateCalibrationRoll,
    RateCalibrationPitch,RateCalibrationYaw,AccX,AccY,AccZ,AngleRoll,AnglePitch,
    KalmanAngleRoll,KalmanAnglePitch,KalmanUncertaintyAngleRoll,
    KalmanUncertaintyAnglePitch,AccOffsetX,AccOffsetY,AccOffsetZ,LoopDt};
  for(float value:values) if(!std::isfinite(value)) return false;
  return LoopDt>0;
}
static void areion_offsets_applied() {
  // Gyro bias calibration is independent of these additive accelerometer offsets.
  // Rebase attitude only after the next complete successful sensor read.
  ImuReadOK=false; AreionRebaseAttitude=true;
  areion_reset_input();
}
#include "AreionSetupLifecycle.h"

static areion::ActionResult areion_arm_action(const std::vector<areion::Value>& data,uint32_t now) {
  if(data.size()!=1 || data[0].type!=areion::ValueType::String) return {false,"ACTION_DATA"};
  if(data[0].text=="DISARM") {
    // Deliberately independent of throttle, source and input freshness. The
    // engine has already checked the owner/session and command sequence.
    if(!areion_motor_safe_stop()) return {false,"ESC_CANCEL_NOT_PERSISTED"};
    return {true,"DISARMED"};
  }
  if(data[0].text!="ARM") return {false,"ACTION_UNKNOWN"};
  if(AreionPidPending) return {false,"PID_SAVE_PENDING"};
  if(AreionSetupLocked || !AreionWizardComplete) return {false,"SETUP_LOCKED"};
  if(AreionInputSource!=1 && AreionInputSource!=2) return {false,"INPUT_SOURCE"};
  if(FlightModeChannel<5) return {false,"SETUP_INPUT_NOT_VERIFIED"};
  if(!AreionLinkReady || (AreionInputSource==1 && !AreionAPReady)) return {false,"TRANSPORT_NOT_READY"};
  if(!AreionSetupComplete) return {false,"FC_NOT_READY"};
  if(!areion_digital_fresh(now)) return {false,"DIGITAL_STALE"};
  if(!AreionInputReady) return {false,"INPUT_NOT_READY"};
  float latest[expectedArrayLength];
  for(int i=0;i<expectedArrayLength;++i) latest[i]=AreionDigitalValues[i];
  // A CONTROL can arrive immediately before ACTION, before read_receiver runs.
  // Check that latest raw frame, never the preceding ReceiverValue snapshot.
  if(!areion_neutral_frame(latest)) return {false,"NOT_NEUTRAL"};
  if(!areion_imu_ready(now)) return {false,"IMU_NOT_READY"};
  if(!Armed) {
    reset_pid();
    HoldGesture=0; HoldStart=now; GestureConsumed=false;
    LastThrottleMovement=latest[2]; ThrottleMovementTimer=now;
    Armed=true;
  }
  return {true,"ARMED"};
}

static bool areion_restore_flight_settings() {
  if(receiver.engine().restore(AreionFlightSettings)) return true;
  // Preserve validated channel/sensitivity settings saved by v2.4.x. Extend
  // them in RAM; explicit SAVE commits schema3, without automatic flash writes.
  areion::Message legacy; std::string error;
  if(!AreionStorage.load(7,2,legacy,error) || legacy.data.size()!=4) return false;
  auto values=legacy.data;
  values.push_back(areion::Value::fromInt(0));
  values.push_back(areion::Value::fromInt(1));
  if(!AreionFlightSettings.validate(values)) return false;
  auto number=[](const areion::Value& value) {
    return float(value.type==areion::ValueType::Integer ? double(value.integer) : value.real);
  };
  FlightModeChannel=int(values[0].integer);
  AngleStickScale=number(values[1]); RateStickScale=number(values[2]); YawStickScale=number(values[3]);
  FlightModeLow=0; FlightModeHigh=1;
  ModeChanged=true; areion_reset_input();
  return true;
}

static bool areion_link_begin(bool transportReady) {
  static bool started=false;
  if(started) return AreionLinkReady;
  started=true;
  AreionRatePID.add(PRateRoll,0,100).add(PRatePitch,0,100).add(PRateYaw,0,100)
    .add(IRateRoll,0,500).add(IRatePitch,0,500).add(IRateYaw,0,500)
    .add(DRateRoll,0,20).add(DRatePitch,0,20).add(DRateYaw,0,20);
  AreionAnglePID.add(PAngleRoll,0,100).add(PAnglePitch,0,100)
    .add(IAngleRoll,0,500).add(IAnglePitch,0,500)
    .add(DAngleRoll,0,20).add(DAnglePitch,0,20);
  AreionRatePID.onApplied(reset_pid); AreionAnglePID.onApplied(reset_pid);
  AreionAccelOffsets.add(AccOffsetX,-0.5,0.5).add(AccOffsetY,-0.5,0.5)
    .add(AccOffsetZ,-0.5,0.5).onApplied(areion_offsets_applied);
  AreionArmingSettings.add(ThrottleLow,1001,1200).add(YawRight,1700,2000)
    .add(YawLeft,1000,1300).add(ThrottleMovement,1,200)
    .add(ArmHoldTime,1,15).add(DisarmHoldTime,1,10).add(AutoDisarmTime,1,300)
    .onApplied([] { areion_reset_input(); });
  AreionFlightSettings.add(FlightModeChannel,1,8).add(AngleStickScale,0.01,0.3)
    .add(RateStickScale,0.01,1.0).add(YawStickScale,0.01,1.0)
    .add(FlightModeLow,0,1).add(FlightModeHigh,0,1)
    .validateWith([](const std::vector<areion::Value>& values) {
      return values[4].integer!=values[5].integer
        && (values[0].integer>=5 || (AreionBootSource==0 && AreionInputSource==0));
    })
    .onApplied([] { ModeChanged=true; areion_reset_input(); });
  AreionTimeoutSettings.add(PpmTimeoutMs,50,1000).add(DigitalTimeoutMs,100,500)
    .onApplied([] { areion_reset_input(); });
  AreionOutputs.add(InputRoll).add(InputPitch).add(InputYaw)
    .add(MotorInput1).add(MotorInput2).add(MotorInput3).add(MotorInput4)
    .add(DesiredRateRoll).add(DesiredRatePitch).add(DesiredRateYaw)
    .add(DesiredAngleRoll).add(DesiredAnglePitch);
  AreionDevice.add(AreionFirmwareVersion,24).add(AreionTargetHz).add(AreionPpmPin);
  for(int i=0;i<4;++i) AreionDevice.add(AreionMotorPins[i]);
  AreionDevice.add(AreionPwmHz).add(AreionPwmBits).add(AreionMinDuty).add(AreionMaxDuty).add(AreionControlHz);
  AreionIMU.add(RateRoll).add(RatePitch).add(RateYaw)
    .add(AccX).add(AccY).add(AccZ).add(AngleRoll).add(AnglePitch)
    .add(KalmanAngleRoll).add(KalmanAnglePitch);
  for(int i=0;i<expectedArrayLength;++i) AreionChannels.add(AreionReportCH[i]);
  AreionStatus.add(Armed).add(AngleMode).add(ImuReadOK).add(ChannelNumber)
    .add(LoopDt).add(ValidCalibrationSamples).add(AreionSampleMs)
    .add(AreionStorageOK).add(AreionRateRestored).add(AreionAngleRestored);
  if(AreionAPReady) AreionAPAddress=receiver.apIP().toString().c_str();
  AreionTransportStatus.add(AreionAPReady).add(AreionAPAddress,45)
    .add(AreionUDPPort,1,65535).add(AreionOwnerLeaseMs);
  AreionSourceGroup.add(AreionInputSource,0,2).validateWith([](const std::vector<areion::Value>& values) {
    const int source=int(values[0].integer);
    if(source!=0) return FlightModeChannel>=5;
    // Runtime source switching cannot bypass receiver calibration/neutral checks
    // of a setup that was completed for digital-only input.
    return AreionSetupLocked || (AreionBootSource==0 && AreionReceiverVerified);
  }).onApplied([] {
    receiver.setControlFromSerial(AreionInputSource==2);
    receiver.setControlFromUDP(AreionInputSource==1);
    areion_reset_input(true);
  });
  AreionInputStatus.add(AreionInputSource).add(AreionActiveSource)
    .add(AreionPPMFresh).add(AreionAPFresh).add(AreionInputReady)
    .add(AreionInputChannelCount).add(AreionInputAgeMs).add(AreionOwnerSession)
    .add(AreionUSBFresh);
  AreionLinkReady=transportReady && receiver.addGroup(AreionRatePID)
    && receiver.addGroup(AreionAnglePID) && receiver.addGroup(AreionIMU)
    && receiver.addGroup(AreionChannels) && receiver.addGroup(AreionStatus)
    && receiver.addGroup(AreionTransportStatus) && receiver.addGroup(AreionSourceGroup)
    && receiver.addGroup(AreionInputStatus) && receiver.addGroup(AreionAccelOffsets)
    && receiver.addGroup(AreionArmingSettings) && receiver.addGroup(AreionFlightSettings)
    && receiver.addGroup(AreionTimeoutSettings) && receiver.addGroup(AreionOutputs)
    && receiver.addGroup(AreionDevice) && receiver.engine().addAction(123,1,areion_arm_action)
    && areion_setup_bind();
  receiver.engine().onWriteAllowed([] { return !Armed && !AreionPidPending && !AreionMotorTestActive && AreionEscState!=1 && AreionEscState!=2 && !AreionEscBootMode && AreionSetupStoreHealthy; });
  // ESC timing is autonomous and all flight ARM paths remain locked. Allow
  // reconnect/read/STOP even when calibration or storage health forbids writes.
  receiver.engine().onOwnerReleaseAllowed([] { return !Armed && !AreionMotorTestActive; });
  receiver.engine().onControlEnabled([] {
    return AreionLinkReady && (AreionInputSource==2 || (AreionInputSource==1 && AreionAPReady));
  });
  receiver.engine().onControl([] (const int* values,size_t count) {
    if(count!=expectedArrayLength) return;
    // Owner handoff can occur between two loop reads. The first CONTROL from
    // a new owner must pass the neutral gate even if no empty interval was seen.
    if(AreionDigitalSource!=AreionInputSource || AreionDigitalSession!=receiver.engine().ownerSession()
       || (AreionHasDigital && uint32_t(millis()-AreionDigitalAt)>=DigitalTimeoutMs)) areion_reset_gate();
    for(int i=0;i<expectedArrayLength;++i) AreionDigitalValues[i]=values[i];
    AreionDigitalSession=receiver.engine().ownerSession();
    AreionDigitalSource=AreionInputSource;
    AreionDigitalAt=millis();
    AreionHasDigital=true; ++AreionDigitalGeneration;
  });
  if(AreionLinkReady) AreionLinkReady=receiver.engine().setOwnerLease(AreionOwnerLeaseMs);
  if(AreionLinkReady) AreionLinkReady=areion_factory_capture();
  AreionStorageOK=AreionStorage.begin();
  if(AreionLinkReady && AreionStorageOK) {
    receiver.engine().setStore(&AreionStorage);
    AreionRateRestored=receiver.engine().restore(AreionRatePID,&AreionRateRestoreError);
    AreionAngleRestored=receiver.engine().restore(AreionAnglePID,&AreionAngleRestoreError);
    AreionOffsetsRestored=receiver.engine().restore(AreionAccelOffsets,&AreionOffsetsRestoreError);
    receiver.engine().restore(AreionArmingSettings);
    areion_restore_flight_settings();
    receiver.engine().restore(AreionTimeoutSettings);
  }
  areion_setup_boot();
  areion_reset_input();
  return AreionLinkReady;
}

static void areion_read_receiver() {
  const uint32_t now=millis();
  AreionInputNewFrame=false;
  bool ppmNew=false;
  const int count=ReceiverInput.available();
  const bool ppmSignalFresh=ReceiverInput.diagnostics().fresh;
  if(count>0) {
    // Validate the complete frame before copying any values or using it to arm.
    bool valid=count>=4 && count<=expectedArrayLength && ppmSignalFresh;
    float candidate[expectedArrayLength];
    for(int i=0;i<expectedArrayLength;++i) candidate[i]=(i==0 || i==1 || i==3)?1500:1000;
    if(valid) for(int i=0;i<count;++i) {
      candidate[i]=ReceiverInput.read(i+1);
      if(!std::isfinite(candidate[i]) || candidate[i]<900 || candidate[i]>2100) valid=false;
    }
    if(AreionDiscardPPM) { AreionDiscardPPM=false; valid=false; }
    const bool hadGap=AreionHasPPM && uint32_t(now-AreionPPMAt)>=PpmTimeoutMs;
    AreionHasPPM=valid;
    if(valid) {
      // Catch a timeout even if a fresh frame arrived during a delayed loop.
      // Its timestamp must not hide the preceding loss and preserve arming.
      if(AreionInputSource==0 && hadGap) areion_reset_gate();
      for(int i=0;i<expectedArrayLength;++i) AreionPPMValues[i]=candidate[i];
      AreionPPMCount=count; AreionPPMAt=now; ppmNew=true;
    }
  } else if(AreionDiscardPPM) {
    // No pending frame to discard; the next arriving frame is after selection.
    AreionDiscardPPM=false;
    AreionHasPPM=false;
  }
  if(!ppmSignalFresh) AreionHasPPM=false;
  AreionPPMFresh=AreionHasPPM && uint32_t(now-AreionPPMAt)<PpmTimeoutMs;
  if(!AreionPPMFresh) AreionHasPPM=false;
  areion_setup_raw_update();
  AreionOwnerSession=receiver.engine().ownerSession();
  const bool digitalFresh=areion_digital_fresh(now);
  AreionAPFresh=digitalFresh && AreionDigitalSource==1;
  AreionUSBFresh=digitalFresh && AreionDigitalSource==2;
  bool fresh=AreionInputSource==0?AreionPPMFresh:digitalFresh;
  if(AreionInputSource==0) {
    for(int i=0;i<4;++i) if(AreionAxisChannels[i]>AreionPPMCount) fresh=false;
    if(FlightModeChannel>AreionPPMCount) fresh=false;
  }
  if(!fresh) {
    areion_reset_input();
    return;
  }
  float candidate[expectedArrayLength];
  bool newFrame=false;
  if(AreionInputSource==0) {
    areion_setup_ppm_normalize(candidate);
    AreionInputChannelCount=AreionPPMCount; AreionInputAgeMs=now-AreionPPMAt;
    newFrame=ppmNew;
  } else {
    for(int i=0;i<expectedArrayLength;++i) candidate[i]=AreionDigitalValues[i];
    AreionInputChannelCount=expectedArrayLength;
    AreionInputAgeMs=now-receiver.engine().lastControlAt();
    newFrame=AreionDigitalGeneration!=AreionDigitalConsumedGeneration;
    AreionDigitalConsumedGeneration=AreionDigitalGeneration;
  }
  // A fresh neutral frame is mandatory after boot, source selection or loss.
  // An arming gesture already held during reconnection cannot arm immediately.
  if(!AreionInputReady && newFrame && areion_neutral_frame(candidate)) AreionInputReady=true;
  if(!AreionInputReady) {
    Armed=false; HoldGesture=0; HoldStart=now; GestureConsumed=false;
    areion_neutral_values();
    return;
  }
  for(int i=0;i<expectedArrayLength;++i) ReceiverValue[i]=candidate[i];
  ChannelNumber=AreionInputChannelCount;
  AreionActiveSource=AreionInputSource==0?1:(AreionInputSource==1?2:3);
  AreionInputNewFrame=newFrame;
}

static void areion_serial_publish() {
  static uint32_t lastPublish=0,lastSetupPublish=0,lastRawPublish=0;
  static uint8_t section=0;
  if(!AreionLinkReady) return;
  const uint32_t now=millis();
  if(uint32_t(now-lastSetupPublish)>=100) {receiver.sendGroup(130);receiver.sendGroup(136);lastSetupPublish=now;}
  if(AreionSetupLocked && uint32_t(now-lastRawPublish)>=50) {receiver.sendGroup(131);lastRawPublish=now;}
  if(uint32_t(now-lastPublish)<25) return;
  lastPublish=now; AreionSampleMs=now;
  AreionOwnerSession=receiver.engine().ownerSession();
  for(int i=0;i<expectedArrayLength;++i) {
    const float value=ReceiverValue[i];
    AreionReportCH[i]=std::isfinite(value) && value>=0 && value<=65535?int(value):-1;
  }
  // 25ms slots: IMU ~13Hz, status/input/channels/output ~6.7Hz. Best effort.
  if(section==0) receiver.sendGroup(120);
  else if(section==1) receiver.sendGroup(122);
  else if(section==3) receiver.sendGroup(22);
  else if(section==5) receiver.sendGroup(23);
  else if(ImuReadOK && ValidCalibrationSamples>0) receiver.sendGroup(21);
  section=uint8_t((section+1)%6);
}
