#include "firmware/drivers/Pca9534.hpp"

#include <driver/i2c_master.h>

#include "firmware/Board.hpp"

namespace gateway {
namespace firmware {

namespace {
constexpr std::uint8_t kRegInput = 0x00;
constexpr std::uint8_t kRegOutput = 0x01;
constexpr std::uint8_t kRegPolarity = 0x02;
constexpr std::uint8_t kRegConfig = 0x03;
}  // namespace

bool Pca9534::init() {
    i2c_master_bus_config_t bus_cfg{};
    bus_cfg.i2c_port = I2C_NUM_0;
    bus_cfg.sda_io_num = board::i2c_sda_pin;
    bus_cfg.scl_io_num = board::i2c_scl_pin;
    bus_cfg.clk_source = I2C_CLK_SRC_DEFAULT;
    bus_cfg.glitch_ignore_cnt = 7;
    bus_cfg.flags.enable_internal_pullup = false;

    i2c_master_bus_handle_t bus_handle = nullptr;
    if (i2c_new_master_bus(&bus_cfg, &bus_handle) != ESP_OK) {
        return false;
    }
    bus_ = bus_handle;

    i2c_device_config_t dev_cfg{};
    dev_cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    dev_cfg.device_address = board::i2c_addr_pca9534;
    dev_cfg.scl_speed_hz = board::i2c_speed_hz;

    i2c_master_dev_handle_t dev_handle = nullptr;
    if (i2c_master_bus_add_device(bus_handle, &dev_cfg, &dev_handle) != ESP_OK) {
        return false;
    }
    dev_ = dev_handle;

    // P0..P3 outputs (relays + Wiegand LED/BEEP), P4..P7 inputs (IN1..IN3 + spare)
    if (!writeReg(kRegOutput, 0x00)) {
        return false;
    }
    if (!writeReg(kRegPolarity, 0x00)) {
        return false;
    }
    if (!writeReg(kRegConfig, 0xF0)) {
        return false;
    }
    last_out_ = 0x00;
    return true;
}

bool Pca9534::writeOutputs(bool relay1, bool relay2, bool wg_led, bool wg_beep) {
    std::uint8_t val = 0;
    if (relay1) {
        val |= static_cast<std::uint8_t>(1U << board::exp_bit_relay1);
    }
    if (relay2) {
        val |= static_cast<std::uint8_t>(1U << board::exp_bit_relay2);
    }
    if (wg_led) {
        val |= static_cast<std::uint8_t>(1U << board::exp_bit_wg_led);
    }
    if (wg_beep) {
        val |= static_cast<std::uint8_t>(1U << board::exp_bit_wg_beep);
    }
    if (val == last_out_) {
        return true;
    }
    if (!writeReg(kRegOutput, val)) {
        return false;
    }
    last_out_ = val;
    return true;
}

gate::RawInputs Pca9534::readInputs() {
    std::uint8_t val = 0xFF;
    if (!readReg(kRegInput, val)) {
        return {};
    }
    // Opto-isolated inputs pull PCA9534 pin LOW when energized.
    return {
        (val & (1U << board::exp_bit_in1)) == 0,
        (val & (1U << board::exp_bit_in2)) == 0,
        (val & (1U << board::exp_bit_in3)) == 0,
    };
}

bool Pca9534::writeReg(std::uint8_t reg, std::uint8_t val) {
    if (dev_ == nullptr) {
        return false;
    }
    const std::uint8_t buf[2] = {reg, val};
    return i2c_master_transmit(static_cast<i2c_master_dev_handle_t>(dev_), buf, sizeof(buf), 50) == ESP_OK;
}

bool Pca9534::readReg(std::uint8_t reg, std::uint8_t& val) {
    if (dev_ == nullptr) {
        return false;
    }
    return i2c_master_transmit_receive(static_cast<i2c_master_dev_handle_t>(dev_), &reg, 1, &val, 1, 50) ==
           ESP_OK;
}

}  // namespace firmware
}  // namespace gateway
