#pragma once

#include <cstdint>

#include "core/Config.hpp"
#include "gate/GateTypes.hpp"

namespace gateway {
namespace gate {

class ReaderFeedbackPlayer {
public:
    void configure(const core::ReaderConfig& cfg) { cfg_ = cfg; }

    void triggerGranted(std::uint64_t now_ms);
    void triggerDenied(std::uint64_t now_ms);
    void tick(std::uint64_t now_ms);

    ReaderFeedback outputs() const;

private:
    enum class Kind : std::uint8_t {
        None,
        Granted,
        Denied
    };

    core::ReaderConfig cfg_{};
    Kind kind_{Kind::None};
    std::uint64_t start_ms_{0};
    bool led_logical_{false};
    bool beep_logical_{false};
};

}  // namespace gate
}  // namespace gateway
