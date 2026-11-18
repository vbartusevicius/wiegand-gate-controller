#include "firmware/net/NetworkManager.hpp"

#include <algorithm>
#include <cstdio>
#include <cstdlib>

#include <ArduinoJson.h>
#include <driver/gpio.h>
#include <esp_event.h>
#include <esp_http_server.h>
#include <esp_mac.h>
#include <esp_netif.h>
#include <esp_ota_ops.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <mqtt_client.h>

#include "firmware/Board.hpp"
#include "firmware/WebAssets.hpp"
#include "gate/GateTypes.hpp"

namespace gateway {
namespace firmware {

namespace {

class ScopedAppLock {
public:
    explicit ScopedAppLock(const NetworkManager& nm) : nm_(nm) { nm_.lockApp(); }
    ~ScopedAppLock() { nm_.unlockApp(); }
    ScopedAppLock(const ScopedAppLock&) = delete;
    ScopedAppLock& operator=(const ScopedAppLock&) = delete;

private:
    const NetworkManager& nm_;
};

NetworkManager* ctxFromReq(httpd_req_t* req) {
    return static_cast<NetworkManager*>(req->user_ctx);
}

std::uint64_t nowMs() {
    return static_cast<std::uint64_t>(esp_timer_get_time() / 1000LL);
}

std::string readBody(httpd_req_t* req, std::size_t max_len = 8192) {
    if (req->content_len == 0 || req->content_len > max_len) {
        return {};
    }
    std::string body(req->content_len, '\0');
    std::size_t received = 0;
    while (received < req->content_len) {
        const int r = httpd_req_recv(req, body.data() + received, req->content_len - received);
        if (r <= 0) {
            return {};
        }
        received += static_cast<std::size_t>(r);
    }
    return body;
}

esp_err_t sendJson(httpd_req_t* req, const std::string& json, const char* status = "200 OK") {
    httpd_resp_set_status(req, status);
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, json.data(), static_cast<ssize_t>(json.size()));
}

esp_err_t sendGzAsset(httpd_req_t* req, const std::uint8_t* data, std::size_t len, const char* mime) {
    httpd_resp_set_type(req, mime);
    httpd_resp_set_hdr(req, "Content-Encoding", "gzip");
    httpd_resp_set_hdr(req, "Cache-Control", "no-cache");
    return httpd_resp_send(req, reinterpret_cast<const char*>(data), static_cast<ssize_t>(len));
}

void wifiEventHandler(void* arg, esp_event_base_t base, std::int32_t id, void* /*data*/) {
    auto* nm = static_cast<NetworkManager*>(arg);
    if (base == WIFI_EVENT) {
        if (id == WIFI_EVENT_STA_START || id == WIFI_EVENT_STA_DISCONNECTED) {
            if (id == WIFI_EVENT_STA_DISCONNECTED) {
                nm->onWifiDisconnected();
            }
            esp_wifi_connect();
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        nm->onWifiConnected();
    }
}

void mqttEventHandler(void* arg, esp_event_base_t /*base*/, std::int32_t id, void* data) {
    auto* nm = static_cast<NetworkManager*>(arg);
    auto* ev = static_cast<esp_mqtt_event_handle_t>(data);
    switch (static_cast<esp_mqtt_event_id_t>(id)) {
    case MQTT_EVENT_CONNECTED:
        nm->onMqttConnected();
        break;
    case MQTT_EVENT_DISCONNECTED:
        nm->onMqttDisconnected();
        break;
    case MQTT_EVENT_DATA:
        if (ev != nullptr && ev->topic != nullptr && ev->data != nullptr) {
            nm->onMqttData(std::string(ev->topic, ev->topic_len), std::string(ev->data, ev->data_len));
        }
        break;
    default:
        break;
    }
}

esp_err_t handleIndex(httpd_req_t* req) {
    return sendGzAsset(req, web_assets::index_html_gz, web_assets::index_html_gz_size, "text/html");
}
esp_err_t handleCss(httpd_req_t* req) {
    return sendGzAsset(req, web_assets::app_css_gz, web_assets::app_css_gz_size, "text/css");
}
esp_err_t handleJs(httpd_req_t* req) {
    return sendGzAsset(req, web_assets::app_js_gz, web_assets::app_js_gz_size, "application/javascript");
}

esp_err_t handleGetStatus(httpd_req_t* req) {
    const auto* nm = ctxFromReq(req);
    std::string json;
    {
        const ScopedAppLock guard(*nm);
        const auto rt = nm->runtimeStatus(-1.0F, nowMs());
        json = web::ApiJson::buildStatus(nm->app()->config(), rt, nm->app()->gate(), nm->app()->store());
    }
    return sendJson(req, json);
}

esp_err_t handleGetConfig(httpd_req_t* req) {
    const auto* nm = ctxFromReq(req);
    std::string json;
    {
        const ScopedAppLock guard(*nm);
        json = web::ApiJson::buildConfig(nm->app()->config());
    }
    return sendJson(req, json);
}

esp_err_t handlePostConfig(httpd_req_t* req) {
    const std::string body = readBody(req);
    if (body.empty()) {
        return sendJson(req, "{\"ok\":false,\"error\":\"empty body\"}", "400 Bad Request");
    }
    const auto* nm = ctxFromReq(req);
    bool ok = false;
    {
        const ScopedAppLock guard(*nm);
        core::DeviceConfig next = nm->app()->config();
        ok = web::ApiJson::applyConfigPatch(body, next);
        if (ok) {
            nm->app()->applyConfig(next);
            nm->storage()->saveConfig(next);
        }
    }
    if (!ok) {
        return sendJson(req, "{\"ok\":false,\"error\":\"invalid json\"}", "400 Bad Request");
    }
    nm->notifyConfigSaved();
    return sendJson(req, "{\"ok\":true}");
}

esp_err_t handleGetUsers(httpd_req_t* req) {
    const auto* nm = ctxFromReq(req);
    std::string json;
    {
        const ScopedAppLock guard(*nm);
        json = web::ApiJson::buildUsers(nm->app()->store());
    }
    return sendJson(req, json);
}

esp_err_t handlePostUser(httpd_req_t* req) {
    const std::string body = readBody(req);
    access::UserEntry user;
    if (!web::ApiJson::parseUserUpsert(body, user)) {
        return sendJson(req, "{\"ok\":false,\"error\":\"invalid user\"}", "400 Bad Request");
    }
    const auto* nm = ctxFromReq(req);
    bool ok = false;
    {
        const ScopedAppLock guard(*nm);
        ok = nm->app()->store().upsertUser(std::move(user));
        if (ok) {
            nm->app()->store().clearLastUnknown();
            nm->storage()->saveUsers(nm->app()->store());
        }
    }
    return sendJson(req, ok ? "{\"ok\":true}" : "{\"ok\":false,\"error\":\"store full\"}",
                    ok ? "200 OK" : "400 Bad Request");
}

esp_err_t handleDeleteUser(httpd_req_t* req) {
    char query[64]{};
    std::uint32_t id = 0;
    if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK) {
        char val[16]{};
        if (httpd_query_key_value(query, "id", val, sizeof(val)) == ESP_OK) {
            id = static_cast<std::uint32_t>(std::strtoul(val, nullptr, 10));
        }
    }
    const auto* nm = ctxFromReq(req);
    bool ok = false;
    {
        const ScopedAppLock guard(*nm);
        ok = id != 0 && nm->app()->store().deleteUser(id);
        if (ok) {
            nm->storage()->saveUsers(nm->app()->store());
        }
    }
    return sendJson(req, ok ? "{\"ok\":true}" : "{\"ok\":false}", ok ? "200 OK" : "404 Not Found");
}

esp_err_t handleGetEvents(httpd_req_t* req) {
    const auto* nm = ctxFromReq(req);
    std::string json;
    {
        const ScopedAppLock guard(*nm);
        json = web::ApiJson::buildEvents(nm->app()->store());
    }
    return sendJson(req, json);
}

esp_err_t handleAction(httpd_req_t* req) {
    const std::string body = readBody(req, 512);
    JsonDocument doc;
    if (deserializeJson(doc, body) != DeserializationError::Ok) {
        return sendJson(req, "{\"ok\":false}", "400 Bad Request");
    }
    const std::string action = doc["action"] | "";
    const auto* nm = ctxFromReq(req);

    if (action == "reboot") {
        sendJson(req, "{\"ok\":true}");
        vTaskDelay(pdMS_TO_TICKS(150));
        esp_restart();
        return ESP_OK;
    }
    if (action == "factory_reset") {
        {
            const ScopedAppLock guard(*nm);
            nm->storage()->factoryReset();
        }
        sendJson(req, "{\"ok\":true}");
        vTaskDelay(pdMS_TO_TICKS(150));
        esp_restart();
        return ESP_OK;
    }

    bool ok = true;
    {
        const ScopedAppLock guard(*nm);
        if (const auto cmd = gate::parseGateCommand(action)) {
            nm->app()->onManualCommand(*cmd, "web", nowMs());
        } else if (action == "clear_unknown") {
            nm->app()->store().clearLastUnknown();
        } else {
            ok = false;
        }
    }
    return sendJson(req, ok ? "{\"ok\":true}" : "{\"ok\":false}", ok ? "200 OK" : "400 Bad Request");
}

esp_err_t handleOta(httpd_req_t* req) {
    const esp_partition_t* update_part = esp_ota_get_next_update_partition(nullptr);
    if (update_part == nullptr || req->content_len == 0) {
        return sendJson(req, "{\"ok\":false,\"error\":\"no partition\"}", "400 Bad Request");
    }

    esp_ota_handle_t ota = 0;
    if (esp_ota_begin(update_part, OTA_SIZE_UNKNOWN, &ota) != ESP_OK) {
        return sendJson(req, "{\"ok\":false,\"error\":\"ota begin failed\"}", "500 Internal Server Error");
    }

    char buf[1024];
    std::size_t remaining = req->content_len;
    while (remaining > 0) {
        const std::size_t want = std::min<std::size_t>(remaining, sizeof(buf));
        const int r = httpd_req_recv(req, buf, want);
        if (r <= 0) {
            esp_ota_abort(ota);
            return sendJson(req, "{\"ok\":false,\"error\":\"recv error\"}", "500 Internal Server Error");
        }
        if (esp_ota_write(ota, buf, static_cast<std::size_t>(r)) != ESP_OK) {
            esp_ota_abort(ota);
            return sendJson(req, "{\"ok\":false,\"error\":\"ota write failed\"}",
                            "500 Internal Server Error");
        }
        remaining -= static_cast<std::size_t>(r);
    }

    if (esp_ota_end(ota) != ESP_OK || esp_ota_set_boot_partition(update_part) != ESP_OK) {
        return sendJson(req, "{\"ok\":false,\"error\":\"ota verify failed\"}", "400 Bad Request");
    }

    sendJson(req, "{\"ok\":true,\"rebooting\":true}");
    vTaskDelay(pdMS_TO_TICKS(250));
    esp_restart();
    return ESP_OK;
}

}  // namespace

void NetworkManager::init(core::GatewayApp* app, Storage* storage, std::string fw_version, LockFn lock,
                          UnlockFn unlock, ConfigSavedFn on_cfg_saved) {
    app_ = app;
    storage_ = storage;
    fw_version_ = std::move(fw_version);
    lock_ = std::move(lock);
    unlock_ = std::move(unlock);
    on_cfg_saved_ = std::move(on_cfg_saved);

    // Enable Seeed XIAO ESP32-C6 external U.FL antenna switch: GPIO3=LOW, GPIO14=HIGH
    gpio_config_t rf_cfg{};
    rf_cfg.pin_bit_mask = (1ULL << board::rf_switch_power_pin) | (1ULL << board::rf_antenna_select_pin);
    rf_cfg.mode = GPIO_MODE_OUTPUT;
    gpio_config(&rf_cfg);
    gpio_set_level(board::rf_switch_power_pin, 0);
    gpio_set_level(board::rf_antenna_select_pin, 1);

    std::uint8_t mac[6]{};
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    char mac_buf[16]{};
    std::snprintf(mac_buf, sizeof(mac_buf), "%02X%02X%02X%02X%02X%02X", mac[0], mac[1], mac[2], mac[3],
                  mac[4], mac[5]);
    mac_hex_ = mac_buf;

    esp_netif_init();
    esp_event_loop_create_default();
}

void NetworkManager::startWifi(bool force_ap) {
    if (!wifi_started_) {
        esp_netif_create_default_wifi_sta();
        esp_netif_create_default_wifi_ap();
        wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
        esp_wifi_init(&init_cfg);
        esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifiEventHandler, this);
        esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifiEventHandler, this);
        wifi_started_ = true;
    } else {
        esp_wifi_stop();
    }

    core::WifiConfig wcfg;
    {
        const ScopedAppLock guard(*this);
        wcfg = app_->config().wifi;
    }

    const bool use_ap = force_ap || wcfg.ssid.empty();
    ap_mode_ = use_ap;
    wifi_connected_ = false;

    if (use_ap) {
        wifi_config_t ap_cfg{};
        const std::string ssid =
            "Wiegand-Gate-Controller-" + mac_hex_.substr(mac_hex_.size() >= 4 ? mac_hex_.size() - 4 : 0);
        std::snprintf(reinterpret_cast<char*>(ap_cfg.ap.ssid), sizeof(ap_cfg.ap.ssid), "%s", ssid.c_str());
        ap_cfg.ap.ssid_len = static_cast<std::uint8_t>(ssid.size());
        ap_cfg.ap.max_connection = 4;
        ap_cfg.ap.authmode = WIFI_AUTH_OPEN;
        esp_wifi_set_mode(WIFI_MODE_AP);
        esp_wifi_set_config(WIFI_IF_AP, &ap_cfg);
        esp_wifi_start();
        esp_wifi_set_max_tx_power(board::wifi_max_tx_power_quarter_dbm);
        ip_str_ = "192.168.4.1";
        return;
    }

    wifi_config_t sta_cfg{};
    std::snprintf(reinterpret_cast<char*>(sta_cfg.sta.ssid), sizeof(sta_cfg.sta.ssid), "%s",
                  wcfg.ssid.c_str());
    std::snprintf(reinterpret_cast<char*>(sta_cfg.sta.password), sizeof(sta_cfg.sta.password), "%s",
                  wcfg.password.c_str());
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &sta_cfg);
    esp_wifi_start();
    esp_wifi_set_max_tx_power(board::wifi_max_tx_power_quarter_dbm);
}

