#pragma once

#include <cstdint>
#include <functional>
#include <memory>

#include "access/AccessStore.hpp"
#include "core/Config.hpp"
#include "gate/GateTypes.hpp"
#include "gate/ReaderFeedbackPlayer.hpp"
#include "gate/RelayChannel.hpp"
#include "gate/RelayPolicy.hpp"
#include "gate/SensorDecoder.hpp"

namespace gateway {
namespace gate {

class GateController {
public:
    using StateChangedCb = std::function<void(GateState prev, GateState next)>;
    using RexTriggerCb = std::function<void(bool pedestrian)>;

    GateController();

    void configure(const core::RelayConfig& relay_cfg, const core::SensorConfig& sensor_cfg,
                   const core::ReaderConfig& reader_cfg);

    void setSensorDecoder(std::unique_ptr<ISensorDecoder> decoder) { sensor_decoder_ = std::move(decoder); }
    void setRelayPolicy(std::unique_ptr<IRelayPolicy> policy) { relay_policy_ = std::move(policy); }

    void setStateChangedCallback(StateChangedCb cb) { on_state_changed_ = std::move(cb); }
    void setRexCallback(RexTriggerCb cb) { on_rex_ = std::move(cb); }

    void updateInputs(RawInputs raw, std::uint64_t now_ms);
    void tick(std::uint64_t now_ms);

    void executeCommand(GateCommand cmd, std::uint64_t now_ms);
    void executeAccessTarget(access::RelayTarget target, std::uint64_t now_ms);

    void triggerGrantedFeedback(std::uint64_t now_ms) { feedback_.triggerGranted(now_ms); }
    void triggerDeniedFeedback(std::uint64_t now_ms) { feedback_.triggerDenied(now_ms); }

    GateState state() const { return state_; }
    RelayOutputs relayOutputs() const;
    RelayOutputs logicalRelays() const { return {relays_.primary.active(), relays_.secondary.active()}; }
    ReaderFeedback readerFeedback() const { return feedback_.outputs(); }
    bool in1Active() const { return in1_logical_; }
    bool in2Active() const { return in2_logical_; }
    bool in3Active() const { return in3_logical_; }
    bool holdOpenActive() const { return relays_.primary.holdOpen(); }

private:
    void setState(GateState next);

    core::RelayConfig relay_cfg_{};
    core::SensorConfig sensor_cfg_{};

    std::unique_ptr<ISensorDecoder> sensor_decoder_;
    std::unique_ptr<IRelayPolicy> relay_policy_;
    RelayPair relays_{};
    ReaderFeedbackPlayer feedback_{};

    StateChangedCb on_state_changed_;
    RexTriggerCb on_rex_;

    GateState state_{GateState::Unknown};
    GateState last_static_state_{GateState::Closed};
    CommandDirection last_cmd_dir_{CommandDirection::None};

    bool in1_logical_{false};
    bool in2_logical_{false};
    bool in3_logical_{false};
    bool prev_in1_{false};
    bool prev_in3_{false};
    bool in1_initialized_{false};

    std::uint64_t in1_last_edge_ms_{0};
    std::uint64_t last_cmd_ms_{0};
};

}  // namespace gate
}  // namespace gateway
