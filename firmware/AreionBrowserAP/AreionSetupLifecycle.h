#pragma once
// Persistent setup interlock and dedicated calibration outputs. This file is
// included after the existing input/IMU helpers, before action registration.
#include <cstdio>

static areion::Group AreionSetupStatus(130,1), AreionRawPPM(131,1), AreionPidStatus(136,1);
static bool AreionPidPending=false, AreionPidRestoreCompletion=false, AreionPidPrimeErrors=false;
static uint32_t AreionPidRevision=0, AreionPidSavedRevision=0;
static std::string AreionPidError="";
static std::vector<areion::Message> AreionFactoryDefaults;
static areion::Group AreionRxCalibration(132,1,true,true), AreionSetupConfig(134,1,true,true);
static bool AreionSetupLocked=true, AreionWizardComplete=false;
static int AreionWizardStage=0, AreionEscState=0, AreionMotorVerifiedMask=0;
// FailsafeVerified is a legacy optional attestation, retained in status/storage.
// Actual runtime input-loss handling is independent of this wizard field.
static bool AreionSensorVerified=false, AreionReceiverVerified=false, AreionFailsafeVerified=false;
static bool AreionMotorTestActive=false, AreionSetupStarted=false, AreionSetupStoreHealthy=true;
static int AreionTestUs[4]={1000,1000,1000,1000};
static uint32_t AreionSetupRevision=0, AreionConfigFingerprint=0;
static std::string AreionSetupFault="", AreionKitId="";
static int AreionRawValues[8]={0}, AreionRawCount=0;
static bool AreionRawFresh=false, AreionSeenPpmFresh=false, AreionSeenPpmLoss=false;
static uint32_t AreionRawAge=UINT32_MAX;
static int AreionRxCal[8][4]={{1000,1500,2000,0},{1000,1500,2000,0},{1000,1500,2000,0},{1000,1500,2000,0},
    {1000,1500,2000,0},{1000,1500,2000,0},{1000,1500,2000,0},{1000,1500,2000,0}};
static int AreionProfile=0, AreionBootSource=0, AreionAxisChannels[4]={1,2,3,4}, AreionDeadband=5;
static int AreionMotorIdle[4]={1180,1180,1180,1180};
static uint32_t AreionBenchOwner=0, AreionBenchAt=0, AreionBenchStart=0, AreionEscAt=0;
static int AreionBenchMask=0, AreionMotorTestedMask=0;
// A calibration boot holds the flight lock while the endpoint sequence and
// subsequent nonblocking gyro startup run. It never automatically arms.
static bool AreionEscClockStarted=false, AreionEscBootMode=false;
static bool AreionEscCancelUnconfirmed=false;
static const uint16_t AreionSetupRecordId=199;

