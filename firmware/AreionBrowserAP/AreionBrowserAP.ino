#include <ZebjusPpm.h>
#include <Wire.h>
#include <math.h>
#include <ZebjusAreionLink.h>
#include "AreionWebGateway.h"
#include "AreionWifiConfig.h"

float RateRoll, RatePitch, RateYaw;
float RateCalibrationRoll, RateCalibrationPitch, RateCalibrationYaw;
float AccX, AccY, AccZ, AngleRoll, AnglePitch;
// Additive accelerometer corrections in g; group6/schema2 can read/apply/save these.
float AccOffsetX=-0.10f, AccOffsetY=+0.03f, AccOffsetZ=+0.12f;
int RateCalibrationNumber, ValidCalibrationSamples = 0;
uint32_t LoopTimer, SerialTimer = 0, PreviousLoopTime;
float LoopDt = 0.004f;
bool ImuReadOK = false;

// === Receiver + USB/AP communication ===

const int port = 8080;
const int expectedArrayLength = 8; // CONTROL schema1: CH1..CH8
const uint32_t inputTimeoutMs = 250; // IMU freshness remains fixed.
uint32_t PpmTimeoutMs=250, DigitalTimeoutMs=250; // group112; disarmed apply/save
ZebjusAreionLink receiver;
PulsePositionInput ReceiverInput(RISING);
float ReceiverValue[expectedArrayLength] = {1500,1500,1000,1500,1000,1000,1000,1000};
int ChannelNumber = 0;

const int MOTOR_PINS[4] = {D0, D1, D2, D3};
const int pwmFreq = 250, pwmResolution = 12, minDuty = 1024, maxDuty = 2048;

// === Motors ===
float MotorInput1=1000, MotorInput2=1000, MotorInput3=1000, MotorInput4=1000;

// === 1D Kalman (Roll/Pitch) ===
float KalmanAngleRoll=0, KalmanUncertaintyAngleRoll=4;
float KalmanAnglePitch=0, KalmanUncertaintyAnglePitch=4;
float Kalman1DOutput[]={0,0};

// === Arm / Disarm ===
bool Armed=false, GestureConsumed=false;
uint8_t HoldGesture=0;
uint32_t HoldStart=0, ThrottleMovementTimer=0;
float LastThrottleMovement=1000;
int ThrottleLow=1050, YawRight=1900, YawLeft=1100, ThrottleMovement=20;
uint32_t ArmHoldTime=5, DisarmHoldTime=1, AutoDisarmTime=15; // Seconds

// === Flight Mode ===
int FlightModeChannel=5; // CH5; future-il 6 aakkiyal CH6
int FlightModeLow=0, FlightModeHigh=1; // 0=ANGLE, 1=RATE/ACRO; group7/schema3
bool AngleMode=true, ModeChanged=false;
// === Stick Sensitivity ===
float AngleStickScale=0.10f, RateStickScale=0.15f, YawStickScale=0.15f;

// === Angle PID ===
float DesiredAngleRoll, DesiredAnglePitch;
float ErrorAngleRoll, ErrorAnglePitch;
float PrevErrorAngleRoll, PrevErrorAnglePitch;
float PrevItermAngleRoll, PrevItermAnglePitch;

// === Rate PID ===
float DesiredRateRoll, DesiredRatePitch, DesiredRateYaw;
float ErrorRateRoll, ErrorRatePitch, ErrorRateYaw;
float InputRoll, InputThrottle, InputPitch, InputYaw;
float PrevErrorRateRoll, PrevErrorRatePitch, PrevErrorRateYaw;
float PrevItermRateRoll, PrevItermRatePitch, PrevItermRateYaw;
float PIDReturn[]={0,0,0};

// === Rate PID Values ===
float PRateRoll=0.9, PRatePitch=PRateRoll, PRateYaw=3.0;
float IRateRoll=15, IRatePitch=IRateRoll, IRateYaw=15.0;
float DRateRoll=0.03, DRatePitch=DRateRoll, DRateYaw=0;

