#include "core/GatewayApp.hpp"

#include <algorithm>

namespace gateway {
namespace core {

GatewayApp::GatewayApp() {
    wiegand_.setCallback([this](const wiegand::WiegandEvent& ev) { onWiegandEvent(ev, last_now_ms_); });
    gate_.setStateChangedCallback([this](gate::GateState prev, gate::GateState next) {
        store_.addEvent({last_now_ms_, "state", "gate", "-", gate::toString(next)});
        for (auto* obs : observers_) {
            obs->onGateStateChanged(prev, next, last_now_ms_);
        }
    });
    gate_.setRexCallback([this](bool pedestrian) {
        store_.addEvent({last_now_ms_, "rex", "in3", "-", pedestrian ? "pedestrian" : "primary"});
    });
    applyConfig(cfg_);
}

void GatewayApp::addObserver(IGatewayObserver* observer) {
    if (observer != nullptr &&
        std::find(observers_.begin(), observers_.end(), observer) == observers_.end()) {
        observers_.push_back(observer);
    }
}

void GatewayApp::applyConfig(const DeviceConfig& cfg) {
    cfg_ = cfg;
    wiegand_.configure(cfg_.reader);
    gate_.configure(cfg_.relay, cfg_.sensor, cfg_.reader);
}

void GatewayApp::onWiegandBit(std::uint8_t bit, std::uint64_t now_us) {
    wiegand_.onBit(bit, now_us);
}

void GatewayApp::publishTag(const std::string& code, const std::string& user, bool granted) {
    if (mqtt_pub_ != nullptr) {
        mqtt_pub_->publishMqtt(ha_mqtt_.buildTagEvent(cfg_, code, user, granted));
    }
}

void GatewayApp::notifyAccess(bool granted, const std::string& source, const std::string& user,
                              const std::string& code, std::uint64_t now_ms) {
    for (auto* obs : observers_) {
        obs->onAccessDecision(granted, source, user, code, now_ms);
        if (granted) {
            obs->onUsersChanged();
        }
    }
}

void GatewayApp::onWiegandEvent(const wiegand::WiegandEvent& ev, std::uint64_t now_ms) {
    last_now_ms_ = now_ms;
    if (ev.kind == wiegand::WiegandEvent::Kind::KeyPress) {
        return;
    }
    if (ev.kind == wiegand::WiegandEvent::Kind::BadParity) {
        gate_.triggerDeniedFeedback(now_ms);
        store_.addEvent({now_ms, "denied", "wiegand", "-", "bad_parity:" + ev.code});
        notifyAccess(false, "wiegand", "-", ev.code, now_ms);
        return;
    }

    const bool is_pin = (ev.kind == wiegand::WiegandEvent::Kind::Pin);
    const access::AuthMatch match = is_pin ? store_.authorizePin(ev.code) : store_.authorizeCard(ev.code);
    const char* src_name = is_pin ? "keypad" : "wiegand";
    last_code_ = ev.code;

    if (match.granted) {
        last_user_ = match.user_name;
        gate_.executeAccessTarget(match.target, now_ms);
        gate_.triggerGrantedFeedback(now_ms);
        store_.addEvent({now_ms, "granted", src_name, match.user_name, ev.code});
        notifyAccess(true, src_name, match.user_name, ev.code, now_ms);
        publishTag(ev.code, match.user_name, true);
        return;
    }

    if (!is_pin) {
        store_.recordLastUnknown(ev.code, ev.bits, now_ms);
    }
    gate_.triggerDeniedFeedback(now_ms);
    store_.addEvent({now_ms, "denied", src_name, "-", ev.code});
    notifyAccess(false, src_name, "-", ev.code, now_ms);
    publishTag(ev.code, "", false);
}

void GatewayApp::onInputs(gate::RawInputs inputs, std::uint64_t now_ms) {
    last_now_ms_ = now_ms;
    gate_.updateInputs(inputs, now_ms);
}

void GatewayApp::onManualCommand(gate::GateCommand cmd, const std::string& source, std::uint64_t now_ms) {
    last_now_ms_ = now_ms;
    gate_.executeCommand(cmd, now_ms);
    store_.addEvent({now_ms, "manual", source, "-", gate::toString(cmd)});
}

void GatewayApp::onMqttCommand(const std::string& payload, std::uint64_t now_ms) {
    if (const auto cmd = gate::parseGateCommand(payload)) {
        onManualCommand(*cmd, "mqtt", now_ms);
    }
}

void GatewayApp::tick(std::uint64_t now_ms, std::uint64_t now_us) {
    last_now_ms_ = now_ms;
    wiegand_.tick(now_us);
    gate_.tick(now_ms);
}

}  // namespace core
}  // namespace gateway
