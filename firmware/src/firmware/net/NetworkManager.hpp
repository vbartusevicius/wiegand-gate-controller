#pragma once

#include <cstdint>
#include <functional>
#include <string>

#include "core/GatewayApp.hpp"
#include "core/GatewayEvents.hpp"
#include "firmware/storage/Storage.hpp"
#include "web/ApiJson.hpp"

namespace gateway {
namespace firmware {

class NetworkManager final : public core::IMqttPublisher {
public:
    using LockFn = std::function<void()>;
    using UnlockFn = std::function<void()>;
    using ConfigSavedFn = std::function<void()>;

    void init(core::GatewayApp* app, Storage* storage, std::string fw_version, LockFn lock, UnlockFn unlock,
              ConfigSavedFn on_cfg_saved);

    void startWifi(bool force_ap = false);
    void startMqtt();
    void stopMqtt();
    void startHttp();

    void publishMqtt(const mqtt::MqttMessage& msg) override;
    void publishDiscoveryAndState(float vin_v);
    void publishState(float vin_v);
    void setLatestVin(float vin_v) { latest_vin_ = vin_v; }

    web::RuntimeStatus runtimeStatus(float vin_v, std::uint64_t uptime_ms) const;
    bool wifiConnected() const { return wifi_connected_; }
    bool apMode() const { return ap_mode_; }
    bool mqttConnected() const { return mqtt_connected_; }
    const std::string& macHex() const { return mac_hex_; }

    core::GatewayApp* app() const { return app_; }
    Storage* storage() const { return storage_; }
    void lockApp() const {
        if (lock_) {
            lock_();
        }
    }
    void unlockApp() const {
        if (unlock_) {
            unlock_();
        }
    }
    void notifyConfigSaved() const {
        if (on_cfg_saved_) {
            on_cfg_saved_();
        }
    }

    void onWifiConnected();
    void onWifiDisconnected();
    void onMqttConnected();
    void onMqttDisconnected();
    void onMqttData(const std::string& topic, const std::string& payload);

private:
    core::GatewayApp* app_{nullptr};
    Storage* storage_{nullptr};
    std::string fw_version_;
    LockFn lock_;
    UnlockFn unlock_;
    ConfigSavedFn on_cfg_saved_;

    std::string mac_hex_;
    std::string ip_str_;
    bool wifi_started_{false};
    bool wifi_connected_{false};
    bool ap_mode_{false};
    bool mqtt_connected_{false};
    void* mqtt_{nullptr};
    void* httpd_{nullptr};
    float latest_vin_{0.0F};
};

}  // namespace firmware
}  // namespace gateway