// === Angle PID Values ===
float PAngleRoll=3, PAnglePitch=PAngleRoll;
float IAngleRoll=0, IAnglePitch=IAngleRoll;
float DAngleRoll=0, DAnglePitch=DAngleRoll;

#include "AreionSerialIntegration.h"

void kalman_1d(float KalmanState, float KalmanUncertainty, float KalmanInput, float KalmanMeasurement) {
  KalmanState=KalmanState+LoopDt*KalmanInput;
  KalmanUncertainty=KalmanUncertainty+LoopDt*LoopDt*4.0f*4.0f;
  float KalmanGain=KalmanUncertainty/(KalmanUncertainty+3.0f*3.0f);
  KalmanState=KalmanState+KalmanGain*(KalmanMeasurement-KalmanState);
  KalmanUncertainty=(1.0f-KalmanGain)*KalmanUncertainty;
  Kalman1DOutput[0]=KalmanState;
  Kalman1DOutput[1]=KalmanUncertainty;
}

void pid_equation(float Error, float P, float I, float D, float PrevError, float PrevIterm) {
  float Pterm=P*Error;
  float Iterm=PrevIterm+I*(Error+PrevError)*LoopDt/2.0f;
  if (Iterm>400) Iterm=400;
  else if (Iterm<-400) Iterm=-400;
  float Dterm=D*(Error-PrevError)/LoopDt;
  float PIDOutput=Pterm+Iterm+Dterm;
  if (PIDOutput>400) PIDOutput=400;
  else if (PIDOutput<-400) PIDOutput=-400;
  PIDReturn[0]=PIDOutput;
  PIDReturn[1]=Error;
  PIDReturn[2]=Iterm;
}

void reset_pid(void) {
  PrevErrorRateRoll=0; PrevErrorRatePitch=0; PrevErrorRateYaw=0;
  PrevItermRateRoll=0; PrevItermRatePitch=0; PrevItermRateYaw=0;
  PrevErrorAngleRoll=0; PrevErrorAnglePitch=0;
  PrevItermAngleRoll=0; PrevItermAnglePitch=0;
}

void flight_mode(void) {
  if (FlightModeChannel<1 || FlightModeChannel>8 || ChannelNumber<FlightModeChannel) return;

  float ModeInput=areion_setup_mode_value();
  if (!std::isfinite(ModeInput)) return;
  const int SelectedMode=ModeInput<1500 ? FlightModeLow : FlightModeHigh;
  bool NewAngleMode=SelectedMode==0;

  if (NewAngleMode!=AngleMode) {
    AngleMode=NewAngleMode; ModeChanged=true;
    PrevErrorAngleRoll=PrevErrorAnglePitch=0;
    PrevItermAngleRoll=PrevItermAnglePitch=0;
  }
}

