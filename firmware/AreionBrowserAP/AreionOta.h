#pragma once
#include <esp_ota_ops.h>
#include <mbedtls/sha256.h>

// All state belongs to the flight loop. Link v2 validates the owner and sequence
// before dispatch, and the transport accepts this action only from the AP gateway.
namespace areion_ota {
constexpr uint8_t bootPin=9;
constexpr size_t chunkBytes=512,slotBytes=0x140000;
enum class Phase { Idle, Receiving, Restart };
static Phase phase=Phase::Idle;
static esp_ota_handle_t handle=0;
static const esp_partition_t* target=nullptr;
static mbedtls_sha256_context hash;
static uint8_t expectedHash[32];
static size_t written=0,total=0;
static uint32_t owner=0,last=0;
static bool busy(){return phase!=Phase::Idle;}

static int digit(char c) {
  if(c>='0'&&c<='9')return c-'0';
  if(c>='a'&&c<='f')return c-'a'+10;
  return -1;
}
static bool decode(const std::string& text,uint8_t* output,size_t bytes) {
  if(text.size()!=2*bytes)return false;
  for(size_t i=0;i<bytes;++i){
    const int hi=digit(text[2*i]),lo=digit(text[2*i+1]);
    if(hi<0||lo<0)return false;
    output[i]=uint8_t((hi<<4)|lo);
  }
  return true;
}
static void cancel() {
  if(phase!=Phase::Receiving)return;
  esp_ota_abort(handle);
  mbedtls_sha256_free(&hash);
  phase=Phase::Idle;owner=0;
  areion_reset_input(true);
}
static areion::ActionResult reject(const char* code){cancel();return {false,code};}

static areion::ActionResult command(const std::vector<areion::Value>& data,uint32_t now) {
  using areion::ValueType;
  if(data.empty()||data[0].type!=ValueType::String)return {false,"OTA_ARGUMENT"};
  const auto& op=data[0].text;
  const auto session=receiver.engine().ownerSession();
  if(op=="BEGIN"){
    if(busy()||AreionGyro.busy()||Armed||AreionMotorTestActive||AreionPidPending||AreionEscBootMode||AreionEscState==1||AreionEscState==2)
      return {false,"OTA_DISARM_AND_STOP_TESTS"};
    if(!session||digitalRead(bootPin)!=LOW)return {false,"OTA_HOLD_BOOT"};
    if(data.size()!=3||data[1].type!=ValueType::Integer||data[1].integer<32||data[1].integer>slotBytes
       ||data[2].type!=ValueType::String||!decode(data[2].text,expectedHash,sizeof(expectedHash)))return {false,"OTA_ARGUMENT"};
    const auto* running=esp_ota_get_running_partition();
    target=esp_ota_get_next_update_partition(nullptr);
    if(!running||!target||target->size!=slotBytes||running->size!=slotBytes||
       !((running->address==0x10000&&target->address==0x150000)||(running->address==0x150000&&target->address==0x10000)))
      return {false,"OTA_LAYOUT"};
    areion_setup_output_minimum();areion_reset_input(true);
    if(esp_ota_begin(target,OTA_WITH_SEQUENTIAL_WRITES,&handle)!=ESP_OK)return {false,"OTA_START_FAILED"};
    ImuReadOK=false;AreionRebaseAttitude=true;
    phase=Phase::Receiving;owner=session;last=now;written=0;total=size_t(data[1].integer);
    mbedtls_sha256_init(&hash);
    if(mbedtls_sha256_starts(&hash,0)!=0)return reject("OTA_HASH_FAILED");
    return {true,"OTA_READY"};
  }
  if(phase!=Phase::Receiving||!session||owner!=session)return {false,"OTA_NO_TRANSFER"};
  if(op=="ABORT"&&data.size()==1){cancel();return {true,"OTA_ABORTED"};}
  if(op=="DATA"){
    if(data.size()<3||data.size()>10||data[1].type!=ValueType::Integer||data[1].integer!=int64_t(written))
      return reject("OTA_OFFSET");
    uint8_t bytes[chunkBytes];size_t count=0;
    for(size_t i=2;i<data.size();++i){
      const auto& field=data[i];
      const size_t n=field.text.size()/2;
      if(field.type!=ValueType::String||n==0||n>64||count+n>sizeof(bytes)||!decode(field.text,bytes+count,n))
        return reject("OTA_BAD_CHUNK");
      count+=n;
    }
    if(count!=std::min(chunkBytes,total-written))return reject("OTA_LENGTH");
    if(!written&&(count<24||bytes[0]!=0xe9||bytes[12]!=13||bytes[13]!=0))return reject("OTA_WRONG_CHIP");
    if(esp_ota_write(handle,bytes,count)!=ESP_OK||mbedtls_sha256_update(&hash,bytes,count)!=0)return reject("OTA_WRITE_FAILED");
    written+=count;last=now;
    return {true,std::string("OTA_OFFSET_")+std::to_string(written)};
  }
  if(op!="FINISH"||data.size()!=1||written!=total)return reject("OTA_INCOMPLETE");
  uint8_t actual[32];
  if(mbedtls_sha256_finish(&hash,actual)!=0||memcmp(actual,expectedHash,sizeof(actual))!=0)return reject("OTA_HASH_FAILED");
  mbedtls_sha256_free(&hash);
  // esp_ota_end consumes its handle on either result and validates the ESP image.
  phase=Phase::Idle;owner=0;
  if(esp_ota_end(handle)!=ESP_OK)return {false,"OTA_IMAGE_INVALID"};
  if(esp_ota_set_boot_partition(target)!=ESP_OK)return {false,"OTA_SELECT_FAILED"};
  phase=Phase::Restart;last=millis();
  return {true,"OTA_RESTART"};
}
static void tick(uint32_t now){
  if(phase==Phase::Receiving&&(uint32_t(now-last)>5000||receiver.engine().ownerSession()!=owner))cancel();
  if(phase==Phase::Restart&&uint32_t(now-last)>1500&&digitalRead(bootPin)==HIGH)ESP.restart();
}
} // namespace areion_ota
