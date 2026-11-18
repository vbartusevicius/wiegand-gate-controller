#include "access/AccessStore.hpp"

#include <ArduinoJson.h>

namespace gateway {
namespace access {

std::uint32_t AccessStore::allocateId(std::uint32_t requested_id) {
    if (requested_id == 0) {
        return next_id_++;
    }
    if (requested_id >= next_id_) {
        next_id_ = requested_id + 1;
    }
    return requested_id;
}

bool AccessStore::upsertUser(UserEntry user) {
    if (user.card.empty() && user.pin.empty()) {
        return false;
    }
    if (user.id != 0) {
        for (auto& existing : users_) {
            if (existing.id == user.id) {
                user.hits = existing.hits;
                existing = std::move(user);
                return true;
            }
        }
    }
    if (users_.size() >= kMaxUsers) {
        return false;
    }
    user.id = allocateId(user.id);
    users_.push_back(std::move(user));
    return true;
}

bool AccessStore::deleteUser(std::uint32_t id) {
    for (auto it = users_.begin(); it != users_.end(); ++it) {
        if (it->id == id) {
            users_.erase(it);
            return true;
        }
    }
    return false;
}

void AccessStore::clearUsers() {
    users_.clear();
    next_id_ = 1;
}

AuthMatch AccessStore::authorizeBy(const std::string& value, std::string UserEntry::* field) {
    if (value.empty()) {
        return {};
    }
    for (auto& user : users_) {
        const auto& stored = user.*field;
        if (user.enabled && !stored.empty() && stored == value) {
            ++user.hits;
            return AuthMatch{true, user.id, user.name, user.target};
        }
    }
    return {};
}

AuthMatch AccessStore::authorizeCard(const std::string& code) {
    return authorizeBy(code, &UserEntry::card);
}

AuthMatch AccessStore::authorizePin(const std::string& pin) {
    return authorizeBy(pin, &UserEntry::pin);
}

void AccessStore::recordLastUnknown(const std::string& code, std::uint8_t bits, std::uint64_t now_ms) {
    last_unknown_code_ = code;
    last_unknown_bits_ = bits;
    last_unknown_at_ms_ = now_ms;
}

void AccessStore::clearLastUnknown() {
    last_unknown_code_.clear();
    last_unknown_bits_ = 0;
    last_unknown_at_ms_ = 0;
}

void AccessStore::addEvent(AccessEvent ev) {
    if (events_.size() >= kMaxEvents) {
        events_.pop_back();
    }
    events_.push_front(std::move(ev));
}

std::optional<UserEntry> AccessStore::findById(std::uint32_t id) const {
    for (const auto& user : users_) {
        if (user.id == id) {
            return user;
        }
    }
    return std::nullopt;
}

std::string AccessStore::serializeUsersJson() const {
    JsonDocument doc;
    JsonArray arr = doc["users"].to<JsonArray>();
    for (const auto& u : users_) {
        JsonObject obj = arr.add<JsonObject>();
        obj["id"] = u.id;
        obj["name"] = u.name;
        obj["card"] = u.card;
        obj["pin"] = u.pin;
        obj["enabled"] = u.enabled;
        obj["target"] = toString(u.target);
        obj["hits"] = u.hits;
    }
    std::string out;
    serializeJson(doc, out);
    return out;
}

bool AccessStore::deserializeUsersJson(const std::string& json) {
    if (json.empty()) {
        return false;
    }
    JsonDocument doc;
    if (deserializeJson(doc, json) != DeserializationError::Ok) {
        return false;
    }
    JsonArrayConst arr = doc["users"].as<JsonArrayConst>();
    if (arr.isNull()) {
        return false;
    }
    users_.clear();
    next_id_ = 1;
    for (JsonObjectConst obj : arr) {
        if (users_.size() >= kMaxUsers) {
            break;
        }
        UserEntry u;
        u.id = obj["id"] | 0U;
        u.name = obj["name"] | "";
        u.card = obj["card"] | "";
        u.pin = obj["pin"] | "";
        u.enabled = obj["enabled"] | true;
        u.target = parseRelayTarget(obj["target"] | "primary");
        u.hits = obj["hits"] | 0U;
        if (!u.card.empty() || !u.pin.empty()) {
            u.id = allocateId(u.id);
            users_.push_back(std::move(u));
        }
    }
    return true;
}

}  // namespace access
}  // namespace gateway
