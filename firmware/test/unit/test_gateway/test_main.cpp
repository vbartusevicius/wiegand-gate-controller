#include <cstdint>
#include <string>
#include <vector>

#include <ArduinoJson.h>
#include <unity.h>

#include "access/AccessStore.hpp"
#include "core/Config.hpp"
#include "core/GatewayApp.hpp"
#include "core/GatewayEvents.hpp"
#include "core/RestartButton.hpp"
#include "gate/GateController.hpp"
#include "gate/GateTypes.hpp"
#include "mqtt/HomeAssistantMqtt.hpp"
#include "web/ApiJson.hpp"
#include "wiegand/WiegandDecoder.hpp"

using namespace gateway;

namespace {

int popcount(std::uint64_t v) {
    int c = 0;
    while (v != 0) {
        c += static_cast<int>(v & 1U);
        v >>= 1U;
    }
    return c;
}

std::uint64_t makeWiegand26(std::uint8_t facility, std::uint16_t card) {
    const std::uint32_t data = (static_cast<std::uint32_t>(facility) << 16U) | card;
    const std::uint32_t upper12 = (data >> 12U) & 0xFFFU;
    const std::uint32_t lower12 = data & 0xFFFU;
    const std::uint64_t even_p = (popcount(upper12) % 2 == 0) ? 0ULL : 1ULL;
    const std::uint64_t odd_p = (popcount(lower12) % 2 == 1) ? 0ULL : 1ULL;
    return (even_p << 25U) | (static_cast<std::uint64_t>(data) << 1U) | odd_p;
}

void feedBits(wiegand::WiegandDecoder& dec, std::uint64_t raw, std::uint8_t bits, std::uint64_t start_us) {
    for (int i = bits - 1; i >= 0; --i) {
        const auto bit = static_cast<std::uint8_t>((raw >> static_cast<unsigned>(i)) & 1ULL);
        dec.onBit(bit, start_us + static_cast<std::uint64_t>((bits - 1 - i) * 2000));
    }
    dec.tick(start_us + static_cast<std::uint64_t>(bits * 2000) + wiegand::WiegandDecoder::kFrameGapUs + 100);
}

}  // namespace

void setUp() {}
void tearDown() {}

void test_wiegand_26_valid_and_bad_parity() {
    wiegand::WiegandDecoder dec;
    std::vector<wiegand::WiegandEvent> events;
    dec.setCallback([&](const wiegand::WiegandEvent& ev) { events.push_back(ev); });

    const std::uint64_t frame = makeWiegand26(42, 12345);
    feedBits(dec, frame, 26, 1000);
    TEST_ASSERT_EQUAL(1, events.size());
    TEST_ASSERT_EQUAL(wiegand::WiegandEvent::Kind::Card, events[0].kind);
    TEST_ASSERT_TRUE(events[0].parity_ok);
    TEST_ASSERT_EQUAL_UINT32(42, events[0].facility);
    TEST_ASSERT_EQUAL_UINT32(12345, events[0].card_number);

    // Flip LSB parity bit -> BadParity
    feedBits(dec, frame ^ 1ULL, 26, 500000);
    TEST_ASSERT_EQUAL(2, events.size());
    TEST_ASSERT_EQUAL(wiegand::WiegandEvent::Kind::BadParity, events[1].kind);
    TEST_ASSERT_FALSE(events[1].parity_ok);
}

void test_wiegand_uhf_58bit_and_keypad_pin() {
    wiegand::WiegandDecoder dec;
    std::vector<wiegand::WiegandEvent> events;
    dec.setCallback([&](const wiegand::WiegandEvent& ev) { events.push_back(ev); });

    feedBits(dec, 0x03AABBCCDDEEFF11ULL, 58, 1000);
    TEST_ASSERT_EQUAL(1, events.size());
    TEST_ASSERT_EQUAL(wiegand::WiegandEvent::Kind::Card, events[0].kind);
    TEST_ASSERT_EQUAL(58, events[0].bits);
    TEST_ASSERT_EQUAL_STRING("3AABBCCDDEEFF11", events[0].code.c_str());

    // Keypad: 1, 2, * (clear), 4, 5, 6, 7, # (submit)
    std::uint64_t t = 1000000;
    const std::uint8_t keys[] = {1, 2, 10, 4, 5, 6, 7, 11};
    for (std::uint8_t k : keys) {
        feedBits(dec, k, 4, t);
        t += 200000;
    }
    const wiegand::WiegandEvent& last = events.back();
    TEST_ASSERT_EQUAL(wiegand::WiegandEvent::Kind::Pin, last.kind);
    TEST_ASSERT_EQUAL_STRING("4567", last.code.c_str());
}