void NetworkManager::startMqtt() {
    stopMqtt();
    core::DeviceConfig cfg;
    {
        const ScopedAppLock guard(*this);
        cfg = app_->config();
    }
    if (!cfg.mqtt.enabled || cfg.mqtt.host.empty() || !wifi_connected_) {
        return;
    }

    char uri[128]{};
    std::snprintf(uri, sizeof(uri), "mqtt://%s:%u", cfg.mqtt.host.c_str(), cfg.mqtt.port);
    const std::string lwt_topic = mqtt::HomeAssistantMqtt::availabilityTopic(cfg);

    esp_mqtt_client_config_t mcfg{};
    mcfg.broker.address.uri = uri;
    mcfg.credentials.username = cfg.mqtt.username.empty() ? nullptr : cfg.mqtt.username.c_str();
    mcfg.credentials.authentication.password =
        cfg.mqtt.password.empty() ? nullptr : cfg.mqtt.password.c_str();
    mcfg.session.last_will.topic = lwt_topic.c_str();
    mcfg.session.last_will.msg = "offline";
    mcfg.session.last_will.qos = 1;
    mcfg.session.last_will.retain = 1;

    esp_mqtt_client_handle_t client = esp_mqtt_client_init(&mcfg);
    if (client != nullptr) {
        mqtt_ = client;
        esp_mqtt_client_register_event(client, MQTT_EVENT_ANY, mqttEventHandler, this);
        esp_mqtt_client_start(client);
    }
}

