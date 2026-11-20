#pragma once

#include <cstdint>
#include <deque>
#include <optional>
#include <string>
#include <vector>

namespace gateway {
namespace access {

enum class RelayTarget : std::uint8_t {
    Primary = 0,     // Door lock / Gate Open or Step-by-Step
    Pedestrian = 1,  // Relay 2 (PED / Close / Door 2)
    Both = 2,
};

struct UserEntry {
    std::uint32_t id{0};
    std::string name;
    std::string card;  // Wiegand card/fob/UHF code
    std::string pin;   // Optional keypad PIN
    bool enabled{true};
    RelayTarget target{RelayTarget::Primary};
    std::uint32_t hits{0};
};

struct AccessEvent {
    std::uint64_t timestamp_ms{0};
    std::string type;    // granted, denied, rex, manual, state, rs485
    std::string source;  // wiegand, keypad, rex, web, mqtt, gate
    std::string user;    // User name or "-"
    std::string code;    // Credential or detail
};

struct AuthMatch {
    bool granted{false};
    std::uint32_t user_id{0};
    std::string user_name;
    RelayTarget target{RelayTarget::Primary};
};

class AccessStore {
public:
    static constexpr std::size_t kMaxUsers = 500;
    static constexpr std::size_t kMaxEvents = 64;

    bool upsertUser(UserEntry user);
    bool deleteUser(std::uint32_t id);
    void clearUsers();

    AuthMatch peekCard(const std::string& code) const;
    void recordHit(std::uint32_t user_id);
    AuthMatch authorizeCard(const std::string& code);
    AuthMatch authorizePin(const std::string& pin);

    void recordLastUnknown(const std::string& code, std::uint8_t bits, std::uint64_t now_ms);
    void clearLastUnknown();
    const std::string& lastUnknownCode() const { return last_unknown_code_; }
    std::uint8_t lastUnknownBits() const { return last_unknown_bits_; }
    std::uint64_t lastUnknownAtMs() const { return last_unknown_at_ms_; }

    void addEvent(AccessEvent ev);

    const std::vector<UserEntry>& users() const { return users_; }
    std::optional<UserEntry> findById(std::uint32_t id) const;
    const std::deque<AccessEvent>& events() const { return events_; }

    std::string serializeUsersJson() const;
    bool deserializeUsersJson(const std::string& json);

private:
    std::uint32_t allocateId(std::uint32_t requested_id);
    AuthMatch peekBy(const std::string& value, std::string UserEntry::* field) const;
    AuthMatch authorizeBy(const std::string& value, std::string UserEntry::* field);

    std::vector<UserEntry> users_;
    std::deque<AccessEvent> events_;
    std::uint32_t next_id_{1};
    std::string last_unknown_code_;
    std::uint8_t last_unknown_bits_{0};
    std::uint64_t last_unknown_at_ms_{0};
};

inline const char* toString(RelayTarget t) {
    switch (t) {
    case RelayTarget::Primary:
        return "primary";
    case RelayTarget::Pedestrian:
        return "pedestrian";
    case RelayTarget::Both:
        return "both";
    }
    return "primary";
}

inline RelayTarget parseRelayTarget(const std::string& s) {
    if (s == "pedestrian") {
        return RelayTarget::Pedestrian;
    }
    if (s == "both") {
        return RelayTarget::Both;
    }
    return RelayTarget::Primary;
}

}  // namespace access
}  // namespace gateway
