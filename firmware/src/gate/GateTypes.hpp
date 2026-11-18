#pragma once

#include <cctype>
#include <cstdint>
#include <optional>
#include <string>

namespace gateway {
namespace gate {

enum class GateState : std::uint8_t {
    Unknown = 0,
    Closed = 1,
    Opening = 2,
    Open = 3,
    Closing = 4,
    PartiallyOpen = 5,
    Fault = 6,
};

enum class GateCommand : std::uint8_t {
    TriggerPrimary = 0,
    Open = 1,
    Close = 2,
    Stop = 3,
    Pedestrian = 4,
    Lock = 5,
    Unlock = 6,
};

enum class CommandDirection : std::uint8_t {
    None = 0,
    Opening = 1,
    Closing = 2,
};

struct RawInputs {
    bool in1{false};  // +SC / Closed reed / Closed limit
    bool in2{false};  // COR / Open limit
    bool in3{false};  // REX / Exit / Ped button
};

struct RelayOutputs {
    bool relay1{false};
    bool relay2{false};
};

struct ReaderFeedback {
    bool led_active{false};
    bool beep_active{false};
};

inline const char* toString(GateState st) {
    switch (st) {
    case GateState::Unknown:
        return "unknown";
    case GateState::Closed:
        return "closed";
    case GateState::Opening:
        return "opening";
    case GateState::Open:
        return "open";
    case GateState::Closing:
        return "closing";
    case GateState::PartiallyOpen:
        return "partially_open";
    case GateState::Fault:
        return "fault";
    }
    return "unknown";
}

inline const char* toString(GateCommand cmd) {
    switch (cmd) {
    case GateCommand::TriggerPrimary:
        return "trigger";
    case GateCommand::Open:
        return "open";
    case GateCommand::Close:
        return "close";
    case GateCommand::Stop:
        return "stop";
    case GateCommand::Pedestrian:
        return "pedestrian";
    case GateCommand::Lock:
        return "lock";
    case GateCommand::Unlock:
        return "unlock";
    }
    return "trigger";
}

inline std::optional<GateCommand> parseGateCommand(const std::string& raw) {
    std::string s;
    s.reserve(raw.size());
    for (char c : raw) {
        s.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
    }
    if (s == "open") {
        return GateCommand::Open;
    }
    if (s == "close") {
        return GateCommand::Close;
    }
    if (s == "stop") {
        return GateCommand::Stop;
    }
    if (s == "unlock") {
        return GateCommand::Unlock;
    }
    if (s == "lock") {
        return GateCommand::Lock;
    }
    if (s == "pedestrian" || s == "ped") {
        return GateCommand::Pedestrian;
    }
    if (s == "trigger") {
        return GateCommand::TriggerPrimary;
    }
    return std::nullopt;
}

}  // namespace gate
}  // namespace gateway
