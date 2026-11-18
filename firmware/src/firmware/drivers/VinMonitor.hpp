#pragma once

namespace gateway {
namespace firmware {

class VinMonitor {
public:
    bool init();
    float readVolts() const;

private:
    void* adc_{nullptr};
    void* cali_{nullptr};
};

}  // namespace firmware
}  // namespace gateway