static bool areion_setup_equal(const std::vector<areion::Value>& a,const std::vector<areion::Value>& b) {
  if(a.size()!=b.size()) return false;
  for(size_t i=0;i<a.size();++i) {
    if(a[i].type!=b[i].type) return false;
    if(a[i].type==areion::ValueType::Integer && a[i].integer!=b[i].integer) return false;
    if(a[i].type==areion::ValueType::Float && a[i].real!=b[i].real) return false;
    if(a[i].type==areion::ValueType::Boolean && a[i].boolean!=b[i].boolean) return false;
    if(a[i].type==areion::ValueType::String && a[i].text!=b[i].text) return false;
  }
  return true;
}
static void areion_setup_output_minimum() {
  for(int i=0;i<4;++i) { AreionTestUs[i]=1000;ledcWrite(MOTOR_PINS[i],minDuty); }
  MotorInput1=MotorInput2=MotorInput3=MotorInput4=1000;
  Armed=false;
}
static void areion_setup_stop_motor() {
  AreionMotorTestActive=false; AreionBenchMask=0; AreionBenchOwner=0;
  areion_setup_output_minimum();
  if(AreionWizardStage==6) AreionWizardStage=1;
}
static bool areion_setup_saved_matches(uint16_t id) {
  auto* group=receiver.engine().findGroup(id);
  if(!group) return false;
  std::vector<areion::Value> current;areion::Message saved;std::string why;
  return group->values(current) && AreionStorage.load(id,group->schema(),saved,why)
    && group->validate(saved.data) && areion_setup_equal(current,saved.data);
}
static bool areion_setup_fingerprint(uint32_t& hash) {
  // Match every active group to its durable copy before hashing; a completion
  // record cannot authorize a different mixture of settings after reset.
  std::string bytes;
  for(uint16_t id:{2,3,4,6,7,112,132,134}) {
    if(!areion_setup_saved_matches(id)) return false;
    areion::Message snapshot;std::string frame;
    if(!receiver.engine().snapshot(id,snapshot)) return false;
    snapshot.type=areion::Type::Data;snapshot.session=1;snapshot.seq=1;
    if(!areion::encodeFrame(snapshot,frame)) return false;
    bytes+=frame;
  }
  hash=areion::crc32(reinterpret_cast<const uint8_t*>(bytes.data()),bytes.size());return true;
}
static bool areion_setup_persist() {
  areion::Message record;record.group=AreionSetupRecordId;record.schema=1;
  record.data={areion::Value::fromBool(AreionWizardComplete),areion::Value::fromInt(AreionEscState),
    areion::Value::fromInt(AreionMotorVerifiedMask),areion::Value::fromBool(AreionSensorVerified),
    areion::Value::fromBool(AreionReceiverVerified),areion::Value::fromBool(AreionFailsafeVerified),
    areion::Value::fromInt(AreionSetupRevision),areion::Value::fromInt(AreionConfigFingerprint),
    areion::Value::fromBool(AreionSetupStarted)};
  std::string why;areion::Message readback;
  if(!AreionStorageOK || !AreionSetupStoreHealthy || !AreionStorage.save(record,why)
     || !AreionStorage.load(AreionSetupRecordId,1,readback,why)
     || !areion_setup_equal(record.data,readback.data)) {
    AreionSetupStoreHealthy=false;AreionStorageOK=false;AreionSetupLocked=true;AreionWizardComplete=false;
    AreionSetupFault=why.empty()?"SETUP_STORAGE_VERIFY_FAILED":why;
    areion_setup_stop_motor();return false;
  }
  return true;
}
static areion::ActionResult areion_setup_commit(const char* success) {
  if(areion_setup_persist()) return {true,success};
  return {false,"SETUP_PERSIST_FAILED"};
}
static bool areion_setup_valid_mapping() {
  if(AreionBootSource!=0 && FlightModeChannel<5) return false;
  for(int i=0;i<4;++i) {
    if(AreionAxisChannels[i]<1 || AreionAxisChannels[i]>8 || AreionAxisChannels[i]==FlightModeChannel) return false;
    for(int j=0;j<i;++j) if(AreionAxisChannels[i]==AreionAxisChannels[j]) return false;
  }
  return true;
}
static float areion_setup_normalized(int channel,bool throttle=false) {
  const int i=channel-1;const float raw=AreionPPMValues[i];const int* c=AreionRxCal[i];
  float out;
  if(throttle) out=1000.f+(raw-c[0])*1000.f/float(c[2]-c[0]);
  else out=raw<c[1] ? 1500.f+(raw-c[1])*500.f/float(c[1]-c[0]) : 1500.f+(raw-c[1])*500.f/float(c[2]-c[1]);
  out=constrain(out,1000.f,2000.f);
  if(c[3]) out=3000.f-out;
  if(!throttle && fabsf(raw-c[1])<=AreionDeadband) out=1500.f;
  return out;
}
static void areion_setup_ppm_normalize(float* output) {
  for(int i=0;i<8;++i) output[i]=i<AreionPPMCount?AreionPPMValues[i]:1000.f;
  for(int i=0;i<4;++i) output[i]=AreionAxisChannels[i]<=AreionPPMCount?
    areion_setup_normalized(AreionAxisChannels[i],i==2):(i==2?1000.f:1500.f);
}
static float areion_setup_mode_value() {
  return AreionInputSource==0 && AreionPPMFresh && FlightModeChannel<=AreionPPMCount?
    AreionPPMValues[FlightModeChannel-1]:ReceiverValue[FlightModeChannel-1];
}
static void areion_setup_raw_update() {
  AreionRawFresh=AreionPPMFresh;AreionRawCount=AreionPPMFresh?AreionPPMCount:0;
  AreionRawAge=AreionHasPPM?uint32_t(millis()-AreionPPMAt):UINT32_MAX;
  for(int i=0;i<8;++i) AreionRawValues[i]=AreionRawFresh && i<AreionRawCount?int(AreionPPMValues[i]):0;
  if(AreionSetupLocked && AreionSetupStarted) {
    if(AreionRawFresh) AreionSeenPpmFresh=true;
    else if(AreionSeenPpmFresh) AreionSeenPpmLoss=true;
  }
}
static bool areion_setup_before_set(uint16_t id,const std::vector<areion::Value>& values) {
  if(AreionPidPending || AreionMotorTestActive || AreionEscState==1 || AreionEscState==2 || AreionEscBootMode) return false;
  if(id!=2 && id!=3 && id!=4 && id!=6 && id!=7 && id!=112 && id!=132 && id!=134) return true;
  auto* group=receiver.engine().findGroup(id);std::vector<areion::Value> current;
  if(!group || !group->values(current)) return false;
  if(areion_setup_equal(values,current)) return true;
  AreionSetupLocked=true;AreionWizardComplete=false;AreionConfigFingerprint=0;
  AreionSetupStarted=true;AreionWizardStage=1;areion_reset_input();
  if(id==6) AreionSensorVerified=false;
  if(id==132 || id==4 || id==7 || id==112) {
    AreionReceiverVerified=false;AreionFailsafeVerified=false;AreionSeenPpmFresh=false;AreionSeenPpmLoss=false;
  }
  if(id==134) {
    if(values[0].integer!=current[0].integer) {
      AreionSensorVerified=false;AreionMotorVerifiedMask=0;AreionEscState=0;AreionMotorTestedMask=0;
    }
    for(int i=7;i<11;++i) if(values[size_t(i)].integer!=current[size_t(i)].integer) AreionMotorVerifiedMask&=~(1<<(i-7));
    bool receiverChange=false;
    for(int i=1;i<=6;++i) receiverChange|=values[size_t(i)].integer!=current[size_t(i)].integer;
    if(receiverChange) {AreionReceiverVerified=false;AreionFailsafeVerified=false;AreionSeenPpmFresh=false;AreionSeenPpmLoss=false;}
  }
  // Durably revoke completion BEFORE the engine assigns any changed value.
  return areion_setup_persist();
}
static bool areion_setup_cancel(const char* why) {
  areion_setup_stop_motor();areion_reset_input();
  if(AreionEscState==1 || AreionEscState==2) {
    AreionEscState=6;AreionWizardStage=7;AreionSetupFault=why;
    if(!areion_setup_persist()) AreionEscCancelUnconfirmed=true;
  }
  return !AreionEscCancelUnconfirmed;
}
static void areion_setup_boot() {
  AreionSetupLocked=true;AreionWizardComplete=false;AreionSetupStarted=false;
  AreionWizardStage=0;AreionEscState=0;AreionMotorVerifiedMask=0;
  AreionSensorVerified=AreionReceiverVerified=AreionFailsafeVerified=false;
  AreionSetupRevision=AreionConfigFingerprint=0;AreionSetupFault="";
  AreionMotorTestActive=false;AreionBenchMask=AreionMotorTestedMask=0;
  AreionSeenPpmFresh=AreionSeenPpmLoss=false;AreionEscClockStarted=false;AreionEscBootMode=false;
  AreionEscCancelUnconfirmed=false;
  AreionPidPending=AreionPidRestoreCompletion=AreionPidPrimeErrors=false;
  AreionPidRevision=AreionPidSavedRevision=0;AreionPidError="";
  AreionSetupStoreHealthy=AreionStorageOK;
  if(!AreionStorageOK) {AreionSetupFault="NO_STORAGE";return;}
  receiver.engine().restore(AreionRxCalibration);
  receiver.engine().restore(AreionSetupConfig);
  AreionInputSource=AreionBootSource;
  receiver.setControlFromSerial(AreionInputSource==2);receiver.setControlFromUDP(AreionInputSource==1);
  areion_reset_input(true);
  areion::Message record;std::string why;
  if(!AreionStorage.load(AreionSetupRecordId,1,record,why)) {
    if(why!="NOT_SAVED") {AreionSetupStoreHealthy=false;AreionStorageOK=false;AreionSetupFault=why;}
    return;
  }
  const auto& v=record.data;
  bool valid=v.size()==9;
  if(valid) {
    for(int i:{0,3,4,5,8}) valid&=v[size_t(i)].type==areion::ValueType::Boolean;
    for(int i:{1,2,6,7}) valid&=v[size_t(i)].type==areion::ValueType::Integer;
    valid=valid && v[1].integer>=0 && v[1].integer<=6 && v[2].integer>=0 && v[2].integer<=15
      && v[6].integer>=0 && v[6].integer<=UINT32_MAX && v[7].integer>=0 && v[7].integer<=UINT32_MAX;
  }
  if(!valid) {AreionSetupStoreHealthy=false;AreionStorageOK=false;AreionSetupFault="SETUP_RECORD_INVALID";return;}
  AreionEscState=int(v[1].integer);AreionMotorVerifiedMask=int(v[2].integer);
  AreionSensorVerified=v[3].boolean;AreionReceiverVerified=v[4].boolean;AreionFailsafeVerified=v[5].boolean;
  AreionSetupRevision=uint32_t(v[6].integer);AreionConfigFingerprint=uint32_t(v[7].integer);AreionSetupStarted=v[8].boolean;
  AreionWizardStage=AreionSetupStarted?1:0;
  if(AreionEscState==1) {
    AreionEscState=2;AreionWizardStage=3;AreionSetupStarted=true;
    // Consume the one-shot request durably before any high output is possible.
    if(!areion_setup_persist()) {AreionEscState=6;AreionWizardStage=7;}
    else AreionEscBootMode=true;
    return;
  }
  if(AreionEscState==2) {
    AreionEscState=6;AreionWizardStage=7;AreionSetupFault="ESC_INTERRUPTED_RESTART_REQUIRED";
    areion_setup_persist();return;
  }
  uint32_t actual=0;
  if(v[0].boolean && AreionSetupStarted && AreionSensorVerified
     && (AreionBootSource!=0 || AreionReceiverVerified) && AreionMotorVerifiedMask==15
     && (AreionEscState==4 || AreionEscState==5) && areion_setup_valid_mapping()
     && areion_setup_fingerprint(actual) && actual==AreionConfigFingerprint) {
    AreionWizardComplete=true;AreionSetupLocked=false;AreionWizardStage=0;
  } else if(v[0].boolean) {
    AreionSetupFault="SETUP_SAVED_CONFIG_MISMATCH";areion_setup_persist();
  }
}
// Returns true while setup owns the motor outputs, including the locked idle.
static bool areion_setup_tick(uint32_t now) {
  if(!AreionSetupLocked) return false;
  Armed=false;HoldGesture=0;GestureConsumed=true;reset_pid();
  if(AreionEscState==2 && AreionSetupStoreHealthy) {
    if(!AreionEscClockStarted) {AreionEscAt=now;AreionEscClockStarted=true;}
    uint32_t elapsed=now-AreionEscAt;
    if(elapsed<3000) {
      AreionWizardStage=3;bool written=true;
      for(int i=0;i<4;++i) written=ledcWrite(MOTOR_PINS[i],maxDuty) && written;
      if(!written) {areion_setup_cancel("ESC_OUTPUT_FAILED");return true;}
      MotorInput1=MotorInput2=MotorInput3=MotorInput4=2000;
    } else if(elapsed<6000) {
      AreionWizardStage=4;areion_setup_output_minimum();
    } else {
      areion_setup_output_minimum();AreionEscState=3;AreionWizardStage=5;
      if(!areion_setup_persist()) {AreionEscState=6;AreionWizardStage=7;}
    }
    return true;
  }
  if(AreionMotorTestActive) {
    if(!AreionSetupStoreHealthy || !areion_imu_ready(now) || AreionEscBootMode
       || receiver.engine().ownerSession()!=AreionBenchOwner
       || uint32_t(now-AreionBenchAt)>=350 || uint32_t(now-AreionBenchStart)>=30000) {
      areion_setup_stop_motor();AreionSetupFault="MOTOR_TEST_STOPPED_TIMEOUT_OR_OWNER";
    } else {
      bool written=true;
      for(int i=0;i<4;++i) written=ledcWrite(MOTOR_PINS[i],(uint32_t(AreionTestUs[i])*4096UL+2000UL)/4000UL) && written;
      if(!written) {areion_setup_stop_motor();AreionSetupFault="MOTOR_OUTPUT_FAILED";return true;}
      for(int i=0;i<4;++i) if(AreionTestUs[i]>1000) AreionMotorTestedMask|=1<<i;
      MotorInput1=float(AreionTestUs[0]);MotorInput2=float(AreionTestUs[1]);
      MotorInput3=float(AreionTestUs[2]);MotorInput4=float(AreionTestUs[3]);
    }
    return true;
  }
  areion_setup_output_minimum();return true;
}
// All multi-group transactions first persist an incomplete setup record. A
// power cut between subsequent writes therefore cannot authorize mixed settings.
static bool areion_factory_capture() {
  AreionFactoryDefaults.clear();
  for(uint16_t id:{2,3,4,6,7,112,132,134}) {
    areion::Message snapshot;
    if(!receiver.engine().snapshot(id,snapshot)) return false;
    AreionFactoryDefaults.push_back(snapshot);
  }
  return true;
}
static bool areion_transaction_fault(const std::string& error) {
  AreionSetupFault=error.empty()?"SETTINGS_VERIFY_FAILED":error;
  AreionStorageOK=AreionSetupStoreHealthy=false;
  AreionSetupLocked=true;AreionWizardComplete=false;AreionConfigFingerprint=0;
  areion_setup_stop_motor();areion_reset_input();return false;
}
static bool areion_save_group(uint16_t id) {
  areion::Message snapshot;std::string why;
  if(!receiver.engine().snapshot(id,snapshot) || !AreionStorage.save(snapshot,why)
     || !areion_setup_saved_matches(id)) return areion_transaction_fault(why);
  return true;
}
static bool areion_transaction_begin() {
  AreionSetupLocked=true;AreionWizardComplete=false;AreionConfigFingerprint=0;
  AreionSetupStarted=true;AreionWizardStage=1;AreionSetupFault="";
  areion_setup_output_minimum();areion_reset_input();
  return areion_setup_persist();
}
static bool areion_transaction_finish(bool restoreCompletion) {
  if(restoreCompletion) {
    uint32_t hash=0;
    if(!AreionSensorVerified || (AreionBootSource==0 && !AreionReceiverVerified)
       || AreionMotorVerifiedMask!=15 || (AreionEscState!=4 && AreionEscState!=5)
       || !areion_setup_valid_mapping() || !areion_setup_fingerprint(hash))
      return areion_transaction_fault("SETTINGS_NOT_SAVED_OR_MISMATCH");
    if(AreionSetupRevision==UINT32_MAX) return areion_transaction_fault("SETUP_REVISION_EXHAUSTED");
    AreionConfigFingerprint=hash;AreionWizardComplete=true;++AreionSetupRevision;
  }
  if(!areion_setup_persist()) return false;
  AreionSetupLocked=!AreionWizardComplete;AreionWizardStage=AreionWizardComplete?0:1;
  areion_reset_input(true);return true;
}
static areion::ActionResult areion_reset_all() {
  if(AreionFactoryDefaults.size()!=8) return {false,"FACTORY_DEFAULTS_UNAVAILABLE"};
  // Clear the pending ESC request in the very first durable record.
  const bool wasEscPending=AreionEscState==1;
  AreionEscState=0;AreionMotorVerifiedMask=AreionMotorTestedMask=0;
  AreionSensorVerified=AreionReceiverVerified=AreionFailsafeVerified=false;
  AreionSeenPpmFresh=AreionSeenPpmLoss=false;
  if(!areion_transaction_begin()) {
    if(wasEscPending) {
      AreionEscCancelUnconfirmed=true;AreionEscState=6;
      AreionSetupFault="RESET_ESC_CANCEL_NOT_PERSISTED";
      return {false,"RESET_ESC_CANCEL_NOT_PERSISTED"};
    }
    return {false,"RESET_PERSIST_FAILED"};
  }
  for(const auto& snapshot:AreionFactoryDefaults) {
    if(!receiver.engine().applyLocal(snapshot.group,snapshot.data)) {
      areion_transaction_fault("FACTORY_DEFAULTS_INVALID");return {false,"RESET_PERSIST_FAILED"};
    }
    if(!areion_save_group(snapshot.group)) return {false,"RESET_PERSIST_FAILED"};
  }
  AreionPidRevision=AreionPidSavedRevision=0;AreionPidError="";
  AreionPidPending=AreionPidRestoreCompletion=AreionPidPrimeErrors=false;
  if(!areion_transaction_finish(false)) return {false,"RESET_PERSIST_FAILED"};
  return {true,"RESET_DEFAULTS_SAVED"};
}
static areion::ActionResult areion_input_save(int source) {
  if(AreionMotorTestActive || AreionEscState==1 || AreionEscState==2) return {false,"CALIBRATION_BUSY"};
  if(source<0 || source>2) return {false,"INPUT_SOURCE"};
  if(source==0 && (!AreionReceiverVerified || !areion_setup_valid_mapping()))
    return {false,"VERIFY_PPM_IN_SETUP_FIRST"};
  if(source!=0 && FlightModeChannel<5) return {false,"DIGITAL_MODE_CHANNEL_CH5_TO_CH8"};
  std::vector<areion::Value> values;
  if(!AreionSetupConfig.values(values)) return {false,"INPUT_SETTINGS_INVALID"};
  values[1]=areion::Value::fromInt(source);
  if(!AreionSetupConfig.validate(values)) return {false,"INPUT_SETTINGS_INVALID"};
  const bool completed=AreionWizardComplete && !AreionSetupLocked;
  if(completed) {
    uint32_t hash=0;
    if(!areion_setup_fingerprint(hash) || hash!=AreionConfigFingerprint) {
      areion_transaction_begin();areion_transaction_fault("INPUT_CONFIG_NOT_VERIFIED");
      return {false,"INPUT_SAVE_FAILED"};
    }
  }
  if(!areion_transaction_begin()) return {false,"INPUT_SAVE_FAILED"};
  if(!receiver.engine().applyLocal(134,values)) {
    areion_transaction_fault("INPUT_SETTINGS_INVALID");return {false,"INPUT_SAVE_FAILED"};
  }
  if(!areion_save_group(134) || !areion_transaction_finish(completed)) return {false,"INPUT_SAVE_FAILED"};
  return {true,"INPUT_SAVED"};
}
static bool areion_pid_flush_pending() {
  if(!AreionPidPending) return true;
  // Never perform NVS work during a live flight iteration. A failed transaction
  // stays pending/error-latched with storage unhealthy, so it is not retried.
  if(Armed || !AreionStorageOK || !AreionSetupStoreHealthy) return false;
  if(!areion_transaction_begin() || !areion_save_group(2) || !areion_save_group(3)
     || !areion_transaction_finish(AreionPidRestoreCompletion)) {
    AreionPidError=AreionSetupFault.empty()?"PID_SAVE_FAILED":AreionSetupFault;
    return false;
  }
  AreionPidSavedRevision=AreionPidRevision;AreionPidPending=false;
  AreionPidRestoreCompletion=false;AreionPidError="";return true;
}
static areion::ActionResult areion_pid_action(const std::vector<areion::Value>& d,uint32_t now) {
  if(d.size()!=11 || d[0].type!=areion::ValueType::Integer || d[1].type!=areion::ValueType::Boolean
     || (d[0].integer!=2 && d[0].integer!=3)) return {false,"PID_ACTION_DATA"};
  for(size_t i=2;i<11;++i) if(d[i].type!=areion::ValueType::Float || !std::isfinite(d[i].real)) return {false,"PID_ACTION_DATA"};
  const uint16_t id=uint16_t(d[0].integer);const size_t count=id==2?9:6;
  if(id==3 && (d[8].real!=0 || d[9].real!=0 || d[10].real!=0)) return {false,"PID_UNUSED_VALUES"};
  std::vector<areion::Value> values(d.begin()+2,d.begin()+2+count),current;
  auto* group=receiver.engine().findGroup(id);
  if(!group || !group->validate(values) || !group->values(current)) return {false,"PID_INVALID_VALUES"};
  if(!AreionStorageOK || !AreionSetupStoreHealthy) return {false,"SETUP_STORAGE_LOCKED"};
  if(AreionMotorTestActive || AreionEscState==1 || AreionEscState==2 || AreionEscBootMode) return {false,"CALIBRATION_BUSY"};
  if(Armed) {
    if(!d[1].boolean) return {false,"BENCH_CONFIRM_REQUIRED"};
    if(AreionSetupLocked || !AreionWizardComplete) return {false,"SETUP_LOCKED"};
    if(!AreionInputReady || (AreionInputSource==0?
       (!AreionPPMFresh || uint32_t(now-AreionPPMAt)>=PpmTimeoutMs):!areion_digital_fresh(now))) return {false,"INPUT_NOT_READY"};
    if(!areion_imu_ready(now)) return {false,"IMU_NOT_READY"};
  }
  // Normalize gain values to the bound float32 before comparing no-op writes.
  for(auto& value:values) value=areion::Value::fromFloat(float(value.real));
  const bool changed=!areion_setup_equal(values,current);
  if(changed && AreionPidRevision==UINT32_MAX) return {false,"PID_REVISION_EXHAUSTED"};
  if(!changed && !AreionPidPending && areion_setup_saved_matches(id)) return {true,"PID_SAVED"};
  if(!AreionPidPending) AreionPidRestoreCompletion=AreionWizardComplete && !AreionSetupLocked;
  if(changed) {
    // ACTION runs in processPackets(), strictly between control iterations.
    // Clear integrators and prime the derivative with the next measured errors.
    if(!receiver.engine().applyLocal(id,values)) return {false,"PID_INVALID_VALUES"};
    ++AreionPidRevision;AreionPidPrimeErrors=true;
  }
  AreionPidPending=true;AreionPidError="";
  if(Armed) return {true,"PID_APPLIED_PENDING_SAVE"};
  return areion_pid_flush_pending()?areion::ActionResult{true,"PID_SAVED"}:areion::ActionResult{false,"PID_SAVE_FAILED"};
}
static areion::ActionResult areion_setup_action(const std::vector<areion::Value>& d,uint32_t now) {
  if(d.size()!=5 || d[0].type!=areion::ValueType::String) return {false,"SETUP_ACTION_DATA"};
  for(size_t i=1;i<5;++i) if(d[i].type!=areion::ValueType::Integer) return {false,"SETUP_ACTION_DATA"};
  const std::string& cmd=d[0].text;const int64_t a=d[1].integer,b=d[2].integer;
  if(d[3].integer!=0 || d[4].integer!=0) return {false,"SETUP_UNUSED_ARGS"};
  const bool zeros=a==0 && b==0, confirm=a==1 && b==0;
  if(cmd=="STOP" || cmd=="MOTOR_STOP") {
    if(!zeros) return {false,"SETUP_UNUSED_ARGS"};
    if(cmd=="MOTOR_STOP" && AreionEscState==2) return {false,"CALIBRATION_BUSY"};
    if(cmd=="STOP") {
      if(!areion_setup_cancel("ESC_CANCELLED")) return {false,"ESC_CANCEL_NOT_PERSISTED"};
    } else areion_setup_stop_motor();
    return {true,"STOPPED"};
  }
  // Do not let a delayed MOTOR_SET insert MIN then resume HIGH, or let a
  // second schedule overwrite a completed sequence before IMU recovery.
  if(AreionEscBootMode) return {false,AreionEscState==2?"CALIBRATION_BUSY":"WAIT_FOR_IMU_STARTUP"};
  if(Armed) return {false,"DISARM_FIRST"};
  if(!AreionStorageOK || !AreionSetupStoreHealthy) return {false,"SETUP_STORAGE_LOCKED"};
  if(AreionPidPending) return {false,"PID_SAVE_PENDING"};
  if(cmd=="INPUT_SAVE") {
    if(a<0 || a>2 || b!=0) return {false,"INPUT_SOURCE"};
    return areion_input_save(int(a));
  }
  if(cmd=="BEGIN") {
    if((a!=0 && a!=1) || b!=0) return {false,"SETUP_BEGIN_ACK"};
    if(AreionMotorTestActive || AreionEscState==2) return {false,"CALIBRATION_BUSY"};
    areion_setup_stop_motor();areion_reset_input();
    if(!AreionSetupLocked) {
      AreionWizardComplete=false;AreionSetupLocked=true;AreionConfigFingerprint=0;
      // Reopening for review retains physical checks. Changed groups revoke
      // only their dependent evidence in areion_setup_before_set().
    }
    AreionSetupStarted=true;if(AreionEscState!=1 && AreionEscState!=2) AreionWizardStage=1;
    return areion_setup_commit("SETUP_LOCKED");
  }
  if(!AreionSetupLocked || !AreionSetupStarted) return {false,"BEGIN_SETUP_FIRST"};
  if(cmd=="RESET_ALL") {
    if(!confirm) return {false,"SETUP_CONFIRM_REQUIRED"};
    if(AreionMotorTestActive || AreionEscState==2) return {false,"CALIBRATION_BUSY"};
    return areion_reset_all();
  }
  if(cmd=="MOTOR_SET") {
    if(!AreionMotorTestActive || receiver.engine().ownerSession()!=AreionBenchOwner || a!=AreionBenchMask
       || b<1000 || b>1500 || uint32_t(now-AreionBenchAt)>=350 || uint32_t(now-AreionBenchStart)>=30000) {
      areion_setup_stop_motor();return {false,"MOTOR_TEST_INACTIVE_OR_EXPIRED"};
    }
    AreionBenchAt=now;
    for(int i=0;i<4;++i) AreionTestUs[i]=(a&(1<<i))?int(b):1000;
    return {true,"MOTOR_TEST_UPDATED"};
  }
  if(AreionMotorTestActive || AreionEscState==2) return {false,"CALIBRATION_BUSY"};
  if(cmd=="MOTOR_START") {
    if(a<1 || a>15 || b!=1) return {false,"PROPS_BATTERY_CONFIRM_REQUIRED"};
    if(AreionEscState!=4 && AreionEscState!=5) return {false,"ESC_CHECK_REQUIRED"};
    if(!AreionSensorVerified || !areion_imu_ready(now)) return {false,"IMU_NOT_READY"};
    areion_reset_input();areion_setup_output_minimum();AreionMotorTestActive=true;
    AreionBenchMask=int(a);AreionBenchOwner=receiver.engine().ownerSession();
    AreionBenchAt=AreionBenchStart=now;AreionWizardStage=6;
    return {true,"MOTOR_TEST_STARTED"};
  }
  if(cmd=="MOTOR_OK") {
    if(a<1 || a>15 || b!=1 || (AreionMotorTestedMask&int(a))!=int(a)) return {false,"TEST_MOTORS_FIRST"};
    AreionMotorVerifiedMask|=int(a);return areion_setup_commit("MOTORS_VERIFIED");
  }
  if(cmd=="FINALIZE") {
    if(!zeros) return {false,"SETUP_UNUSED_ARGS"};
    if(!AreionSensorVerified || (AreionBootSource==0 && !AreionReceiverVerified)
       || AreionMotorVerifiedMask!=15 || (AreionEscState!=4 && AreionEscState!=5)
       || !areion_setup_valid_mapping()) return {false,"SETUP_CHECKS_INCOMPLETE"};
    uint32_t hash=0;if(!areion_setup_fingerprint(hash)) return {false,"SETTINGS_NOT_SAVED_OR_MISMATCH"};
    if(AreionSetupRevision==UINT32_MAX) return {false,"SETUP_REVISION_EXHAUSTED"};
    AreionConfigFingerprint=hash;AreionWizardComplete=true;++AreionSetupRevision;
    if(!areion_setup_persist()) return {false,"FINAL_SAVE_FAILED"};
    AreionSetupLocked=false;AreionWizardStage=0;AreionSetupFault="";areion_reset_input(true);
    return {true,"SETUP_SAVED_ARM_AVAILABLE"};
  }
  if(!confirm) return {false,"SETUP_CONFIRM_REQUIRED"};
  if(cmd=="SENSOR_OK") {
    if(!areion_imu_ready(now) || !areion_setup_saved_matches(6)) return {false,"SAVE_VALID_IMU_OFFSETS_FIRST"};
    AreionSensorVerified=true;
  } else if(cmd=="RX_OK") {
    if(AreionBootSource!=0 || !AreionRawFresh || !areion_setup_valid_mapping()
       || !areion_setup_saved_matches(132) || !areion_setup_saved_matches(134)) return {false,"RX_SETTINGS_OR_SIGNAL"};
    for(int i=0;i<4;++i) if(AreionAxisChannels[i]>AreionRawCount) return {false,"RX_CHANNEL_MISSING"};
    if(FlightModeChannel>AreionRawCount) return {false,"MODE_CHANNEL_MISSING"};
    float values[8];areion_setup_ppm_normalize(values);
    if(!areion_neutral_frame(values)) return {false,"RX_NOT_NEUTRAL"};
    AreionReceiverVerified=true;
  } else if(cmd=="FAILSAFE_OK") {
    // Optional legacy action only. It is not a completion/arming prerequisite.
    if(AreionBootSource==0 && (!AreionSeenPpmLoss || !AreionRawFresh)) return {false,"TEST_RX_LOSS_AND_RECOVERY"};
    AreionFailsafeVerified=true;
  } else if(cmd=="ESC_SCHEDULE") {
    if(!AreionSensorVerified || (AreionBootSource==0 && !AreionReceiverVerified)) return {false,"CALIBRATE_SENSOR_AND_RX_FIRST"};
    AreionEscState=1;AreionWizardStage=2;AreionMotorVerifiedMask=0;AreionMotorTestedMask=0;
  } else if(cmd=="ESC_VERIFY") {
    if(AreionEscState!=3) return {false,"RUN_ESC_SEQUENCE_FIRST"};
    AreionEscState=4;AreionWizardStage=1;
  } else if(cmd=="ESC_SKIP") {
    if(!AreionSensorVerified || (AreionBootSource==0 && !AreionReceiverVerified)) return {false,"CALIBRATE_SENSOR_AND_RX_FIRST"};
    AreionEscState=5;AreionWizardStage=1;AreionMotorVerifiedMask=0;
  } else return {false,"SETUP_UNKNOWN_ACTION"};
  AreionSetupFault="";
  return areion_setup_commit("SETUP_UPDATED");
}
static bool areion_setup_bind() {
#ifdef ARDUINO_ARCH_ESP32
  char kit[32];snprintf(kit,sizeof(kit),"A1-%012llX",static_cast<unsigned long long>(ESP.getEfuseMac()));AreionKitId=kit;
#else
  AreionKitId="A1-HOST-TEST";
#endif
  AreionSetupStatus.add(AreionSetupLocked).add(AreionWizardComplete).add(AreionWizardStage).add(AreionEscState)
    .add(AreionMotorVerifiedMask).add(AreionSensorVerified).add(AreionReceiverVerified).add(AreionFailsafeVerified)
    .add(AreionMotorTestActive);
  for(int i=0;i<4;++i) AreionSetupStatus.add(AreionTestUs[i]);
  AreionSetupStatus.add(AreionSetupRevision).add(AreionSetupFault,128).add(AreionKitId,48);
  for(int i=0;i<8;++i) AreionRawPPM.add(AreionRawValues[i]);
  AreionRawPPM.add(AreionRawCount).add(AreionRawFresh).add(AreionRawAge);
  for(int i=0;i<8;++i) AreionRxCalibration.add(AreionRxCal[i][0],900,1500).add(AreionRxCal[i][1],900,2100)
    .add(AreionRxCal[i][2],1500,2100).add(AreionRxCal[i][3],0,1);
  AreionRxCalibration.validateWith([](const std::vector<areion::Value>& v) {
    for(size_t i=0;i<8;++i) {
      int64_t low=v[i*4].integer,mid=v[i*4+1].integer,high=v[i*4+2].integer;
      if(high-low<400 || mid-low<100 || high-mid<100) return false;
    }
    return true;
  }).onApplied([] {areion_reset_input();});
  AreionSetupConfig.add(AreionProfile,0,3).add(AreionBootSource,0,2);
  for(int i=0;i<4;++i) AreionSetupConfig.add(AreionAxisChannels[i],1,8);
  AreionSetupConfig.add(AreionDeadband,0,50);
  for(int i=0;i<4;++i) AreionSetupConfig.add(AreionMotorIdle[i],1000,1500);
  AreionSetupConfig.validateWith([](const std::vector<areion::Value>& v) {
    if(v[1].integer!=0 && FlightModeChannel<5) return false;
    for(int i=2;i<6;++i) for(int j=2;j<i;++j) if(v[size_t(i)].integer==v[size_t(j)].integer) return false;
    return true;
  }).onApplied([] {
    AreionInputSource=AreionBootSource;receiver.setControlFromSerial(AreionInputSource==2);
    receiver.setControlFromUDP(AreionInputSource==1);areion_reset_input(true);
  });
  AreionPidStatus.add(AreionPidPending).add(AreionPidRevision).add(AreionPidSavedRevision).add(AreionPidError,128);
  receiver.engine().onBeforeSet(areion_setup_before_set);
  return receiver.addGroup(AreionSetupStatus) && receiver.addGroup(AreionRawPPM)
    && receiver.addGroup(AreionRxCalibration) && receiver.addGroup(AreionSetupConfig)
    && receiver.addGroup(AreionPidStatus)
    && receiver.engine().addAction(135,1,areion_setup_action)
    && receiver.engine().addAction(137,1,areion_pid_action);
}
