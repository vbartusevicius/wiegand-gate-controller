#pragma once

#include <cstdint>

#include "gate/GateController.hpp"

namespace gateway {
namespace firmware {

class Pca9534 {
public:
    bool init();
    bool writeOutputs(bool relay1, bool relay2, bool wg_led, bool wg_beep);
    gate::RawInputs readInputs();

private:
    bool writeReg(std::uint8_t reg, std::uint8_t val);
    bool readReg(std::uint8_t reg, std::uint8_t& val);

    void* bus_{nullptr};
    void* dev_{nullptr};
    std::uint8_t last_out_{0xFF};
};

}  // namespace firmware
}  // namespace gateway
