#include "firmware/storage/Storage.hpp"

#include <cstdio>

#include <ArduinoJson.h>
#include <esp_spiffs.h>
#include <nvs.h>
#include <nvs_flash.h>

#include "web/ApiJson.hpp"

namespace gateway {
namespace firmware {

namespace {
constexpr const char* kNvsNamespace = "wg_cfg";
constexpr const char* kNvsKeyJson = "cfg_json";
constexpr const char* kUsersPath = "/storage/users.json";
}  // namespace

bool Storage::init() {
    esp_err_t rc = nvs_flash_init();
    if (rc == ESP_ERR_NVS_NO_FREE_PAGES || rc == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        rc = nvs_flash_init();
    }
    if (rc != ESP_OK) {
        return false;
    }

    esp_vfs_spiffs_conf_t conf{};
    conf.base_path = "/storage";
    conf.partition_label = "storage";
    conf.max_files = 4;
    conf.format_if_mount_failed = true;
    spiffs_ok_ = (esp_vfs_spiffs_register(&conf) == ESP_OK);
    return true;
}

bool Storage::loadConfig(core::DeviceConfig& cfg) {
    nvs_handle_t handle{};
    if (nvs_open(kNvsNamespace, NVS_READONLY, &handle) != ESP_OK) {
        return false;
    }
    std::size_t len = 0;
    if (nvs_get_str(handle, kNvsKeyJson, nullptr, &len) != ESP_OK || len == 0) {
        nvs_close(handle);
        return false;
    }
    std::string json(len, '\0');
    const esp_err_t rc = nvs_get_str(handle, kNvsKeyJson, json.data(), &len);
    nvs_close(handle);
    if (rc != ESP_OK) {
        return false;
    }
    if (!json.empty() && json.back() == '\0') {
        json.pop_back();
    }
    return web::ApiJson::applyConfigPatch(json, cfg);
}

bool Storage::saveConfig(const core::DeviceConfig& cfg) {
    // Store full config including passwords in NVS JSON
    JsonDocument doc;
    if (deserializeJson(doc, web::ApiJson::buildConfig(cfg)) != DeserializationError::Ok) {
        return false;
    }
    doc["wifi"]["password"] = cfg.wifi.password;
    doc["mqtt"]["password"] = cfg.mqtt.password;
    std::string raw;
    serializeJson(doc, raw);

    nvs_handle_t handle{};
    if (nvs_open(kNvsNamespace, NVS_READWRITE, &handle) != ESP_OK) {
        return false;
    }
    const bool ok =
        (nvs_set_str(handle, kNvsKeyJson, raw.c_str()) == ESP_OK) && (nvs_commit(handle) == ESP_OK);
    nvs_close(handle);
    return ok;
}

bool Storage::loadUsers(access::AccessStore& store) {
    if (!spiffs_ok_) {
        return false;
    }
    FILE* f = std::fopen(kUsersPath, "rb");
    if (f == nullptr) {
        return false;
    }
    std::string raw;
    char buf[256];
    while (true) {
        const std::size_t n = std::fread(buf, 1, sizeof(buf), f);
        if (n == 0) {
            break;
        }
        raw.append(buf, n);
    }
    std::fclose(f);
    return store.deserializeUsersJson(raw);
}

bool Storage::saveUsers(const access::AccessStore& store) {
    if (!spiffs_ok_) {
        return false;
    }
    const std::string raw = store.serializeUsersJson();
    FILE* f = std::fopen(kUsersPath, "wb");
    if (f == nullptr) {
        return false;
    }
    const std::size_t written = std::fwrite(raw.data(), 1, raw.size(), f);
    std::fclose(f);
    return written == raw.size();
}

void Storage::factoryReset() {
    nvs_flash_erase();
    if (spiffs_ok_) {
        std::remove(kUsersPath);
    }
}

}  // namespace firmware
}  // namespace gateway
