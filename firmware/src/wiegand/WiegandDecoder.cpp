#include "wiegand/WiegandDecoder.hpp"

#include <cstdio>

namespace gateway {
namespace wiegand {

namespace {

int popcount(std::uint64_t x) {
    int count = 0;
    while (x != 0) {
        count += static_cast<int>(x & 1U);
        x >>= 1U;
    }
    return count;
}

}  // namespace

void WiegandDecoder::reset() {
    shift_ = 0;
    bit_count_ = 0;
    last_bit_us_ = 0;
    pin_buf_.clear();
    last_key_us_ = 0;
}

void WiegandDecoder::onBit(std::uint8_t bit, std::uint64_t now_us) {
    if (bit_count_ > 0 && (now_us - last_bit_us_) > kFrameGapUs) {
        flushFrame(last_bit_us_);
    }
    if (bit_count_ < kMaxBits) {
        shift_ = (shift_ << 1U) | (bit != 0 ? 1ULL : 0ULL);
        ++bit_count_;
    }
    last_bit_us_ = now_us;
}

void WiegandDecoder::tick(std::uint64_t now_us) {
    if (bit_count_ > 0 && (now_us - last_bit_us_) >= kFrameGapUs) {
        flushFrame(now_us);
    }
    if (!pin_buf_.empty() && cfg_.pin_timeout_ms > 0) {
        const std::uint64_t timeout_us = static_cast<std::uint64_t>(cfg_.pin_timeout_ms) * 1000ULL;
        if ((now_us - last_key_us_) >= timeout_us) {
            pin_buf_.clear();
        }
    }
}

bool WiegandDecoder::checkSplitParity(std::uint64_t raw, std::uint8_t half_bits) {
    const std::uint64_t mask = (1ULL << half_bits) - 1ULL;
    const std::uint64_t upper = (raw >> half_bits) & mask;
    const std::uint64_t lower = raw & mask;
    return (popcount(upper) % 2 == 0) && (popcount(lower) % 2 == 1);
}

void WiegandDecoder::parseStandardCard(WiegandEvent& ev, std::uint8_t half_bits, std::uint64_t payload_mask,
                                       std::uint32_t facility_mask) {
    ev.parity_ok = checkSplitParity(ev.raw, half_bits);
    const auto payload = static_cast<std::uint32_t>((ev.raw >> 1U) & payload_mask);
    ev.facility = (payload >> 16U) & facility_mask;
    ev.card_number = payload & 0xFFFFU;
    ev.code = std::to_string(payload);
    if (!ev.parity_ok) {
        ev.kind = WiegandEvent::Kind::BadParity;
    }
}

std::string WiegandDecoder::toHex(std::uint64_t raw, std::uint8_t bits) {
    const std::uint8_t hex_digits = static_cast<std::uint8_t>((bits + 3U) / 4U);
    char buf[20]{};
    std::snprintf(buf, sizeof(buf), "%0*llX", static_cast<int>(hex_digits),
                  static_cast<unsigned long long>(raw));
    return std::string(buf);
}

void WiegandDecoder::flushFrame(std::uint64_t now_us) {
    const std::uint64_t raw = shift_;
    const std::uint8_t bits = bit_count_;
    shift_ = 0;
    bit_count_ = 0;

    if (bits == 4 && cfg_.keypad_enabled) {
        emitKey(static_cast<std::uint8_t>(raw & 0x0FU), now_us);
        return;
    }
    if (bits == 8 && cfg_.keypad_enabled) {
        // 8-bit Wiegand keypad: high nibble is complement of low nibble
        const auto low = static_cast<std::uint8_t>(raw & 0x0FU);
        const auto high = static_cast<std::uint8_t>((raw >> 4U) & 0x0FU);
        if ((low ^ high) == 0x0FU) {
            emitKey(low, now_us);
            return;
        }
    }

    if (bits < 8) {
        return;  // Ignore stray noise glitches
    }
    if (cfg_.wiegand_bits != 0 && bits != cfg_.wiegand_bits) {
        return;
    }

    WiegandEvent ev;
    ev.bits = bits;
    ev.raw = raw;
    ev.kind = WiegandEvent::Kind::Card;

    if (bits == 26) {
        parseStandardCard(ev, 13, 0xFFFFFFULL, 0xFFU);
    } else if (bits == 34) {
        parseStandardCard(ev, 17, 0xFFFFFFFFULL, 0xFFFFU);
    } else {
        ev.code = toHex(raw, bits);
    }

    if (callback_) {
        callback_(ev);
    }
}

void WiegandDecoder::emitKeyEvent(std::uint8_t key, std::string code) {
    if (!callback_) {
        return;
    }
    WiegandEvent ev;
    ev.kind = WiegandEvent::Kind::KeyPress;
    ev.bits = 4;
    ev.raw = key;
    ev.code = std::move(code);
    callback_(ev);
}

void WiegandDecoder::emitKey(std::uint8_t key, std::uint64_t now_us) {
    last_key_us_ = now_us;
    if (key <= 9U) {
        const char ch = static_cast<char>('0' + key);
        if (pin_buf_.size() < cfg_.pin_max_len) {
            pin_buf_.push_back(ch);
        }
        emitKeyEvent(key, std::string(1, ch));
        return;
    }

    if (key == 10U) {  // '*' / ESC -> clear
        pin_buf_.clear();
        emitKeyEvent(key, "*");
        return;
    }

    if (key == 11U) {  // '#' / ENT -> submit
        if (pin_buf_.size() >= cfg_.pin_min_len) {
            emitPin();
        } else {
            pin_buf_.clear();
        }
    }
}

void WiegandDecoder::emitPin() {
    WiegandEvent ev;
    ev.kind = WiegandEvent::Kind::Pin;
    ev.code = pin_buf_;
    pin_buf_.clear();
    if (callback_) {
        callback_(ev);
    }
}

}  // namespace wiegand
}  // namespace gateway
