#pragma once

#include <cstdint>

#include "gate/GateController.hpp"

namespace gateway {
namespace firmware {

class RgbStatus {
public:
    bool init();
    void update(bool wifi_ok, bool ap_mode, bool mqtt_ok, gate::GateState gate_state, std::uint64_t now_ms);
    void flashAuth(bool granted, std::uint64_t now_ms);

private:
    void* strip_{nullptr};
    std::uint64_t auth_until_ms_{0};
    bool auth_granted_{false};
};

}  // namespace firmware
}  // namespace gateway