void NetworkManager::stopMqtt() {
    mqtt_connected_ = false;
    if (mqtt_ != nullptr) {
        auto* client = static_cast<esp_mqtt_client_handle_t>(mqtt_);
        esp_mqtt_client_stop(client);
        esp_mqtt_client_destroy(client);
        mqtt_ = nullptr;
    }
}

void NetworkManager::startHttp() {
    if (httpd_ != nullptr) {
        return;
    }
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.max_uri_handlers = 16;
    cfg.stack_size = 8192;
    httpd_handle_t server = nullptr;
    if (httpd_start(&server, &cfg) != ESP_OK) {
        return;
    }
    httpd_ = server;

    const httpd_uri_t uris[] = {
        {"/", HTTP_GET, handleIndex, this, false, false, nullptr},
        {"/app.css", HTTP_GET, handleCss, this, false, false, nullptr},
        {"/app.js", HTTP_GET, handleJs, this, false, false, nullptr},
        {"/api/status", HTTP_GET, handleGetStatus, this, false, false, nullptr},
        {"/api/config", HTTP_GET, handleGetConfig, this, false, false, nullptr},
        {"/api/config", HTTP_POST, handlePostConfig, this, false, false, nullptr},
        {"/api/users", HTTP_GET, handleGetUsers, this, false, false, nullptr},
        {"/api/users", HTTP_POST, handlePostUser, this, false, false, nullptr},
        {"/api/users", HTTP_DELETE, handleDeleteUser, this, false, false, nullptr},
        {"/api/events", HTTP_GET, handleGetEvents, this, false, false, nullptr},
        {"/api/action", HTTP_POST, handleAction, this, false, false, nullptr},
        {"/api/ota", HTTP_POST, handleOta, this, false, false, nullptr},
    };
    for (const auto& u : uris) {
        httpd_register_uri_handler(server, &u);
    }
}