void test_access_store_crud_and_json_roundtrip() {
    access::AccessStore store;
    TEST_ASSERT_TRUE(
        store.upsertUser({0, "Alice", "2764857", "4567", true, access::RelayTarget::Primary, 0}));
    TEST_ASSERT_TRUE(
        store.upsertUser({0, "Courier", "999111", "", true, access::RelayTarget::Pedestrian, 0}));
    TEST_ASSERT_TRUE(
        store.upsertUser({0, "Blocked", "555555", "0000", false, access::RelayTarget::Primary, 0}));

    auto m1 = store.authorizeCard("2764857");
    TEST_ASSERT_TRUE(m1.granted);
    TEST_ASSERT_EQUAL_STRING("Alice", m1.user_name.c_str());
    TEST_ASSERT_EQUAL(access::RelayTarget::Primary, m1.target);

    auto m2 = store.authorizePin("4567");
    TEST_ASSERT_TRUE(m2.granted);

    auto m_blocked = store.authorizeCard("555555");
    TEST_ASSERT_FALSE(m_blocked.granted);

    const std::string saved = store.serializeUsersJson();
    access::AccessStore restored;
    TEST_ASSERT_TRUE(restored.deserializeUsersJson(saved));
    TEST_ASSERT_EQUAL(3, restored.users().size());
    TEST_ASSERT_TRUE(restored.authorizeCard("999111").granted);
    TEST_ASSERT_EQUAL(access::RelayTarget::Pedestrian, restored.authorizeCard("999111").target);
}

void test_roger_b70_sc_state_decoder_and_relays() {
    gate::GateController gate;
    core::RelayConfig rcfg;
    rcfg.mode = core::DeviceMode::GateDual;
    rcfg.relay1_pulse_ms = 500;
    rcfg.relay2_pulse_ms = 500;
    core::SensorConfig scfg;
    scfg.mode = core::SensorMode::RogerB70;
    scfg.sc_blink_timeout_ms = 2000;
    core::ReaderConfig rdcfg;
    gate.configure(rcfg, scfg, rdcfg);

    // Steady 0V -> Closed
    gate.updateInputs({false, false, false}, 100);
    TEST_ASSERT_EQUAL(gate::GateState::Closed, gate.state());

    // Command Open -> Relay 1 pulses for 500ms
    gate.executeCommand(gate::GateCommand::Open, 1000);
    TEST_ASSERT_TRUE(gate.relayOutputs().relay1);
    TEST_ASSERT_FALSE(gate.relayOutputs().relay2);
    gate.tick(1501);
    TEST_ASSERT_FALSE(gate.relayOutputs().relay1);

    // +SC starts blinking -> Opening
    gate.updateInputs({true, false, false}, 1600);
    TEST_ASSERT_EQUAL(gate::GateState::Opening, gate.state());
    gate.updateInputs({false, false, false}, 2100);
    TEST_ASSERT_EQUAL(gate::GateState::Opening, gate.state());
    gate.updateInputs({true, false, false}, 2600);
    TEST_ASSERT_EQUAL(gate::GateState::Opening, gate.state());

    // +SC remains steady ON > 2000ms -> Open
    gate.tick(4700);
    TEST_ASSERT_EQUAL(gate::GateState::Open, gate.state());

    // TriggerPrimary while Open in GateDual -> Relay 2 (Close)
    gate.executeCommand(gate::GateCommand::TriggerPrimary, 5000);
    TEST_ASSERT_FALSE(gate.relayOutputs().relay1);
    TEST_ASSERT_TRUE(gate.relayOutputs().relay2);
}

void test_dual_limit_fault_and_rex() {
    gate::GateController gate;
    core::RelayConfig rcfg;
    rcfg.mode = core::DeviceMode::GatePulse;
    core::SensorConfig scfg;
    scfg.mode = core::SensorMode::DualLimit;
    scfg.in3_enabled = true;
    scfg.in3_pedestrian = true;
    gate.configure(rcfg, scfg, {});

    // IN1=Closed, IN2=Open both active -> Fault
    gate.updateInputs({true, true, false}, 100);
    TEST_ASSERT_EQUAL(gate::GateState::Fault, gate.state());

    // IN3 rising edge -> pedestrian pulse on Relay 2
    gate.updateInputs({true, false, true}, 200);
    TEST_ASSERT_EQUAL(gate::GateState::Closed, gate.state());
    TEST_ASSERT_TRUE(gate.relayOutputs().relay2);
}