void arm_disarm(void)
{
  // Stick gestures and idle auto-disarm belong to the physical PPM receiver.
  // USB/AP use explicit ACTION ARM/DISARM; channels never request arming.
  // Input-loss and IMU-failure stops still apply independently in every mode.
  if (AreionSetupLocked || !AreionWizardComplete) {Armed=false;HoldGesture=0;return;}
  if (!Armed && AreionPidPending) {HoldGesture=0;return;}
  if (AreionInputSource!=0) return;
  if (AreionBootSource!=0 || !AreionReceiverVerified) {
    Armed=false;HoldGesture=0;return;
  }

  uint32_t Now=millis();
  bool Fresh=AreionInputReady && AreionActiveSource!=0, NewFrame=AreionInputNewFrame;
  float Throttle=ReceiverValue[2], Yaw=ReceiverValue[3];

  if (Fresh && NewFrame) {
    uint8_t Gesture=Throttle<ThrottleLow ? (Yaw>YawRight ? 1 : (Yaw<YawLeft ? 2 : 0)) : 0;
    if (Gesture!=HoldGesture) {
      HoldGesture=Gesture; HoldStart=Now; GestureConsumed=false;
    }
    uint32_t HoldTime=(Gesture==1 ? ArmHoldTime : DisarmHoldTime)*1000UL;
    if (Gesture!=0 && !GestureConsumed && (uint32_t)(Now-HoldStart)>=HoldTime) {
      if (Gesture==1 && !Armed) {
        ThrottleMovementTimer=Now; LastThrottleMovement=Throttle;
      }
      Armed=(Gesture==1); GestureConsumed=true;
    }
  }

  if (!Armed) return;
  if (Fresh && NewFrame && (Throttle>=ThrottleLow || LastThrottleMovement>=ThrottleLow || fabsf(Throttle-LastThrottleMovement)>=ThrottleMovement)) {
    LastThrottleMovement=Throttle; ThrottleMovementTimer=Now;
  }
  if (Throttle<ThrottleLow && (uint32_t)(Now-ThrottleMovementTimer)>=AutoDisarmTime*1000UL) {
    Armed=false; GestureConsumed=true;
  }
}

void read_receiver(void) {
  areion_read_receiver(); // Select exactly one: PPM, fresh AP or fresh USB channels.
}

void gyro_signals(void) {
  ImuReadOK=false;
  Wire.beginTransmission(0x68); Wire.write(0x3B);
  if (Wire.endTransmission(false)!=0) return;
  if (Wire.requestFrom((uint8_t)0x68, (uint8_t)14)!=14) return;
  uint8_t data[14]; for (int i=0; i<14; i++) data[i]=Wire.read();

  int16_t AccXLSB=(int16_t)((data[0]<<8)|data[1]);
  int16_t AccYLSB=(int16_t)((data[2]<<8)|data[3]);
  int16_t AccZLSB=(int16_t)((data[4]<<8)|data[5]);
  int16_t GyroX=(int16_t)((data[8]<<8)|data[9]);
  int16_t GyroY=(int16_t)((data[10]<<8)|data[11]);
  int16_t GyroZ=(int16_t)((data[12]<<8)|data[13]);

  RateRoll=GyroX/65.5f;
  RatePitch=GyroY/65.5f;
  RateYaw=GyroZ/65.5f;
  AccX=AccXLSB/4096.0f+AccOffsetX;
  AccY=AccYLSB/4096.0f+AccOffsetY;
  AccZ=AccZLSB/4096.0f+AccOffsetZ;

  AngleRoll=atan2f(AccY,sqrtf(AccX*AccX+AccZ*AccZ))*57.2957795f;
  AnglePitch=-atan2f(AccX,sqrtf(AccY*AccY+AccZ*AccZ))*57.2957795f;
  if (AreionRebaseAttitude) {
    KalmanAngleRoll=AngleRoll; KalmanAnglePitch=AnglePitch;
    KalmanUncertaintyAngleRoll=KalmanUncertaintyAnglePitch=4;
    AreionRebaseAttitude=false;
  }
  AreionImuSampleMs=millis();
  ImuReadOK=true;
}

static bool AreionAPAttempted=false;
static uint8_t AreionEscImuPhase=0;
static uint32_t AreionEscImuAt=0, AreionEscImuSampleAt=0;

static void areion_start_ap() {
  if(AreionAPAttempted) return;
  AreionAPAttempted=true;
  AreionWifiRecord wifi{};
  areion_load_wifi(wifi);
  AreionAPReady=AreionLinkReady && AreionWifiConfigured && receiver.beginAP(wifi.ssid,wifi.password,port);
  if (AreionAPReady) AreionActiveSSID=wifi.ssid;
  if(AreionAPReady) {
    AreionAPAddress=receiver.apIP().toString().c_str();
    areion_web_gateway_begin(receiver.apIP(), port);
  }
  if(AreionLinkReady) receiver.sendGroup(121);
}

