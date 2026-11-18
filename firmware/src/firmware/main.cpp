#include <cstdint>
#include <string>

#include <esp_ota_ops.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include "core/GatewayApp.hpp"
#include "core/GatewayEvents.hpp"
#include "core/RestartButton.hpp"
#include "firmware/drivers/Pca9534.hpp"
#include "firmware/drivers/RestartButtonDriver.hpp"
#include "firmware/drivers/RgbStatus.hpp"
#include "firmware/drivers/VinMonitor.hpp"
#include "firmware/drivers/WiegandHal.hpp"
#include "firmware/net/NetworkManager.hpp"
#include "firmware/storage/Storage.hpp"

#ifndef GATEWAY_FW_VERSION
#define GATEWAY_FW_VERSION "dev"
#endif

namespace {

class RuntimeObserver final : public gateway::core::IGatewayObserver {
public:
    explicit RuntimeObserver(gateway::firmware::RgbStatus& rgb) : rgb_(rgb) {}

    void onAccessDecision(bool granted, const std::string& /*source*/, const std::string& /*user*/,
                          const std::string& /*code*/, std::uint64_t now_ms) override {
        rgb_.flashAuth(granted, now_ms);
    }

    void onUsersChanged() override { users_dirty_ = true; }

    bool takeUsersDirty() {
        const bool dirty = users_dirty_;
        users_dirty_ = false;
        return dirty;
    }

private:
    gateway::firmware::RgbStatus& rgb_;
    bool users_dirty_{false};
};

}  // namespace

extern "C" void app_main() {
    using namespace gateway;

    firmware::Storage storage;
    storage.init();

    core::GatewayApp app;
    core::DeviceConfig cfg = app.config();
    storage.loadConfig(cfg);
    app.applyConfig(cfg);
    storage.loadUsers(app.store());

    firmware::Pca9534 expander;
    expander.init();

    firmware::WiegandHal wiegand_hal;
    wiegand_hal.init();

    firmware::RgbStatus rgb;
    rgb.init();

    firmware::VinMonitor vin_monitor;
    vin_monitor.init();

    firmware::RestartButtonDriver restart_btn;
    restart_btn.init();

    SemaphoreHandle_t app_mutex = xSemaphoreCreateRecursiveMutex();
    auto lock = [app_mutex]() { xSemaphoreTakeRecursive(app_mutex, portMAX_DELAY); };
    auto unlock = [app_mutex]() { xSemaphoreGiveRecursive(app_mutex); };

    firmware::NetworkManager net;
    RuntimeObserver observer(rgb);
    bool need_net_reload = false;

    app.addObserver(&observer);
    app.setMqttPublisher(&net);

    net.init(&app, &storage, GATEWAY_FW_VERSION, lock, unlock,
             [&need_net_reload]() { need_net_reload = true; });
    net.startWifi(false);
    net.startHttp();

    esp_ota_mark_app_valid_cancel_rollback();

    std::uint64_t last_state_pub_ms = 0;
    std::uint64_t last_vin_read_ms = 0;
    float vin_v = vin_monitor.readVolts();
    net.setLatestVin(vin_v);
    auto prev_gate_state = app.gate().state();

    while (true) {
        const std::uint64_t now_us = static_cast<std::uint64_t>(esp_timer_get_time());
        const std::uint64_t now_ms = now_us / 1000ULL;

        // 1. Hardware I/O sampling outside mutex where slow
        const auto raw_inputs = expander.readInputs();

        if ((now_ms - last_vin_read_ms) >= 1000ULL) {
            last_vin_read_ms = now_ms;
            vin_v = vin_monitor.readVolts();
            net.setLatestVin(vin_v);
        }

        const auto btn = restart_btn.poll(now_ms);
        if (btn == core::ButtonAction::Restart) {
            esp_restart();
        } else if (btn == core::ButtonAction::SetupPortal) {
            net.startWifi(true);
        } else if (btn == core::ButtonAction::FactoryReset) {
            storage.factoryReset();
            esp_restart();
        }

        // 2. Run deterministic gateway core under mutex
        lock();
        wiegand_hal.drain(app);
        app.onInputs(raw_inputs, now_ms);
        app.tick(now_ms, now_us);

        const auto relays = app.gate().relayOutputs();
        const auto fb = app.gate().readerFeedback();
        const auto gate_state = app.gate().state();
        const bool save_users = observer.takeUsersDirty();
        const bool reload = need_net_reload;
        need_net_reload = false;
        unlock();

        // 3. Drive outputs & persistence
        expander.writeOutputs(relays.relay1, relays.relay2, fb.led_active, fb.beep_active);
        rgb.update(net.wifiConnected(), net.apMode(), net.mqttConnected(), gate_state, now_ms);

        if (save_users) {
            lock();
            storage.saveUsers(app.store());
            unlock();
        }
        if (reload) {
            net.startWifi(false);
            net.startMqtt();
        }
        if (gate_state != prev_gate_state || (now_ms - last_state_pub_ms) >= 30000ULL) {
            prev_gate_state = gate_state;
            last_state_pub_ms = now_ms;
            net.publishState(vin_v);
        }

        vTaskDelay(pdMS_TO_TICKS(5));
    }
}