void NetworkManager::publishMqtt(const mqtt::MqttMessage& msg) {
    if (!mqtt_connected_ || mqtt_ == nullptr) {
        return;
    }
    esp_mqtt_client_publish(static_cast<esp_mqtt_client_handle_t>(mqtt_), msg.topic.c_str(),
                            msg.payload.c_str(), static_cast<int>(msg.payload.size()), 1, msg.retain ? 1 : 0);
}

void NetworkManager::publishDiscoveryAndState(float vin_v) {
    core::DeviceConfig cfg;
    std::vector<mqtt::MqttMessage> msgs;
    mqtt::MqttMessage avail;
    {
        const ScopedAppLock guard(*this);
        cfg = app_->config();
        if (cfg.mqtt.ha_discovery) {
            msgs = app_->haMqtt().buildDiscovery(cfg, mqtt::HomeAssistantMqtt::nodeId(mac_hex_), fw_version_);
        }
        avail = app_->haMqtt().buildAvailability(cfg, true);
    }
    publishMqtt(avail);
    for (const auto& m : msgs) {
        publishMqtt(m);
    }
    publishState(vin_v);
}

void NetworkManager::publishState(float vin_v) {
    if (!mqtt_connected_) {
        return;
    }
    int rssi = 0;
    wifi_ap_record_t ap_info{};
    if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
        rssi = ap_info.rssi;
    }
    mqtt::MqttMessage msg;
    {
        const ScopedAppLock guard(*this);
        msg = app_->haMqtt().buildState(app_->config(), app_->gate().state(), vin_v, rssi, app_->lastUser(),
                                        app_->lastCode());
    }
    publishMqtt(msg);
}