// Endpoint calibration has finished (or was stopped). Bring the normal IMU
// online without dropping USB/AP or asking the operator for another reboot.
// Each call does a bounded amount of work; motor outputs stay at minimum.
static void areion_esc_imu_recover(uint32_t now) {
  if(!AreionEscBootMode || AreionEscState==1 || AreionEscState==2 || !AreionSetupStoreHealthy) return;
  areion_setup_output_minimum();
  if(AreionEscImuPhase==0) {
    AreionSetupComplete=false;ImuReadOK=false;ValidCalibrationSamples=0;RateCalibrationNumber=0;
    RateCalibrationRoll=RateCalibrationPitch=RateCalibrationYaw=0;
    Wire.begin(D4,D5);Wire.setClock(400000);
    AreionEscImuAt=now;AreionEscImuPhase=1;return;
  }
  if(AreionEscImuPhase==1 && uint32_t(now-AreionEscImuAt)>=250) {
    Wire.beginTransmission(0x68);Wire.write(0x6B);Wire.write(0x00);Wire.endTransmission();
    AreionEscImuAt=now;AreionEscImuPhase=2;return;
  }
  if(AreionEscImuPhase==2 && uint32_t(now-AreionEscImuAt)>=100) {
    Wire.beginTransmission(0x68);Wire.write(0x1A);Wire.write(0x05);Wire.endTransmission();
    Wire.beginTransmission(0x68);Wire.write(0x1C);Wire.write(0x10);Wire.endTransmission();
    Wire.beginTransmission(0x68);Wire.write(0x1B);Wire.write(0x08);Wire.endTransmission();
    AreionEscImuAt=now;AreionEscImuPhase=3;return;
  }
  if(AreionEscImuPhase==3 && uint32_t(now-AreionEscImuAt)>=100) {
    AreionEscImuSampleAt=now;AreionEscImuAt=now;AreionEscImuPhase=4;return;
  }
  if(AreionEscImuPhase==4) {
    const bool due=uint32_t(now-AreionEscImuSampleAt)>=1;
    if(due && RateCalibrationNumber<2000) {
      gyro_signals();++RateCalibrationNumber;
      if(ImuReadOK) {
        RateCalibrationRoll+=RateRoll;RateCalibrationPitch+=RatePitch;RateCalibrationYaw+=RateYaw;
        ++ValidCalibrationSamples;
      }
    }
    if(due) AreionEscImuSampleAt=now;
    // Readings during the zero capture are not yet calibrated live telemetry.
    ImuReadOK=false;
    if(RateCalibrationNumber>=2000 || uint32_t(now-AreionEscImuAt)>=12000) {
      if(ValidCalibrationSamples<=0 || RateCalibrationNumber<2000) {
        AreionSetupFault="IMU_STARTUP_FAILED";AreionEscImuPhase=6;return;
      }
      RateCalibrationRoll/=ValidCalibrationSamples;RateCalibrationPitch/=ValidCalibrationSamples;
      RateCalibrationYaw/=ValidCalibrationSamples;
      AreionEscImuAt=now;AreionEscImuPhase=5;
    }
    return;
  }
  if(AreionEscImuPhase==5 && uint32_t(now-AreionEscImuAt)>=1000) {
    gyro_signals();
    if(!ImuReadOK) {AreionSetupFault="IMU_STARTUP_FAILED";AreionEscImuPhase=6;return;}
    KalmanAngleRoll=AngleRoll;KalmanAnglePitch=AnglePitch;
    KalmanUncertaintyAngleRoll=KalmanUncertaintyAnglePitch=4;
    RateRoll-=RateCalibrationRoll;RatePitch-=RateCalibrationPitch;RateYaw-=RateCalibrationYaw;
    AreionSetupComplete=true;AreionEscBootMode=false;AreionEscImuPhase=6;
    AreionRebaseAttitude=false;areion_reset_input(true);
  }
}

