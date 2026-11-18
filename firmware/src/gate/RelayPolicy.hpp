#pragma once

#include <cstdint>
#include <memory>

#include "core/Config.hpp"
#include "gate/GateTypes.hpp"
#include "gate/RelayChannel.hpp"

namespace gateway {
namespace gate {

class IRelayPolicy {
public:
    virtual ~IRelayPolicy() = default;
    virtual void execute(GateCommand cmd, GateState state, const core::RelayConfig& cfg, RelayPair& relays,
                         std::uint64_t now_ms, CommandDirection& dir) const = 0;
};

std::unique_ptr<IRelayPolicy> makeRelayPolicy(core::DeviceMode mode);

}  // namespace gate
}  // namespace gateway
