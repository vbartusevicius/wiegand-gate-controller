#pragma once

#include <string>

#include "access/AccessStore.hpp"
#include "core/Config.hpp"

namespace gateway {
namespace firmware {

class Storage {
public:
    bool init();
    bool loadConfig(core::DeviceConfig& cfg);
    bool saveConfig(const core::DeviceConfig& cfg);

    bool loadUsers(access::AccessStore& store);
    bool saveUsers(const access::AccessStore& store);

    void factoryReset();

private:
    bool spiffs_ok_{false};
};

}  // namespace firmware
}  // namespace gateway
