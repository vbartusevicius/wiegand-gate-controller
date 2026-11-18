#include "gate/RelayPolicy.hpp"

namespace gateway {
namespace gate {

namespace {

class BaseRelayPolicy : public IRelayPolicy {
protected:
    static void openOrUnlock(const core::RelayConfig& cfg, RelayPair& relays, std::uint64_t now_ms,
                             CommandDirection& dir) {
        dir = CommandDirection::Opening;
        if (cfg.relay1_hold_open) {
            relays.primary.holdOn();
        } else {
            relays.primary.pulse(now_ms, cfg.relay1_pulse_ms);
        }
    }

    static void triggerPedestrian(const core::RelayConfig& cfg, RelayPair& relays, std::uint64_t now_ms,
                                  CommandDirection& dir) {
        dir = CommandDirection::Opening;
        relays.secondary.pulse(now_ms, cfg.relay2_pulse_ms);
    }

    static void releaseHoldOrStop(RelayPair& relays) { relays.releaseAll(); }
};

class GateDualPolicy final : public BaseRelayPolicy {
public:
    void execute(GateCommand cmd, GateState state, const core::RelayConfig& cfg, RelayPair& relays,
                 std::uint64_t now_ms, CommandDirection& dir) const override {
        switch (cmd) {
        case GateCommand::TriggerPrimary:
            if (state == GateState::Open || state == GateState::Opening) {
                dir = CommandDirection::Closing;
                relays.secondary.pulse(now_ms, cfg.relay2_pulse_ms);
            } else {
                dir = CommandDirection::Opening;
                relays.primary.pulse(now_ms, cfg.relay1_pulse_ms);
            }
            break;
        case GateCommand::Open:
        case GateCommand::Unlock:
            openOrUnlock(cfg, relays, now_ms, dir);
            break;
        case GateCommand::Close:
        case GateCommand::Lock:
            dir = CommandDirection::Closing;
            relays.primary.release();
            relays.secondary.pulse(now_ms, cfg.relay2_pulse_ms);
            break;
        case GateCommand::Stop:
            releaseHoldOrStop(relays);
            break;
        case GateCommand::Pedestrian:
            triggerPedestrian(cfg, relays, now_ms, dir);
            break;
        }
    }
};

class GatePulsePolicy final : public BaseRelayPolicy {
public:
    void execute(GateCommand cmd, GateState state, const core::RelayConfig& cfg, RelayPair& relays,
                 std::uint64_t now_ms, CommandDirection& dir) const override {
        switch (cmd) {
        case GateCommand::TriggerPrimary:
            dir = (state == GateState::Open || state == GateState::Opening) ? CommandDirection::Closing
                                                                            : CommandDirection::Opening;
            relays.primary.pulse(now_ms, cfg.relay1_pulse_ms);
            break;
        case GateCommand::Open:
        case GateCommand::Unlock:
            openOrUnlock(cfg, relays, now_ms, dir);
            break;
        case GateCommand::Close:
        case GateCommand::Lock:
            dir = CommandDirection::Closing;
            if (cfg.relay1_hold_open) {
                relays.primary.release();
            } else if (state == GateState::Open || state == GateState::PartiallyOpen ||
                       state == GateState::Opening) {
                relays.primary.pulse(now_ms, cfg.relay1_pulse_ms);
            }
            break;
        case GateCommand::Stop:
            relays.primary.pulse(now_ms, cfg.relay1_pulse_ms);
            break;
        case GateCommand::Pedestrian:
            triggerPedestrian(cfg, relays, now_ms, dir);
            break;
        }
    }
};

class DoorPolicy final : public BaseRelayPolicy {
public:
    void execute(GateCommand cmd, GateState, const core::RelayConfig& cfg, RelayPair& relays,
                 std::uint64_t now_ms, CommandDirection& dir) const override {
        switch (cmd) {
        case GateCommand::TriggerPrimary:
            dir = CommandDirection::Opening;
            relays.primary.pulse(now_ms, cfg.relay1_pulse_ms);
            break;
        case GateCommand::Open:
        case GateCommand::Unlock:
            openOrUnlock(cfg, relays, now_ms, dir);
            break;
        case GateCommand::Close:
        case GateCommand::Lock:
            dir = CommandDirection::Closing;
            if (cfg.relay1_hold_open) {
                relays.primary.release();
            }
            break;
        case GateCommand::Stop:
            releaseHoldOrStop(relays);
            break;
        case GateCommand::Pedestrian:
            triggerPedestrian(cfg, relays, now_ms, dir);
            break;
        }
    }
};

}  // namespace

std::unique_ptr<IRelayPolicy> makeRelayPolicy(core::DeviceMode mode) {
    switch (mode) {
    case core::DeviceMode::GateDual:
        return std::make_unique<GateDualPolicy>();
    case core::DeviceMode::GatePulse:
        return std::make_unique<GatePulsePolicy>();
    case core::DeviceMode::Door:
    case core::DeviceMode::DualDoor:
        return std::make_unique<DoorPolicy>();
    }
    return std::make_unique<GateDualPolicy>();
}

}  // namespace gate
}  // namespace gateway