void test_ha_mqtt_discovery_and_gateway_app() {
    class MockPublisher final : public core::IMqttPublisher {
    public:
        void publishMqtt(const mqtt::MqttMessage& msg) override { messages.push_back(msg); }
        std::vector<mqtt::MqttMessage> messages;
    };

    class MockObserver final : public core::IGatewayObserver {
    public:
        void onAccessDecision(bool g, const std::string& /*source*/, const std::string& /*user*/,
                              const std::string& /*code*/, std::uint64_t /*now_ms*/) override {
            ++decisions;
            last_granted = g;
        }
        void onUsersChanged() override { ++users_changed; }
        void onGateStateChanged(gate::GateState /*prev*/, gate::GateState next,
                                std::uint64_t /*now_ms*/) override {
            last_state = next;
        }
        int decisions{0};
        bool last_granted{false};
        int users_changed{0};
        gate::GateState last_state{gate::GateState::Unknown};
    };

    core::GatewayApp app;
    MockPublisher pub;
    MockObserver obs;
    app.setMqttPublisher(&pub);
    app.addObserver(&obs);
    app.store().upsertUser({0, "Valentinas", "2764857", "1234", true, access::RelayTarget::Primary, 0});

    const std::uint64_t raw = makeWiegand26(42, 12345);  // payload = (42<<16)|12345 = 2764857
    for (int i = 25; i >= 0; --i) {
        app.onWiegandBit(static_cast<std::uint8_t>((raw >> static_cast<unsigned>(i)) & 1ULL),
                         static_cast<std::uint64_t>((25 - i) * 2000));
    }
    app.tick(100, 100000);
    TEST_ASSERT_TRUE(app.gate().relayOutputs().relay1);
    TEST_ASSERT_EQUAL_STRING("Valentinas", app.lastUser().c_str());
    TEST_ASSERT_EQUAL(1, obs.decisions);
    TEST_ASSERT_TRUE(obs.last_granted);
    TEST_ASSERT_EQUAL(1, obs.users_changed);
    TEST_ASSERT_EQUAL(1, pub.messages.size());

    // Denied card triggers observer with granted=false and no user mutation
    const std::uint64_t unknown = makeWiegand26(7, 999);
    for (int i = 25; i >= 0; --i) {
        app.onWiegandBit(static_cast<std::uint8_t>((unknown >> static_cast<unsigned>(i)) & 1ULL),
                         static_cast<std::uint64_t>(500000 + (25 - i) * 2000));
    }
    app.tick(600, 600000);
    TEST_ASSERT_EQUAL(2, obs.decisions);
    TEST_ASSERT_FALSE(obs.last_granted);
    TEST_ASSERT_EQUAL(1, obs.users_changed);
    TEST_ASSERT_EQUAL(2, pub.messages.size());
    TEST_ASSERT_FALSE(app.store().lastUnknownCode().empty());

    const auto msgs = app.haMqtt().buildDiscovery(app.config(), "wg_aabbcc", "1.0.0");
    TEST_ASSERT_EQUAL(5, msgs.size());
    TEST_ASSERT_TRUE(msgs[0].topic.find("/cover/") != std::string::npos);

    core::DeviceConfig patched = app.config();
    TEST_ASSERT_TRUE(web::ApiJson::applyConfigPatch(
        "{\"relay\":{\"mode\":\"door\"},\"sensor\":{\"mode\":\"dual_limit\"}}", patched));
    TEST_ASSERT_EQUAL(core::DeviceMode::Door, patched.relay.mode);
    TEST_ASSERT_EQUAL(core::SensorMode::DualLimit, patched.sensor.mode);
}

void test_restart_button_and_door_hold_open() {
    core::RestartButton btn;
    TEST_ASSERT_EQUAL(core::ButtonAction::None, btn.poll(true, 100));
    TEST_ASSERT_EQUAL(core::ButtonAction::None, btn.poll(false, 120));  // glitch < 50ms

    TEST_ASSERT_EQUAL(core::ButtonAction::None, btn.poll(true, 1000));
    TEST_ASSERT_EQUAL(core::ButtonAction::Restart, btn.poll(false, 1200));

    TEST_ASSERT_EQUAL(core::ButtonAction::None, btn.poll(true, 2000));
    TEST_ASSERT_EQUAL(core::ButtonAction::SetupPortal, btn.poll(false, 7000));

    TEST_ASSERT_EQUAL(core::ButtonAction::None, btn.poll(true, 10000));
    TEST_ASSERT_EQUAL(core::ButtonAction::FactoryReset, btn.poll(false, 20500));

    TEST_ASSERT_EQUAL(gate::GateCommand::Open, *gate::parseGateCommand("OPEN"));
    TEST_ASSERT_EQUAL(gate::GateCommand::Pedestrian, *gate::parseGateCommand("ped"));
    TEST_ASSERT_FALSE(gate::parseGateCommand("unknown").has_value());

    gate::GateController door;
    core::RelayConfig rcfg;
    rcfg.mode = core::DeviceMode::Door;
    rcfg.relay1_hold_open = true;
    core::SensorConfig scfg;
    scfg.mode = core::SensorMode::TimerFallback;
    door.configure(rcfg, scfg, {});

    door.executeCommand(gate::GateCommand::Unlock, 100);
    TEST_ASSERT_TRUE(door.holdOpenActive());
    TEST_ASSERT_TRUE(door.relayOutputs().relay1);
    door.executeCommand(gate::GateCommand::Lock, 200);
    TEST_ASSERT_FALSE(door.holdOpenActive());
    TEST_ASSERT_FALSE(door.relayOutputs().relay1);
}

int main() {
    UNITY_BEGIN();
    RUN_TEST(test_wiegand_26_valid_and_bad_parity);
    RUN_TEST(test_wiegand_uhf_58bit_and_keypad_pin);
    RUN_TEST(test_access_store_crud_and_json_roundtrip);
    RUN_TEST(test_roger_b70_sc_state_decoder_and_relays);
    RUN_TEST(test_dual_limit_fault_and_rex);
    RUN_TEST(test_ha_mqtt_discovery_and_gateway_app);
    RUN_TEST(test_restart_button_and_door_hold_open);
    return UNITY_END();
}
