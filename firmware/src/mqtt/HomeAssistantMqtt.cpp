#include "mqtt/HomeAssistantMqtt.hpp"

#include <cctype>
#include <cmath>

#include <ArduinoJson.h>

namespace gateway {
namespace mqtt {

namespace {

void fillDevice(JsonObject dev, const core::DeviceConfig& cfg, const std::string& node_id,
                const std::string& fw_version) {
    JsonArray ids = dev["identifiers"].to<JsonArray>();
    ids.add(node_id);
    dev["name"] = cfg.device_name;
    dev["manufacturer"] = "Wiegand Gateway";
    dev["model"] = "WG-C6 (Gate/Door)";
    dev["sw_version"] = fw_version;
}

MqttMessage makeDiscovery(const core::DeviceConfig& cfg, const std::string& node_id,
                          const std::string& fw_version, const std::string& component,
                          const std::string& object_id, JsonDocument& doc) {
    fillDevice(doc["device"].to<JsonObject>(), cfg, node_id, fw_version);
    doc["availability_topic"] = HomeAssistantMqtt::availabilityTopic(cfg);
    doc["unique_id"] = node_id + "_" + object_id;
    doc["object_id"] = node_id + "_" + object_id;

    MqttMessage msg;
    msg.topic = cfg.mqtt.discovery_prefix + "/" + component + "/" + node_id + "/" + object_id + "/config";
    serializeJson(doc, msg.payload);
    msg.retain = true;
    return msg;
}

const char* haCoverState(gate::GateState st) {
    switch (st) {
    case gate::GateState::Closed:
        return "closed";
    case gate::GateState::Opening:
        return "opening";
    case gate::GateState::Open:
    case gate::GateState::PartiallyOpen:
        return "open";
    case gate::GateState::Closing:
        return "closing";
    case gate::GateState::Unknown:
    case gate::GateState::Fault:
        return "open";
    }
    return "closed";
}

const char* haLockState(gate::GateState st) {
    return (st == gate::GateState::Closed) ? "LOCKED" : "UNLOCKED";
}

}  // namespace

std::string HomeAssistantMqtt::nodeId(const std::string& mac_hex) {
    std::string out = "wg_";
    for (char c : mac_hex) {
        if (std::isxdigit(static_cast<unsigned char>(c)) != 0) {
            out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
        }
    }
    return out;
}

std::string HomeAssistantMqtt::commandTopic(const core::DeviceConfig& cfg) {
    return cfg.mqtt.base_topic + "/cmd";
}

std::string HomeAssistantMqtt::availabilityTopic(const core::DeviceConfig& cfg) {
    return cfg.mqtt.base_topic + "/status";
}

std::vector<MqttMessage> HomeAssistantMqtt::buildDiscovery(const core::DeviceConfig& cfg,
                                                           const std::string& node_id,
                                                           const std::string& fw_version) const {
    std::vector<MqttMessage> out;
    const std::string state_topic = cfg.mqtt.base_topic + "/state";
    const std::string cmd_topic = commandTopic(cfg);

    const bool is_gate =
        (cfg.relay.mode == core::DeviceMode::GateDual || cfg.relay.mode == core::DeviceMode::GatePulse);
    if (is_gate) {
        JsonDocument doc;
        doc["name"] = "Gate";
        doc["device_class"] = "gate";
        doc["state_topic"] = state_topic;
        doc["value_template"] = "{{ value_json.cover_state }}";
        doc["command_topic"] = cmd_topic;
        doc["payload_open"] = "OPEN";
        doc["payload_close"] = "CLOSE";
        doc["payload_stop"] = "STOP";
        out.push_back(makeDiscovery(cfg, node_id, fw_version, "cover", "gate", doc));
    } else {
        JsonDocument doc;
        doc["name"] = "Door Lock";
        doc["state_topic"] = state_topic;
        doc["value_template"] = "{{ value_json.lock_state }}";
        doc["command_topic"] = cmd_topic;
        doc["payload_lock"] = "LOCK";
        doc["payload_unlock"] = "UNLOCK";
        out.push_back(makeDiscovery(cfg, node_id, fw_version, "lock", "door", doc));
    }

    {
        JsonDocument doc;
        doc["name"] = is_gate ? "Gate Contact" : "Door Contact";
        doc["device_class"] = is_gate ? "garage_door" : "door";
        doc["state_topic"] = state_topic;
        doc["value_template"] = "{{ 'OFF' if value_json.gate_state == 'closed' else 'ON' }}";
        out.push_back(makeDiscovery(cfg, node_id, fw_version, "binary_sensor", "contact", doc));
    }
    {
        JsonDocument doc;
        doc["name"] = "Last Access";
        doc["icon"] = "mdi:badge-account";
        doc["state_topic"] = state_topic;
        doc["value_template"] = "{{ value_json.last_user }}";
        out.push_back(makeDiscovery(cfg, node_id, fw_version, "sensor", "last_access", doc));
    }
    {
        JsonDocument doc;
        doc["name"] = "Supply Voltage";
        doc["device_class"] = "voltage";
        doc["unit_of_measurement"] = "V";
        doc["entity_category"] = "diagnostic";
        doc["state_topic"] = state_topic;
        doc["value_template"] = "{{ value_json.vin_v }}";
        out.push_back(makeDiscovery(cfg, node_id, fw_version, "sensor", "vin", doc));
    }
    {
        JsonDocument doc;
        doc["name"] = "Pedestrian / Aux";
        doc["icon"] = "mdi:door-open";
        doc["command_topic"] = cmd_topic;
        doc["payload_press"] = "PED";
        out.push_back(makeDiscovery(cfg, node_id, fw_version, "button", "pedestrian", doc));
    }
    return out;
}

MqttMessage HomeAssistantMqtt::buildState(const core::DeviceConfig& cfg, gate::GateState gate_state,
                                          float vin_v, int rssi_dbm, const std::string& last_user,
                                          const std::string& last_code) const {
    JsonDocument doc;
    doc["gate_state"] = gate::toString(gate_state);
    doc["cover_state"] = haCoverState(gate_state);
    doc["lock_state"] = haLockState(gate_state);
    doc["vin_v"] = core::round2(vin_v);
    doc["rssi"] = rssi_dbm;
    doc["last_user"] = last_user.empty() ? "none" : last_user;
    doc["last_code"] = last_code;

    MqttMessage msg;
    msg.topic = cfg.mqtt.base_topic + "/state";
    serializeJson(doc, msg.payload);
    msg.retain = true;
    return msg;
}

MqttMessage HomeAssistantMqtt::buildAvailability(const core::DeviceConfig& cfg, bool online) const {
    return {availabilityTopic(cfg), online ? "online" : "offline", true};
}

MqttMessage HomeAssistantMqtt::buildTagEvent(const core::DeviceConfig& cfg, const std::string& code,
                                             const std::string& user, bool granted) const {
    JsonDocument doc;
    doc["code"] = code;
    doc["user"] = user;
    doc["granted"] = granted;

    MqttMessage msg;
    msg.topic = cfg.mqtt.base_topic + "/tag";
    serializeJson(doc, msg.payload);
    msg.retain = false;
    return msg;
}

}  // namespace mqtt
}  // namespace gateway
