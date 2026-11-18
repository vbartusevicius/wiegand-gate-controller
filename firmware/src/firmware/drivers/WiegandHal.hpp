#pragma once

#include <cstdint>

#include "core/GatewayApp.hpp"

namespace gateway {
namespace firmware {

class WiegandHal {
public:
    bool init();
    void drain(core::GatewayApp& app);
};

}  // namespace firmware
}  // namespace gateway
