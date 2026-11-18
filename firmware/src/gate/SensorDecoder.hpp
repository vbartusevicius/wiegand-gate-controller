#pragma once

#include <cstdint>
#include <memory>

#include "core/Config.hpp"
#include "gate/GateTypes.hpp"

namespace gateway {
namespace gate {

struct SensorContext {
    bool in1_logical{false};
    bool in2_logical{false};
    std::uint64_t in1_last_edge_ms{0};
    std::uint64_t last_cmd_ms{0};
    CommandDirection last_cmd_dir{CommandDirection::None};
    GateState last_static_state{GateState::Closed};
    std::uint64_t now_ms{0};
    const core::RelayConfig& relay_cfg;
    const core::SensorConfig& sensor_cfg;
};

class ISensorDecoder {
public:
    virtual ~ISensorDecoder() = default;
    virtual GateState decode(const SensorContext& ctx) const = 0;
};

std::unique_ptr<ISensorDecoder> makeSensorDecoder(core::SensorMode mode);

}  // namespace gate
}  // namespace gateway