void setup() {
  Serial.begin(115200);
  // === Receiver + USB/AP setup ===
  bool linkReady=receiver.begin();
  receiver.restrictGroupsToUsb(Serial, 138, 139);
  if (linkReady) linkReady=receiver.attachStream(Serial);
  receiver.setControlFromSerial(false); // Boot input is PPM; source selection enables one route.
  receiver.setControlFromUDP(false);
  // Restore the one-shot request before any PWM, AP or blocking IMU startup.
  AreionAPAttempted=false;AreionAPReady=false;AreionAPAddress.clear();AreionEscImuPhase=0;
  areion_link_begin(linkReady); // Bind PID/IMU/status and source-selection groups.
  ReceiverInput.begin(D10);
  for (int i=0; i<4; i++) ledcAttach(MOTOR_PINS[i],pwmFreq,pwmResolution);
  if(AreionEscBootMode) {
    // The pending request was consumed and read back before attaching PWM.
    // MAX must be the first pulse: a MIN-then-MAX sequence can arm an ESC.
    // AP startup is deferred until LOW so it cannot delay the HIGH deadline.
    // Skip blocking gyro startup; recovery runs after the sequence in loop().
    AreionSetupComplete=false;ImuReadOK=false;ValidCalibrationSamples=0;
    areion_setup_tick(millis());
    LoopTimer=micros();PreviousLoopTime=LoopTimer-4000UL;
    return;
  }
  areion_setup_output_minimum();
  areion_start_ap();

  Wire.begin(D4,D5); Wire.setClock(400000); delay(250);
  Wire.beginTransmission(0x68); Wire.write(0x6B); Wire.write(0x00); Wire.endTransmission(); delay(100);
  Wire.beginTransmission(0x68); Wire.write(0x1A); Wire.write(0x05); Wire.endTransmission();
  Wire.beginTransmission(0x68); Wire.write(0x1C); Wire.write(0x10); Wire.endTransmission();
  Wire.beginTransmission(0x68); Wire.write(0x1B); Wire.write(0x08); Wire.endTransmission(); delay(100);

  for (RateCalibrationNumber=0; RateCalibrationNumber<2000; RateCalibrationNumber++) {
    gyro_signals();
    if (ImuReadOK) {
      RateCalibrationRoll+=RateRoll; RateCalibrationPitch+=RatePitch; RateCalibrationYaw+=RateYaw;
      ValidCalibrationSamples++;
    }
    delay(1);
  }
  if (ValidCalibrationSamples>0) {
    RateCalibrationRoll/=ValidCalibrationSamples; RateCalibrationPitch/=ValidCalibrationSamples;
    RateCalibrationYaw/=ValidCalibrationSamples;
    KalmanAngleRoll=AngleRoll; KalmanAnglePitch=AnglePitch;
  }
  delay(1000); LoopTimer=micros(); PreviousLoopTime=LoopTimer-4000UL;
  AreionSetupComplete=true;
}

