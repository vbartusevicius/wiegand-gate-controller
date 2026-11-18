#include "firmware/drivers/RestartButtonDriver.hpp"

#include <driver/gpio.h>

#include "firmware/Board.hpp"

namespace gateway {
namespace firmware {

bool RestartButtonDriver::init() {
    gpio_config_t btn_cfg{};
    btn_cfg.pin_bit_mask = (1ULL << board::btn_restart_pin);
    btn_cfg.mode = GPIO_MODE_INPUT;
    btn_cfg.pull_up_en = GPIO_PULLUP_ENABLE;
    btn_cfg.pull_down_en = GPIO_PULLDOWN_DISABLE;
    btn_cfg.intr_type = GPIO_INTR_DISABLE;
    return gpio_config(&btn_cfg) == ESP_OK;
}

core::ButtonAction RestartButtonDriver::poll(std::uint64_t now_ms) {
    const bool down = gpio_get_level(board::btn_restart_pin) == 0;
    return button_.poll(down, now_ms);
}

}  // namespace firmware
}  // namespace gateway