web::RuntimeStatus NetworkManager::runtimeStatus(float vin_v, std::uint64_t uptime_ms) const {
    web::RuntimeStatus rt;
    rt.fw_version = fw_version_;
    rt.uptime_ms = uptime_ms;
    rt.vin_v = vin_v < 0.0F ? latest_vin_ : vin_v;
    rt.wifi_connected = wifi_connected_;
    rt.ap_mode = ap_mode_;
    rt.ip = ip_str_;
    rt.mac = mac_hex_;
    rt.mqtt_connected = mqtt_connected_;
    wifi_ap_record_t ap_info{};
    if (wifi_connected_ && esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
        rt.rssi_dbm = ap_info.rssi;
    }
    return rt;
}

void NetworkManager::onWifiConnected() {
    wifi_connected_ = true;
    ap_mode_ = false;
    esp_netif_t* netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (netif != nullptr) {
        esp_netif_ip_info_t ip{};
        if (esp_netif_get_ip_info(netif, &ip) == ESP_OK) {
            char buf[20]{};
            std::snprintf(buf, sizeof(buf), IPSTR, IP2STR(&ip.ip));
            ip_str_ = buf;
        }
    }
    startMqtt();
}

void NetworkManager::onWifiDisconnected() {
    wifi_connected_ = false;
    mqtt_connected_ = false;
}

void NetworkManager::onMqttConnected() {
    mqtt_connected_ = true;
    std::string cmd_topic;
    {
        const ScopedAppLock guard(*this);
        cmd_topic = mqtt::HomeAssistantMqtt::commandTopic(app_->config());
    }
    esp_mqtt_client_subscribe(static_cast<esp_mqtt_client_handle_t>(mqtt_), cmd_topic.c_str(), 1);
    publishDiscoveryAndState(latest_vin_);
}

void NetworkManager::onMqttDisconnected() {
    mqtt_connected_ = false;
}

void NetworkManager::onMqttData(const std::string& topic, const std::string& payload) {
    const ScopedAppLock guard(*this);
    const std::string cmd_topic = mqtt::HomeAssistantMqtt::commandTopic(app_->config());
    if (topic == cmd_topic) {
        app_->onMqttCommand(payload, nowMs());
    }
}

}  // namespace firmware
}  // namespace gateway
