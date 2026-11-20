#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "access/AccessStore.hpp"
#include "core/Config.hpp"
#include "core/GatewayEvents.hpp"
#include "gate/GateController.hpp"
#include "mqtt/HomeAssistantMqtt.hpp"
#include "wiegand/WiegandDecoder.hpp"

namespace gateway {
namespace core {

class GatewayApp {
public:
    GatewayApp();

    void applyConfig(const DeviceConfig& cfg);
    void setMqttPublisher(IMqttPublisher* pub) { mqtt_pub_ = pub; }
    void addObserver(IGatewayObserver* observer);

    void onWiegandBit(std::uint8_t bit, std::uint64_t now_us);
    void onWiegandEvent(const wiegand::WiegandEvent& ev, std::uint64_t now_ms);
    void onInputs(gate::RawInputs inputs, std::uint64_t now_ms);
    void onMqttCommand(const std::string& payload, std::uint64_t now_ms);
    void onManualCommand(gate::GateCommand cmd, const std::string& source, std::uint64_t now_ms);

    void tick(std::uint64_t now_ms, std::uint64_t now_us);

    DeviceConfig& mutableConfig() { return cfg_; }
    const DeviceConfig& config() const { return cfg_; }
    access::AccessStore& store() { return store_; }
    const access::AccessStore& store() const { return store_; }
    gate::GateController& gate() { return gate_; }
    const gate::GateController& gate() const { return gate_; }
    mqtt::HomeAssistantMqtt& haMqtt() { return ha_mqtt_; }

    const std::string& lastUser() const { return last_user_; }
    const std::string& lastCode() const { return last_code_; }

private:
    void notifyAccess(bool granted, const std::string& source, const std::string& user,
                      const std::string& code, std::uint64_t now_ms);
    void publishTag(const std::string& code, const std::string& user, bool granted);

    DeviceConfig cfg_{};
    access::AccessStore store_;
    wiegand::WiegandDecoder wiegand_;
    gate::GateController gate_;
    mqtt::HomeAssistantMqtt ha_mqtt_;

    IMqttPublisher* mqtt_pub_{nullptr};
    std::vector<IGatewayObserver*> observers_;
    std::uint64_t last_now_ms_{0};
    std::string last_user_;
    std::string last_code_;
    bool has_last_granted_card_{false};
    std::string last_granted_card_;
    std::uint64_t last_granted_card_ms_{0};
    bool has_last_denied_card_{false};
    std::string last_denied_card_;
    std::uint64_t last_denied_card_ms_{0};
};

}  // namespace core
}  // namespace gateway
