#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "core/Config.hpp"
#include "gate/GateController.hpp"

namespace gateway {
namespace mqtt {

struct MqttMessage {
    std::string topic;
    std::string payload;
    bool retain{false};
};

class HomeAssistantMqtt {
public:
    static std::string nodeId(const std::string& mac_hex);

    std::vector<MqttMessage> buildDiscovery(const core::DeviceConfig& cfg, const std::string& node_id,
                                            const std::string& fw_version) const;

    MqttMessage buildState(const core::DeviceConfig& cfg, gate::GateState gate_state, float vin_v,
                           int rssi_dbm, const std::string& last_user, const std::string& last_code) const;

    MqttMessage buildAvailability(const core::DeviceConfig& cfg, bool online) const;
    MqttMessage buildTagEvent(const core::DeviceConfig& cfg, const std::string& code, const std::string& user,
                              bool granted) const;

    static std::string commandTopic(const core::DeviceConfig& cfg);
    static std::string availabilityTopic(const core::DeviceConfig& cfg);
};

}  // namespace mqtt
}  // namespace gateway
