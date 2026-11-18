#pragma once

#include <cstddef>
#include <cstdint>

#include "firmware/EspIdfHostStubs.hpp"

// Seeed XIAO ESP32-C6 pin assignment on Wiegand Gate Controller v1 main board:
//   D0  / GPIO0  = VIN_ADC     (ADC1_CH0: 9-32 V DC input monitor via 100k/10k divider)
//   D1  / GPIO1  = BTN_RESTART (SW1 Restart / AP Setup / Factory Reset button, active LOW)
//   D2  / GPIO2  = WG_D0       (Wiegand Data 0 via 5V-tolerant Schmitt buffer, falling edge)
//   D3  / GPIO21 = LED_DATA    (2x WS2812B-MINI-V3J RGB LEDs via 74AHCT1G125 buffer)
//   D4  / GPIO22 = I2C_SDA     (PCA9534 8-bit I/O expander @ 0x20)
//   D5  / GPIO23 = I2C_SCL     (I2C clock, 400 kHz)
//   D9  / GPIO20 = WG_D1       (Wiegand Data 1 via 5V-tolerant Schmitt buffer, falling edge)
//   D10 / GPIO18 = EXP_INT     (PCA9534 /INT active LOW)
namespace gateway {
namespace firmware {
namespace board {

constexpr gpio_num_t boot_btn_pin = GPIO_NUM_9;

constexpr gpio_num_t vin_adc_pin = GPIO_NUM_0;
constexpr adc_channel_t vin_adc_channel = ADC_CHANNEL_0;

constexpr gpio_num_t btn_restart_pin = GPIO_NUM_1;
constexpr gpio_num_t wg_d0_pin = GPIO_NUM_2;
constexpr gpio_num_t led_data_pin = GPIO_NUM_21;
constexpr gpio_num_t i2c_sda_pin = GPIO_NUM_22;
constexpr gpio_num_t i2c_scl_pin = GPIO_NUM_23;
constexpr gpio_num_t wg_d1_pin = GPIO_NUM_20;
constexpr gpio_num_t exp_int_pin = GPIO_NUM_18;

// Seeed XIAO ESP32-C6 internal FM8625H RF switch (selects external U.FL flex dipole antenna):
constexpr gpio_num_t rf_switch_power_pin = GPIO_NUM_3;
constexpr gpio_num_t rf_antenna_select_pin = GPIO_NUM_14;
constexpr std::int8_t wifi_max_tx_power_quarter_dbm = 82;

constexpr std::uint8_t i2c_addr_pca9534 = 0x20;
constexpr std::uint32_t i2c_speed_hz = 400000;
constexpr float vin_divider_ratio = 11.0F;  // 100k / 10k

// PCA9534 bit assignments
constexpr std::uint8_t exp_bit_relay1 = 0;
constexpr std::uint8_t exp_bit_relay2 = 1;
constexpr std::uint8_t exp_bit_wg_led = 2;
constexpr std::uint8_t exp_bit_wg_beep = 3;
constexpr std::uint8_t exp_bit_in1 = 4;
constexpr std::uint8_t exp_bit_in2 = 5;
constexpr std::uint8_t exp_bit_in3 = 6;

constexpr bool usb_pin(gpio_num_t pin) {
    return pin == GPIO_NUM_12 || pin == GPIO_NUM_13;
}

constexpr bool pins_distinct() {
    const gpio_num_t pins[] = {
        vin_adc_pin, btn_restart_pin, wg_d0_pin,   led_data_pin,        i2c_sda_pin,
        i2c_scl_pin, wg_d1_pin,       exp_int_pin, rf_switch_power_pin, rf_antenna_select_pin,
    };
    for (std::size_t i = 0; i < sizeof(pins) / sizeof(pins[0]); ++i) {
        if (usb_pin(pins[i])) {
            return false;
        }
        for (std::size_t j = i + 1; j < sizeof(pins) / sizeof(pins[0]); ++j) {
            if (pins[i] == pins[j]) {
                return false;
            }
        }
    }
    return true;
}

static_assert(pins_distinct(), "Wiegand Gate Controller pins must be distinct and avoid USB D-/D+");

}  // namespace board
}  // namespace firmware
}  // namespace gateway
