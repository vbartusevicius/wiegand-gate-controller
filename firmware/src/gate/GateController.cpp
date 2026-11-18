#include "gate/GateController.hpp"

namespace gateway {
namespace gate {

GateController::GateController()
    : sensor_decoder_(makeSensorDecoder(sensor_cfg_.mode)), relay_policy_(makeRelayPolicy(relay_cfg_.mode)) {}

void GateController::configure(const core::RelayConfig& relay_cfg, const core::SensorConfig& sensor_cfg,
                               const core::ReaderConfig& reader_cfg) {
    if (relay_cfg.mode != relay_cfg_.mode || relay_policy_ == nullptr) {
        relay_policy_ = makeRelayPolicy(relay_cfg.mode);
    }
    if (sensor_cfg.mode != sensor_cfg_.mode || sensor_decoder_ == nullptr) {
        sensor_decoder_ = makeSensorDecoder(sensor_cfg.mode);
    }
    relay_cfg_ = relay_cfg;
    sensor_cfg_ = sensor_cfg;
    feedback_.configure(reader_cfg);
}

void GateController::setState(GateState next) {
    if (state_ == next) {
        return;
    }
    const GateState prev = state_;
    state_ = next;
    if (next == GateState::Closed || next == GateState::Open) {
        last_static_state_ = next;
    }
    if (on_state_changed_) {
        on_state_changed_(prev, next);
    }
}

void GateController::updateInputs(RawInputs raw, std::uint64_t now_ms) {
    in1_logical_ = sensor_cfg_.in1_inverted ? !raw.in1 : raw.in1;
    in2_logical_ = sensor_cfg_.in2_inverted ? !raw.in2 : raw.in2;
    in3_logical_ = sensor_cfg_.in3_inverted ? !raw.in3 : raw.in3;

    if (!in1_initialized_) {
        in1_initialized_ = true;
        prev_in1_ = in1_logical_;
        prev_in3_ = in3_logical_;
    }

    if (in1_logical_ != prev_in1_) {
        prev_in1_ = in1_logical_;
        in1_last_edge_ms_ = now_ms;
    }

    if (sensor_cfg_.in3_enabled && in3_logical_ && !prev_in3_) {
        executeCommand(sensor_cfg_.in3_pedestrian ? GateCommand::Pedestrian : GateCommand::TriggerPrimary,
                       now_ms);
        if (on_rex_) {
            on_rex_(sensor_cfg_.in3_pedestrian);
        }
    }
    prev_in3_ = in3_logical_;

    tick(now_ms);
}

void GateController::tick(std::uint64_t now_ms) {
    relays_.tick(now_ms);
    if (sensor_decoder_ != nullptr) {
        const SensorContext ctx{
            in1_logical_,       in2_logical_, in1_last_edge_ms_, last_cmd_ms_, last_cmd_dir_,
            last_static_state_, now_ms,       relay_cfg_,        sensor_cfg_,
        };
        setState(sensor_decoder_->decode(ctx));
    }
    feedback_.tick(now_ms);
}

void GateController::executeCommand(GateCommand cmd, std::uint64_t now_ms) {
    last_cmd_ms_ = now_ms;
    if (relay_policy_ != nullptr) {
        relay_policy_->execute(cmd, state_, relay_cfg_, relays_, now_ms, last_cmd_dir_);
    }
}

void GateController::executeAccessTarget(access::RelayTarget target, std::uint64_t now_ms) {
    switch (target) {
    case access::RelayTarget::Primary:
        executeCommand(GateCommand::TriggerPrimary, now_ms);
        break;
    case access::RelayTarget::Pedestrian:
        executeCommand(GateCommand::Pedestrian, now_ms);
        break;
    case access::RelayTarget::Both:
        executeCommand(GateCommand::TriggerPrimary, now_ms);
        relays_.secondary.pulse(now_ms, relay_cfg_.relay2_pulse_ms);
        break;
    }
}

RelayOutputs GateController::relayOutputs() const {
    return {
        relay_cfg_.relay1_inverted ? !relays_.primary.active() : relays_.primary.active(),
        relay_cfg_.relay2_inverted ? !relays_.secondary.active() : relays_.secondary.active(),
    };
}

}  // namespace gate
}  // namespace gateway
