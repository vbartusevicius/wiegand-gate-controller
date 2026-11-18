#pragma once

#include <cstdint>

namespace gateway {
namespace gate {

class RelayChannel {
public:
    void pulse(std::uint64_t now_ms, std::uint32_t duration_ms) {
        hold_open_ = false;
        active_ = true;
        off_at_ms_ = now_ms + duration_ms;
    }

    void holdOn() {
        hold_open_ = true;
        active_ = true;
        off_at_ms_ = 0;
    }

    void release() {
        hold_open_ = false;
        active_ = false;
        off_at_ms_ = 0;
    }

    void tick(std::uint64_t now_ms) {
        if (active_ && !hold_open_ && off_at_ms_ != 0 && now_ms >= off_at_ms_) {
            active_ = false;
            off_at_ms_ = 0;
        }
    }

    bool active() const { return active_; }
    bool holdOpen() const { return hold_open_; }

private:
    bool active_{false};
    bool hold_open_{false};
    std::uint64_t off_at_ms_{0};
};

struct RelayPair {
    RelayChannel primary;
    RelayChannel secondary;

    void tick(std::uint64_t now_ms) {
        primary.tick(now_ms);
        secondary.tick(now_ms);
    }

    void releaseAll() {
        primary.release();
        secondary.release();
    }
};

}  // namespace gate
}  // namespace gateway
