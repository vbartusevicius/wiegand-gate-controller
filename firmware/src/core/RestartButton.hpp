#pragma once

#include <cstdint>

namespace gateway {
namespace core {

enum class ButtonAction : std::uint8_t {
    None = 0,
    Restart = 1,
    SetupPortal = 2,
    FactoryReset = 3,
};

class RestartButton {
public:
    static constexpr std::uint64_t kDebounceMs = 50ULL;
    static constexpr std::uint64_t kSetupPortalMs = 4500ULL;
    static constexpr std::uint64_t kFactoryResetMs = 10000ULL;

    ButtonAction poll(bool is_down, std::uint64_t now_ms) {
        if (is_down && !pressed_) {
            pressed_ = true;
            press_start_ms_ = now_ms;
            return ButtonAction::None;
        }
        if (!is_down && pressed_) {
            pressed_ = false;
            const std::uint64_t held = now_ms - press_start_ms_;
            if (held >= kFactoryResetMs) {
                return ButtonAction::FactoryReset;
            }
            if (held >= kSetupPortalMs) {
                return ButtonAction::SetupPortal;
            }
            if (held >= kDebounceMs) {
                return ButtonAction::Restart;
            }
        }
        return ButtonAction::None;
    }

private:
    bool pressed_{false};
    std::uint64_t press_start_ms_{0};
};

}  // namespace core
}  // namespace gateway
