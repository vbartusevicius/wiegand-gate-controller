file(GLOB_RECURSE gateway_sources "*.cpp")

idf_component_register(
    SRCS ${gateway_sources}
    INCLUDE_DIRS "."
    REQUIRES nvs_flash freertos esp_app_format esp_driver_gpio esp_driver_i2c esp_adc esp_netif esp_wifi esp_event esp_http_server esp_partition app_update mqtt lwip esp_timer esp_hw_support spiffs
)

target_compile_options(${COMPONENT_LIB} PRIVATE -Wall -Wextra -Werror)