void loop() {
  uint32_t CurrentLoopTime=micros();
  LoopDt=(uint32_t)(CurrentLoopTime-PreviousLoopTime)*0.000001f;
  PreviousLoopTime=CurrentLoopTime;
  if (LoopDt<=0.0f) LoopDt=0.004f;

  receiver.processPackets(); // Receive commands and8-channel USB/AP input.
  read_receiver();
  areion_pid_flush_pending(); // Disarmed only; flash is never written during flight.
  if(AreionEscBootMode) {
    // No high-output operation is followed by blocking AP/IMU initialization.
    // Start AP only after output is LOW, then recover IMU with flight locked.
    areion_setup_tick(millis());
    if(AreionEscState!=2 || AreionWizardStage!=3) areion_start_ap();
    areion_esc_imu_recover(millis());
    areion_serial_publish();
    // Sample gyro once per 1ms recovery iteration rather than rereading a
    // register burst. The normal flight loop below remains 250Hz.
    const uint32_t period=AreionEscState==2?4000UL:1000UL;
    while ((uint32_t)(micros()-LoopTimer)<period);
    LoopTimer=micros();return;
  }
  gyro_signals();
  if (AreionMotorTestActive && !areion_imu_ready(millis())) areion_setup_cancel("MOTOR_TEST_IMU_LOST");
  if (areion_setup_tick(millis())) {
    if (ImuReadOK) {
      RateRoll-=RateCalibrationRoll;RatePitch-=RateCalibrationPitch;RateYaw-=RateCalibrationYaw;
      // Setup disables flight outputs, not the attitude estimate. Keep the
      // existing Kalman equations running so the live level display moves.
      kalman_1d(KalmanAngleRoll,KalmanUncertaintyAngleRoll,RateRoll,AngleRoll);
      KalmanAngleRoll=Kalman1DOutput[0];KalmanUncertaintyAngleRoll=Kalman1DOutput[1];
      kalman_1d(KalmanAnglePitch,KalmanUncertaintyAnglePitch,RatePitch,AnglePitch);
      KalmanAnglePitch=Kalman1DOutput[0];KalmanUncertaintyAnglePitch=Kalman1DOutput[1];
    }
    areion_serial_publish();
    while ((uint32_t)(micros()-LoopTimer)<4000UL);
    LoopTimer=micros();return;
  }
  if (!areion_imu_ready(millis())) {
    // A failed/new invalid sensor read must also stop an already armed FC.
    areion_motor_safe_stop();
    AreionRebaseAttitude=true;
    areion_serial_publish();
    while ((uint32_t)(micros()-LoopTimer)<4000UL);
    LoopTimer=micros();
    return;
  }
  arm_disarm();
  flight_mode();

 
  RateRoll-=RateCalibrationRoll;
  RatePitch-=RateCalibrationPitch;
  RateYaw-=RateCalibrationYaw;

  kalman_1d(KalmanAngleRoll,KalmanUncertaintyAngleRoll,RateRoll,AngleRoll);
  KalmanAngleRoll=Kalman1DOutput[0]; KalmanUncertaintyAngleRoll=Kalman1DOutput[1];
  kalman_1d(KalmanAnglePitch,KalmanUncertaintyAnglePitch,RatePitch,AnglePitch);
  KalmanAnglePitch=Kalman1DOutput[0]; KalmanUncertaintyAnglePitch=Kalman1DOutput[1];


  InputThrottle=ReceiverValue[2];
  DesiredRateYaw=YawStickScale*(ReceiverValue[3]-1500);

  if (AngleMode) {
    DesiredAngleRoll=AngleStickScale*(ReceiverValue[0]-1500);
    DesiredAnglePitch=AngleStickScale*(ReceiverValue[1]-1500);

    ErrorAngleRoll=DesiredAngleRoll-KalmanAngleRoll;
    ErrorAnglePitch=DesiredAnglePitch-KalmanAnglePitch;
    if(AreionPidPrimeErrors) {
      PrevErrorAngleRoll=ErrorAngleRoll;PrevErrorAnglePitch=ErrorAnglePitch;
    }

    pid_equation(ErrorAngleRoll,PAngleRoll,IAngleRoll,DAngleRoll,PrevErrorAngleRoll,PrevItermAngleRoll);
    DesiredRateRoll=PIDReturn[0];
    PrevErrorAngleRoll=PIDReturn[1];
    PrevItermAngleRoll=PIDReturn[2];

    pid_equation(ErrorAnglePitch,PAnglePitch,IAnglePitch,DAnglePitch,PrevErrorAnglePitch,PrevItermAnglePitch);
    DesiredRatePitch=PIDReturn[0];
    PrevErrorAnglePitch=PIDReturn[1];
    PrevItermAnglePitch=PIDReturn[2];
  } else {
    DesiredRateRoll=RateStickScale*(ReceiverValue[0]-1500);
    DesiredRatePitch=RateStickScale*(ReceiverValue[1]-1500);
  }


  ErrorRateRoll=DesiredRateRoll-RateRoll;
  ErrorRatePitch=DesiredRatePitch-RatePitch;
  ErrorRateYaw=DesiredRateYaw-RateYaw;

  if(AreionPidPrimeErrors) {
    PrevErrorRateRoll=ErrorRateRoll;PrevErrorRatePitch=ErrorRatePitch;PrevErrorRateYaw=ErrorRateYaw;
    AreionPidPrimeErrors=false;
  }
  if (ModeChanged) {
    PrevErrorRateRoll=ErrorRateRoll;
    PrevErrorRatePitch=ErrorRatePitch;
    ModeChanged=false;
  }

  pid_equation(ErrorRateRoll,PRateRoll,IRateRoll,DRateRoll,PrevErrorRateRoll,PrevItermRateRoll);
  InputRoll=PIDReturn[0];
  PrevErrorRateRoll=PIDReturn[1];
  PrevItermRateRoll=PIDReturn[2];

  pid_equation(ErrorRatePitch,PRatePitch,IRatePitch,DRatePitch,PrevErrorRatePitch,PrevItermRatePitch);
  InputPitch=PIDReturn[0];
  PrevErrorRatePitch=PIDReturn[1];
  PrevItermRatePitch=PIDReturn[2];

  pid_equation(ErrorRateYaw,PRateYaw,IRateYaw,DRateYaw,PrevErrorRateYaw,PrevItermRateYaw);
  InputYaw=PIDReturn[0];
  PrevErrorRateYaw=PIDReturn[1];
  PrevItermRateYaw=PIDReturn[2];

  // Motor mixing — microseconds
  if (InputThrottle>1800.0f) InputThrottle=1800.0f;
  MotorInput1=InputThrottle+InputRoll-InputPitch+InputYaw;
  MotorInput2=InputThrottle-InputRoll-InputPitch-InputYaw;
  MotorInput3=InputThrottle-InputRoll+InputPitch+InputYaw;
  MotorInput4=InputThrottle+InputRoll+InputPitch-InputYaw;

  MotorInput1=constrain(MotorInput1,1000,1999);
  MotorInput2=constrain(MotorInput2,1000,1999);
  MotorInput3=constrain(MotorInput3,1000,1999);
  MotorInput4=constrain(MotorInput4,1000,1999);

  if (MotorInput1<AreionMotorIdle[0]) MotorInput1=AreionMotorIdle[0];
  if (MotorInput2<AreionMotorIdle[1]) MotorInput2=AreionMotorIdle[1];
  if (MotorInput3<AreionMotorIdle[2]) MotorInput3=AreionMotorIdle[2];
  if (MotorInput4<AreionMotorIdle[3]) MotorInput4=AreionMotorIdle[3];

  if (AreionSetupLocked || !AreionWizardComplete || !Armed || !AreionInputReady || ReceiverValue[2]<ThrottleLow) {
    MotorInput1=MotorInput2=MotorInput3=MotorInput4=1000;
    reset_pid();
  }


  // Microseconds to duty — 250 Hz, 12-bit
  ledcWrite(MOTOR_PINS[0],((uint32_t)MotorInput1*4096UL+2000UL)/4000UL);
  ledcWrite(MOTOR_PINS[1],((uint32_t)MotorInput2*4096UL+2000UL)/4000UL);
  ledcWrite(MOTOR_PINS[2],((uint32_t)MotorInput3*4096UL+2000UL)/4000UL);
  ledcWrite(MOTOR_PINS[3],((uint32_t)MotorInput4*4096UL+2000UL)/4000UL);

  

  areion_serial_publish();

  while ((uint32_t)(micros()-LoopTimer)<4000UL);
  LoopTimer=micros();
}
