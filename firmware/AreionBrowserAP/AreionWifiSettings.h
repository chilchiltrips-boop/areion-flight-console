#pragma once
#include <nvs.h>
#include <cstring>

struct AreionWifiRecord {
  uint8_t version;
  char ssid[33];
  char password[64];
};
static areion::Group AreionWifiStatus(139,1);
static std::string AreionActiveSSID, AreionSavedSSID;
static bool AreionWifiConfigured=false, AreionWifiRestart=false;

static bool areion_wifi_valid(const std::string& name,const std::string& password) {
  if (name.empty() || name.size()>32 || password.size()<8 || password.size()>63) return false;
  for (unsigned char c : name) if (c<0x20 || c==0x7f) return false;
  for (unsigned char c : password) if (c<0x20 || c>0x7e) return false;
  return true;
}
static AreionWifiRecord areion_wifi_record(const std::string& ssid,const std::string& password) {
  AreionWifiRecord record{};
  record.version=1;
  ssid.copy(record.ssid,32);
  password.copy(record.password,63);
  return record;
}
static void areion_load_wifi(AreionWifiRecord& record) {
  nvs_handle_t h;
  size_t bytes=sizeof(record);
  esp_err_t result=nvs_open("areion-wifi",NVS_READONLY,&h);
  if (result==ESP_OK) {
    result=nvs_get_blob(h,"ap",&record,&bytes);
    nvs_close(h);
  }
  if (result==ESP_ERR_NVS_NOT_FOUND) record=areion_wifi_record(AREION_AP_SSID,AREION_AP_PASSWORD);
  else if (result!=ESP_OK || bytes!=sizeof(record)) record={};
  AreionWifiConfigured=record.version==1 && record.ssid[32]=='\0' && record.password[63]=='\0'
                    && areion_wifi_valid(record.ssid,record.password);
  AreionSavedSSID=AreionWifiConfigured?record.ssid:"";
}
static areion::ActionResult areion_wifi_change(const std::vector<areion::Value>& data,uint32_t) {
  if (Armed || AreionPidPending || AreionMotorTestActive || AreionEscBootMode || AreionEscState==1 || AreionEscState==2)
    return {false,"DISARM_AND_STOP_TESTS"};
  if (data.empty()) return {false,"AP_SETTINGS_INVALID"};
  for (const auto& item : data) if (item.type!=areion::ValueType::String) return {false,"AP_SETTINGS_INVALID"};
  const bool recovery=data[0].text=="RECOVER_AP";
  if (recovery ? data.size()!=2 : (data[0].text!="SET_AP" || data.size()!=3)) return {false,"AP_SETTINGS_INVALID"};
  const std::string name=recovery?AREION_AP_SSID:data[1].text;
  const std::string& password=data.back().text;
  if (!areion_wifi_valid(name,password)) return {false,"AP_SETTINGS_INVALID"};
  const auto record=areion_wifi_record(name,password);
  nvs_handle_t h;
  if (nvs_open("areion-wifi",NVS_READWRITE,&h)!=ESP_OK) return {false,"AP_STORAGE_FAILED"};
  AreionWifiRecord check{};
  size_t size=sizeof(check);
  bool ok=nvs_set_blob(h,"ap",&record,sizeof(record))==ESP_OK && nvs_commit(h)==ESP_OK &&
          nvs_get_blob(h,"ap",&check,&size)==ESP_OK && size==sizeof(record) &&
          std::memcmp(&record,&check,size)==0;
  nvs_close(h);
  if (!ok) return {false,"AP_STORAGE_FAILED"};
  AreionSavedSSID=name; AreionWifiConfigured=true; AreionWifiRestart=true;
  return {true,recovery?"AP_RECOVERED":"AP_SAVED"};
}
static bool areion_wifi_bind() {
  AreionWifiStatus.add(AreionActiveSSID,32).add(AreionSavedSSID,32).add(AreionWifiConfigured).add(AreionWifiRestart);
  return receiver.addGroup(AreionWifiStatus) && receiver.engine().addAction(138,1,areion_wifi_change);
}
