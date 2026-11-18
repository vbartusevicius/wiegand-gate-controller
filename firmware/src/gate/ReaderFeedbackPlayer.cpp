#include "gate/ReaderFeedbackPlayer.hpp"

namespace gateway {
namespace gate {

void ReaderFeedbackPlayer::triggerGranted(std::uint64_t now_ms) {
    kind_ = Kind::Granted;
    start_ms_ = now_ms;
    tick(now_ms);
}

void ReaderFeedbackPlayer::triggerDenied(std::uint64_t now_ms) {
    kind_ = Kind::Denied;
    start_ms_ = now_ms;
    tick(now_ms);
}

void ReaderFeedbackPlayer::tick(std::uint64_t now_ms) {
    if (kind_ == Kind::None) {
        led_logical_ = false;
        beep_logical_ = false;
        return;
    }

    const std::uint64_t elapsed = now_ms - start_ms_;
    if (kind_ == Kind::Granted) {
        if (elapsed >= cfg_.granted_led_ms) {
            kind_ = Kind::None;
            led_logical_ = false;
            beep_logical_ = false;
        } else {
            led_logical_ = true;
            beep_logical_ = elapsed < cfg_.granted_beep_ms;
        }
        return;
    }

    // Denied: N short 100ms on / 100ms off beeps
    const std::uint64_t total_ms = static_cast<std::uint64_t>(cfg_.denied_beeps) * 200ULL;
    if (elapsed >= total_ms) {
        kind_ = Kind::None;
        led_logical_ = false;
        beep_logical_ = false;
    } else {
        beep_logical_ = ((elapsed / 100ULL) % 2ULL) == 0ULL;
        led_logical_ = false;
    }
}

ReaderFeedback ReaderFeedbackPlayer::outputs() const {
    // Hardware uses open-drain NPN: output pin HIGH drives NPN ON (pulls reader line LOW).
    // If reader expects active-high instead of active-low, flip accordingly.
    return {
        cfg_.led_active_low ? led_logical_ : !led_logical_,
        cfg_.beep_active_low ? beep_logical_ : !beep_logical_,
    };
}

}  // namespace gate
}  // namespace gateway
