#pragma once

#include <cmath>
#include <cstdint>
#include <string>

namespace gateway {
namespace core {

enum class DeviceMode : std::uint8_t {
    GateDual = 0,   // Relay 1 = Open (AP), Relay 2 = Close (CH) / Ped
    GatePulse = 1,  // Relay 1 = Step-by-step (PP), Relay 2 = Pedestrian (PED) or Aux
    Door = 2,       // Relay 1 = Lock strike/maglock, Relay 2 = Aux/Alarm
    DualDoor = 3,   // Relay 1 = Door 1, Relay 2 = Door 2
};

enum class SensorMode : std::uint8_t {
    RogerB70 = 0,       // IN1 = +SC (0V=Closed, Blink=Moving, 24V=Open), IN2 = COR optional confirm
    SingleReed = 1,     // IN1 = Closed reed switch
    DualLimit = 2,      // IN1 = Closed limit, IN2 = Open limit
    TimerFallback = 3,  // Estimate state from command + travel_time_ms
};

struct WifiConfig {
    std::string ssid;
    std::string password;
    std::string hostname{"wiegand-gate-controller"};
};

struct MqttConfig {
    bool enabled{false};
    std::string host;
    std::uint16_t port{1883};
    std::string username;
    std::string password;
    std::string base_topic{"wiegand-gate-controller"};
    std::string discovery_prefix{"homeassistant"};
    bool ha_discovery{true};
};

struct RelayConfig {
    DeviceMode mode{DeviceMode::GateDual};
    std::uint32_t relay1_pulse_ms{600};
    std::uint32_t relay2_pulse_ms{600};
    bool relay1_inverted{false};
    bool relay2_inverted{false};
    bool relay1_hold_open{false};  // Maglock / ORO timer hold mode
    std::uint32_t travel_time_ms{15000};
};

struct SensorConfig {
    SensorMode mode{SensorMode::RogerB70};
    bool in1_inverted{false};  // Active-low / NC vs NO
    bool in2_inverted{false};
    bool in3_inverted{false};  // IN3 = REX / Exit / Ped button
    bool in3_enabled{true};
    bool in3_pedestrian{false};     // IN3 triggers Relay 2 (PED) instead of Relay 1
    bool cor_indicates_open{true};  // If IN2 is wired to B70/1DC COR: true=active means open, false=closed
    std::uint32_t sc_blink_timeout_ms{2200};
};

struct ReaderConfig {
    std::uint8_t wiegand_bits{0};  // 0 = auto (26/34/37/58/etc.), else strict bit count
    std::uint8_t pin_min_len{4};
    std::uint8_t pin_max_len{8};
    std::uint32_t pin_timeout_ms{5000};
    bool keypad_enabled{true};
    bool led_active_low{true};
    bool beep_active_low{true};
    std::uint32_t granted_beep_ms{150};
    std::uint32_t granted_led_ms{2500};
    std::uint8_t denied_beeps{3};
};

struct DeviceConfig {
    std::string device_name{"Front Gate"};
    WifiConfig wifi;
    MqttConfig mqtt;
    RelayConfig relay;
    SensorConfig sensor;
    ReaderConfig reader;
};

inline const char* toString(DeviceMode mode) {
    switch (mode) {
    case DeviceMode::GateDual:
        return "gate_dual";
    case DeviceMode::GatePulse:
        return "gate_pulse";
    case DeviceMode::Door:
        return "door";
    case DeviceMode::DualDoor:
        return "dual_door";
    }
    return "gate_dual";
}

inline DeviceMode parseDeviceMode(const std::string& s) {
    if (s == "gate_pulse") {
        return DeviceMode::GatePulse;
    }
    if (s == "door") {
        return DeviceMode::Door;
    }
    if (s == "dual_door") {
        return DeviceMode::DualDoor;
    }
    return DeviceMode::GateDual;
}

inline const char* toString(SensorMode mode) {
    switch (mode) {
    case SensorMode::RogerB70:
        return "roger_b70";
    case SensorMode::SingleReed:
        return "single_reed";
    case SensorMode::DualLimit:
        return "dual_limit";
    case SensorMode::TimerFallback:
        return "timer_fallback";
    }
    return "roger_b70";
}

inline SensorMode parseSensorMode(const std::string& s) {
    if (s == "single_reed") {
        return SensorMode::SingleReed;
    }
    if (s == "dual_limit") {
        return SensorMode::DualLimit;
    }
    if (s == "timer_fallback") {
        return SensorMode::TimerFallback;
    }
    return SensorMode::RogerB70;
}

inline double round2(float v) {
    return static_cast<double>(std::lround(v * 100.0F)) / 100.0;
}

}  // namespace core
}  // namespace gateway
