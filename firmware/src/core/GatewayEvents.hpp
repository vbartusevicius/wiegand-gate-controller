#pragma once

#include <cstdint>
#include <string>

#include "gate/GateTypes.hpp"
#include "mqtt/HomeAssistantMqtt.hpp"

namespace gateway {
namespace core {

class IMqttPublisher {
public:
    virtual ~IMqttPublisher() = default;
    virtual void publishMqtt(const mqtt::MqttMessage& msg) = 0;
};

class IGatewayObserver {
public:
    virtual ~IGatewayObserver() = default;
    virtual void onAccessDecision(bool /*granted*/, const std::string& /*source*/,
                                  const std::string& /*user*/, const std::string& /*code*/,
                                  std::uint64_t /*now_ms*/) {}
    virtual void onUsersChanged() {}
    virtual void onGateStateChanged(gate::GateState /*prev*/, gate::GateState /*next*/,
                                    std::uint64_t /*now_ms*/) {}
};

}  // namespace core
}  // namespace gateway
