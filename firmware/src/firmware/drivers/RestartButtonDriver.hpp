#pragma once

#include <cstdint>

#include "core/RestartButton.hpp"

namespace gateway {
namespace firmware {

class RestartButtonDriver {
public:
    bool init();
    core::ButtonAction poll(std::uint64_t now_ms);

private:
    core::RestartButton button_{};
};

}  // namespace firmware
}  // namespace gateway
