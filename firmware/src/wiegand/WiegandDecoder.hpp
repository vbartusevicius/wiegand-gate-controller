#pragma once

#include <cstdint>
#include <functional>
#include <string>

#include "core/Config.hpp"

namespace gateway {
namespace wiegand {

struct WiegandEvent {
    enum class Kind : std::uint8_t {
        Card = 0,
        Pin = 1,
        KeyPress = 2,
        BadParity = 3,
    };

    Kind kind{Kind::Card};
    std::uint8_t bits{0};
    std::uint64_t raw{0};
    std::string code;  // Normalized card code (decimal or hex) or entered PIN
    std::uint32_t facility{0};
    std::uint32_t card_number{0};
    bool parity_ok{true};
};

class WiegandDecoder {
public:
    using Callback = std::function<void(const WiegandEvent&)>;

    static constexpr std::uint64_t kFrameGapUs = 25000;  // 25 ms silence completes a Wiegand frame
    static constexpr std::uint8_t kMaxBits = 64;

    void configure(const core::ReaderConfig& cfg) { cfg_ = cfg; }
    void setCallback(Callback cb) { callback_ = std::move(cb); }

    // Called from ISR-drained queue or test harness in chronological order
    void onBit(std::uint8_t bit, std::uint64_t now_us);

    // Periodic poll to flush completed Wiegand frames & PIN inactivity timeouts
    void tick(std::uint64_t now_us);

    void reset();

    const std::string& pendingPin() const { return pin_buf_; }

private:
    void flushFrame(std::uint64_t now_us);
    void emitKey(std::uint8_t key, std::uint64_t now_us);
    void emitKeyEvent(std::uint8_t key, std::string code);
    void emitPin();
    static bool checkSplitParity(std::uint64_t raw, std::uint8_t half_bits);
    static void parseStandardCard(WiegandEvent& ev, std::uint8_t half_bits, std::uint64_t payload_mask,
                                  std::uint32_t facility_mask);
    static std::string toHex(std::uint64_t raw, std::uint8_t bits);

    core::ReaderConfig cfg_{};
    Callback callback_;

    std::uint64_t shift_{0};
    std::uint8_t bit_count_{0};
    std::uint64_t last_bit_us_{0};

    std::string pin_buf_;
    std::uint64_t last_key_us_{0};
};

}  // namespace wiegand
}  // namespace gateway
