#pragma once

#include <cstdint>
#include <string>

#include "access/AccessStore.hpp"
#include "core/Config.hpp"
#include "gate/GateController.hpp"

namespace gateway {
namespace web {

struct RuntimeStatus {
    std::string fw_version;
    std::uint64_t uptime_ms{0};
    float vin_v{0.0F};
    bool wifi_connected{false};
    bool ap_mode{false};
    std::string ip;
    std::string mac;
    int rssi_dbm{0};
    bool mqtt_connected{false};
    bool simulated{false};
    std::string active_antenna{"internal"};
};

class ApiJson {
public:
    static std::string buildStatus(const core::DeviceConfig& cfg, const RuntimeStatus& rt,
                                   const gate::GateController& gate, const access::AccessStore& store);

    static std::string buildConfig(const core::DeviceConfig& cfg);
    static bool applyConfigPatch(const std::string& json, core::DeviceConfig& cfg);

    static std::string buildUsers(const access::AccessStore& store);
    static bool parseUserUpsert(const std::string& json, access::UserEntry& user);

    static std::string buildEvents(const access::AccessStore& store);
};

}  // namespace web
}  // namespace gateway
