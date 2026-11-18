#include "gate/SensorDecoder.hpp"

namespace gateway {
namespace gate {

namespace {

class RogerB70Decoder final : public ISensorDecoder {
public:
    GateState decode(const SensorContext& ctx) const override {
        // B70/1DC 8(+SC): 0V = closed, blinking (~0.5-1 Hz) = moving, steady 24V = open.
        const std::uint64_t blink_win = ctx.sensor_cfg.sc_blink_timeout_ms;
        const bool recently_toggled =
            ctx.in1_last_edge_ms != 0 && (ctx.now_ms - ctx.in1_last_edge_ms) < blink_win;

        if (recently_toggled) {
            const std::uint64_t move_win = static_cast<std::uint64_t>(ctx.relay_cfg.travel_time_ms) + 5000ULL;
            if (ctx.last_cmd_dir != CommandDirection::None && (ctx.now_ms - ctx.last_cmd_ms) < move_win) {
                return ctx.last_cmd_dir == CommandDirection::Opening ? GateState::Opening
                                                                     : GateState::Closing;
            }
            return ctx.last_static_state == GateState::Open ? GateState::Closing : GateState::Opening;
        }

        if (!ctx.in1_logical) {
            return GateState::Closed;
        }
        if (ctx.in2_logical && !ctx.sensor_cfg.cor_indicates_open) {
            return GateState::Closed;
        }
        return GateState::Open;
    }
};

class SingleReedDecoder final : public ISensorDecoder {
public:
    GateState decode(const SensorContext& ctx) const override {
        return ctx.in1_logical ? GateState::Closed : GateState::Open;
    }
};

class DualLimitDecoder final : public ISensorDecoder {
public:
    GateState decode(const SensorContext& ctx) const override {
        if (ctx.in1_logical && ctx.in2_logical) {
            return GateState::Fault;
        }
        if (ctx.in1_logical) {
            return GateState::Closed;
        }
        if (ctx.in2_logical) {
            return GateState::Open;
        }
        if (ctx.last_cmd_ms != 0 && (ctx.now_ms - ctx.last_cmd_ms) < ctx.relay_cfg.travel_time_ms) {
            return ctx.last_cmd_dir == CommandDirection::Closing ? GateState::Closing : GateState::Opening;
        }
        return GateState::PartiallyOpen;
    }
};

class TimerFallbackDecoder final : public ISensorDecoder {
public:
    GateState decode(const SensorContext& ctx) const override {
        if (ctx.last_cmd_ms == 0) {
            return GateState::Closed;
        }
        if ((ctx.now_ms - ctx.last_cmd_ms) < ctx.relay_cfg.travel_time_ms) {
            return ctx.last_cmd_dir == CommandDirection::Closing ? GateState::Closing : GateState::Opening;
        }
        return ctx.last_cmd_dir == CommandDirection::Closing ? GateState::Closed : GateState::Open;
    }
};

}  // namespace

std::unique_ptr<ISensorDecoder> makeSensorDecoder(core::SensorMode mode) {
    switch (mode) {
    case core::SensorMode::RogerB70:
        return std::make_unique<RogerB70Decoder>();
    case core::SensorMode::SingleReed:
        return std::make_unique<SingleReedDecoder>();
    case core::SensorMode::DualLimit:
        return std::make_unique<DualLimitDecoder>();
    case core::SensorMode::TimerFallback:
        return std::make_unique<TimerFallbackDecoder>();
    }
    return std::make_unique<RogerB70Decoder>();
}

}  // namespace gate
}  // namespace gateway
