#include "web/ApiJson.hpp"

#include <ArduinoJson.h>

namespace gateway {
namespace web {

namespace {

template <typename T>
void readField(JsonObjectConst obj, const char* key, T& dst) {
    if (obj[key].is<T>()) {
        dst = obj[key].as<T>();
    }
}

void readString(JsonObjectConst obj, const char* key, std::string& dst) {
    if (obj[key].is<const char*>()) {
        dst = obj[key].as<std::string>();
    }
}

void readNonEmptySecret(JsonObjectConst obj, const char* key, std::string& dst) {
    if (obj[key].is<const char*>()) {
        auto val = obj[key].as<std::string>();
        if (!val.empty()) {
            dst = std::move(val);
        }
    }
}

template <typename Enum, typename ParseFn>
void readEnum(JsonObjectConst obj, const char* key, Enum& dst, ParseFn parse) {
    if (obj[key].is<const char*>()) {
        dst = parse(obj[key].as<std::string>());
    }
}

}  // namespace

std::string ApiJson::buildStatus(const core::DeviceConfig& cfg, const RuntimeStatus& rt,
                                 const gate::GateController& gate, const access::AccessStore& store) {
    JsonDocument doc;
    doc["device_name"] = cfg.device_name;
    doc["fw_version"] = rt.fw_version;
    doc["uptime_s"] = static_cast<std::uint64_t>(rt.uptime_ms / 1000ULL);
    doc["vin_v"] = core::round2(rt.vin_v);
    doc["simulated"] = rt.simulated;

    JsonObject net = doc["network"].to<JsonObject>();
    net["wifi_connected"] = rt.wifi_connected;
    net["ap_mode"] = rt.ap_mode;
    net["ip"] = rt.ip;
    net["mac"] = rt.mac;
    net["rssi"] = rt.rssi_dbm;
    net["mqtt_connected"] = rt.mqtt_connected;
    net["antenna"] = rt.active_antenna;

    JsonObject g = doc["gate"].to<JsonObject>();
    g["state"] = gate::toString(gate.state());
    g["mode"] = core::toString(cfg.relay.mode);
    g["sensor_mode"] = core::toString(cfg.sensor.mode);
    g["hold_open"] = gate.holdOpenActive();
    const auto rel = gate.logicalRelays();
    g["relay1"] = rel.relay1;
    g["relay2"] = rel.relay2;
    g["in1"] = gate.in1Active();
    g["in2"] = gate.in2Active();
    g["in3"] = gate.in3Active();

    JsonObject learn = doc["last_unknown"].to<JsonObject>();
    learn["code"] = store.lastUnknownCode();
    learn["bits"] = store.lastUnknownBits();
    learn["at_ms"] = store.lastUnknownAtMs();

    doc["users_count"] = store.users().size();

    std::string out;
    serializeJson(doc, out);
    return out;
}

std::string ApiJson::buildConfig(const core::DeviceConfig& cfg) {
    JsonDocument doc;
    doc["device_name"] = cfg.device_name;

    JsonObject wifi = doc["wifi"].to<JsonObject>();
    wifi["ssid"] = cfg.wifi.ssid;
    wifi["password_set"] = !cfg.wifi.password.empty();
    wifi["hostname"] = cfg.wifi.hostname;
    wifi["antenna"] = core::toString(cfg.wifi.antenna);

    JsonObject mqtt = doc["mqtt"].to<JsonObject>();
    mqtt["enabled"] = cfg.mqtt.enabled;
    mqtt["host"] = cfg.mqtt.host;
    mqtt["port"] = cfg.mqtt.port;
    mqtt["username"] = cfg.mqtt.username;
    mqtt["password_set"] = !cfg.mqtt.password.empty();
    mqtt["base_topic"] = cfg.mqtt.base_topic;
    mqtt["discovery_prefix"] = cfg.mqtt.discovery_prefix;
    mqtt["ha_discovery"] = cfg.mqtt.ha_discovery;

    JsonObject relay = doc["relay"].to<JsonObject>();
    relay["mode"] = core::toString(cfg.relay.mode);
    relay["relay1_pulse_ms"] = cfg.relay.relay1_pulse_ms;
    relay["relay2_pulse_ms"] = cfg.relay.relay2_pulse_ms;
    relay["relay1_inverted"] = cfg.relay.relay1_inverted;
    relay["relay2_inverted"] = cfg.relay.relay2_inverted;
    relay["relay1_hold_open"] = cfg.relay.relay1_hold_open;
    relay["travel_time_ms"] = cfg.relay.travel_time_ms;

    JsonObject sensor = doc["sensor"].to<JsonObject>();
    sensor["mode"] = core::toString(cfg.sensor.mode);
    sensor["in1_inverted"] = cfg.sensor.in1_inverted;
    sensor["in2_inverted"] = cfg.sensor.in2_inverted;
    sensor["in3_inverted"] = cfg.sensor.in3_inverted;
    sensor["in3_enabled"] = cfg.sensor.in3_enabled;
    sensor["in3_pedestrian"] = cfg.sensor.in3_pedestrian;
    sensor["cor_indicates_open"] = cfg.sensor.cor_indicates_open;
    sensor["sc_blink_timeout_ms"] = cfg.sensor.sc_blink_timeout_ms;

    JsonObject reader = doc["reader"].to<JsonObject>();
    reader["wiegand_bits"] = cfg.reader.wiegand_bits;
    reader["pin_min_len"] = cfg.reader.pin_min_len;
    reader["pin_max_len"] = cfg.reader.pin_max_len;
    reader["pin_timeout_ms"] = cfg.reader.pin_timeout_ms;
    reader["keypad_enabled"] = cfg.reader.keypad_enabled;
    reader["led_active_low"] = cfg.reader.led_active_low;
    reader["beep_active_low"] = cfg.reader.beep_active_low;
    reader["granted_beep_ms"] = cfg.reader.granted_beep_ms;
    reader["granted_led_ms"] = cfg.reader.granted_led_ms;
    reader["denied_beeps"] = cfg.reader.denied_beeps;

    std::string out;
    serializeJson(doc, out);
    return out;
}

bool ApiJson::applyConfigPatch(const std::string& json, core::DeviceConfig& cfg) {
    JsonDocument doc;
    if (deserializeJson(doc, json) != DeserializationError::Ok || !doc.is<JsonObject>()) {
        return false;
    }
    const JsonObjectConst root = doc.as<JsonObjectConst>();
    readString(root, "device_name", cfg.device_name);

    if (const JsonObjectConst w = root["wifi"]; !w.isNull()) {
        readString(w, "ssid", cfg.wifi.ssid);
        readNonEmptySecret(w, "password", cfg.wifi.password);
        readString(w, "hostname", cfg.wifi.hostname);
        readEnum(w, "antenna", cfg.wifi.antenna, core::parseAntennaMode);
    }

    if (const JsonObjectConst m = root["mqtt"]; !m.isNull()) {
        readField(m, "enabled", cfg.mqtt.enabled);
        readString(m, "host", cfg.mqtt.host);
        readField(m, "port", cfg.mqtt.port);
        readString(m, "username", cfg.mqtt.username);
        readNonEmptySecret(m, "password", cfg.mqtt.password);
        readString(m, "base_topic", cfg.mqtt.base_topic);
        readString(m, "discovery_prefix", cfg.mqtt.discovery_prefix);
        readField(m, "ha_discovery", cfg.mqtt.ha_discovery);
    }

    if (const JsonObjectConst r = root["relay"]; !r.isNull()) {
        readEnum(r, "mode", cfg.relay.mode, core::parseDeviceMode);
        readField(r, "relay1_pulse_ms", cfg.relay.relay1_pulse_ms);
        readField(r, "relay2_pulse_ms", cfg.relay.relay2_pulse_ms);
        readField(r, "relay1_inverted", cfg.relay.relay1_inverted);
        readField(r, "relay2_inverted", cfg.relay.relay2_inverted);
        readField(r, "relay1_hold_open", cfg.relay.relay1_hold_open);
        readField(r, "travel_time_ms", cfg.relay.travel_time_ms);
    }

    if (const JsonObjectConst s = root["sensor"]; !s.isNull()) {
        readEnum(s, "mode", cfg.sensor.mode, core::parseSensorMode);
        readField(s, "in1_inverted", cfg.sensor.in1_inverted);
        readField(s, "in2_inverted", cfg.sensor.in2_inverted);
        readField(s, "in3_inverted", cfg.sensor.in3_inverted);
        readField(s, "in3_enabled", cfg.sensor.in3_enabled);
        readField(s, "in3_pedestrian", cfg.sensor.in3_pedestrian);
        readField(s, "cor_indicates_open", cfg.sensor.cor_indicates_open);
        readField(s, "sc_blink_timeout_ms", cfg.sensor.sc_blink_timeout_ms);
    }

    if (const JsonObjectConst rd = root["reader"]; !rd.isNull()) {
        readField(rd, "wiegand_bits", cfg.reader.wiegand_bits);
        readField(rd, "pin_min_len", cfg.reader.pin_min_len);
        readField(rd, "pin_max_len", cfg.reader.pin_max_len);
        readField(rd, "pin_timeout_ms", cfg.reader.pin_timeout_ms);
        readField(rd, "keypad_enabled", cfg.reader.keypad_enabled);
        readField(rd, "led_active_low", cfg.reader.led_active_low);
        readField(rd, "beep_active_low", cfg.reader.beep_active_low);
        readField(rd, "granted_beep_ms", cfg.reader.granted_beep_ms);
        readField(rd, "granted_led_ms", cfg.reader.granted_led_ms);
        readField(rd, "denied_beeps", cfg.reader.denied_beeps);
    }

    return true;
}

std::string ApiJson::buildUsers(const access::AccessStore& store) {
    return store.serializeUsersJson();
}

bool ApiJson::parseUserUpsert(const std::string& json, access::UserEntry& user) {
    JsonDocument doc;
    if (deserializeJson(doc, json) != DeserializationError::Ok || !doc.is<JsonObject>()) {
        return false;
    }
    user.id = doc["id"] | 0U;
    user.name = doc["name"] | "";
    user.card = doc["card"] | "";
    user.pin = doc["pin"] | "";
    user.enabled = doc["enabled"] | true;
    user.target = access::parseRelayTarget(doc["target"] | "primary");
    return !user.card.empty() || !user.pin.empty();
}

std::string ApiJson::buildEvents(const access::AccessStore& store) {
    JsonDocument doc;
    JsonArray arr = doc["events"].to<JsonArray>();
    for (const auto& ev : store.events()) {
        JsonObject o = arr.add<JsonObject>();
        o["ts"] = ev.timestamp_ms;
        o["type"] = ev.type;
        o["source"] = ev.source;
        o["user"] = ev.user;
        o["code"] = ev.code;
    }
    std::string out;
    serializeJson(doc, out);
    return out;
}

}  // namespace web
}  // namespace gateway
