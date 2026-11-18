#include "firmware/drivers/RgbStatus.hpp"

#include <led_strip.h>

#include "firmware/Board.hpp"

namespace gateway {
namespace firmware {

bool RgbStatus::init() {
    led_strip_config_t strip_cfg{};
    strip_cfg.strip_gpio_num = board::led_data_pin;
    strip_cfg.max_leds = 2;
    strip_cfg.color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB;
    strip_cfg.led_model = LED_MODEL_WS2812;
    strip_cfg.flags.invert_out = false;

    led_strip_rmt_config_t rmt_cfg{};
    rmt_cfg.clk_src = RMT_CLK_SRC_DEFAULT;
    rmt_cfg.resolution_hz = 10 * 1000 * 1000;

    led_strip_handle_t handle = nullptr;
    if (led_strip_new_rmt_device(&strip_cfg, &rmt_cfg, &handle) != ESP_OK) {
        return false;
    }
    strip_ = handle;
    led_strip_clear(handle);
    return true;
}

void RgbStatus::flashAuth(bool granted, std::uint64_t now_ms) {
    auth_granted_ = granted;
    auth_until_ms_ = now_ms + 1500ULL;
}

void RgbStatus::update(bool wifi_ok, bool ap_mode, bool mqtt_ok, gate::GateState gate_state,
                       std::uint64_t now_ms) {
    if (strip_ == nullptr) {
        return;
    }
    auto* handle = static_cast<led_strip_handle_t>(strip_);
    const bool blink = ((now_ms / 400ULL) % 2ULL) == 0ULL;

    // LED 0: Network & auth feedback
    std::uint8_t r0 = 0, g0 = 0, b0 = 0;
    if (now_ms < auth_until_ms_) {
        if (auth_granted_) {
            g0 = 32;
        } else {
            r0 = 40;
        }
    } else if (ap_mode) {
        b0 = blink ? 24 : 4;
        r0 = blink ? 12 : 0;
    } else if (wifi_ok && mqtt_ok) {
        g0 = 14;
    } else if (wifi_ok) {
        b0 = 16;
    } else {
        r0 = blink ? 18 : 2;
    }

    // LED 1: Gate / Door state
    std::uint8_t r1 = 0, g1 = 0, b1 = 0;
    switch (gate_state) {
    case gate::GateState::Closed:
        g1 = 12;
        break;
    case gate::GateState::Open:
    case gate::GateState::PartiallyOpen:
        r1 = 20;
        g1 = 12;
        break;
    case gate::GateState::Opening:
    case gate::GateState::Closing:
        b1 = blink ? 24 : 2;
        g1 = blink ? 16 : 0;
        break;
    case gate::GateState::Fault:
        r1 = blink ? 36 : 0;
        break;
    case gate::GateState::Unknown:
        r1 = 6;
        g1 = 6;
        b1 = 6;
        break;
    }

    led_strip_set_pixel(handle, 0, r0, g0, b0);
    led_strip_set_pixel(handle, 1, r1, g1, b1);
    led_strip_refresh(handle);
}

}  // namespace firmware
}  // namespace gateway
