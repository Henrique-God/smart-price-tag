#include "power.h"

#include <stdio.h>

#include <Arduino.h>
#include <driver/rtc_io.h>
#include <esp_sleep.h>
#include <esp_system.h>

#include "board.h"
#include "spt_log.h"
#include "spt_types.h"

namespace {
constexpr char TAG[] = "power";
}

WakeCause power_wake_cause() {
    switch (esp_sleep_get_wakeup_cause()) {
        case ESP_SLEEP_WAKEUP_UNDEFINED:
            return WakeCause::Reset;
        case ESP_SLEEP_WAKEUP_TIMER:
            return WakeCause::Timer;
        case ESP_SLEEP_WAKEUP_EXT0:
            return WakeCause::Button;
        default:
            return WakeCause::Other;
    }
}

const char* power_wake_cause_name(WakeCause cause) {
    switch (cause) {
        case WakeCause::Reset:
            return "reset";
        case WakeCause::Timer:
            return "timer";
        case WakeCause::Button:
            return "button";
        default:
            return "other";
    }
}

const char* power_tag_id() {
    static char id[SPT_TAG_ID_SIZE] = "";
    if (id[0] == '\0') {
        // MAC station vem do eFuse; não é preciso ligar o Wi-Fi para lê-lo
        uint8_t mac[6] = {};
        esp_err_t err = esp_read_mac(mac, ESP_MAC_WIFI_STA);
        if (err != ESP_OK) {
            SPT_LOGE(TAG, "falha ao ler o MAC: %s", esp_err_to_name(err));
            return id;
        }
        // MAC zerado não identifica a etiqueta: várias usariam os mesmos tópicos
        bool all_zero = true;
        for (uint8_t byte : mac) {
            all_zero = all_zero && byte == 0;
        }
        if (all_zero) {
            SPT_LOGE(TAG, "MAC inválido (todo zero)");
            return id;
        }
        snprintf(id, sizeof(id), "%02x%02x%02x%02x%02x%02x",
                 mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    }
    return id;
}

uint16_t power_battery_mv() {
    // analogReadMilliVolts já aplica a calibração do eFuse; sem bateria (só USB) fica perto de 0
    const uint32_t mv = analogReadMilliVolts(PIN_BATTERY) * BATTERY_DIVIDER;
    return mv > UINT16_MAX ? UINT16_MAX : static_cast<uint16_t>(mv);
}

uint32_t power_deadline_remaining_ms() {
    const uint32_t elapsed = millis();
    return elapsed >= POWER_CYCLE_DEADLINE_MS ? 0 : POWER_CYCLE_DEADLINE_MS - elapsed;
}

void power_deep_sleep(uint32_t seconds) {
    esp_sleep_enable_timer_wakeup(static_cast<uint64_t>(seconds) * 1000000ULL);
    // Botão ativo em nível baixo; o pull-up do domínio RTC continua ligado durante o sono.
    // Quem usar o pino como GPIO comum depois de um despertar por ext0 precisa de rtc_gpio_deinit.
    const gpio_num_t button = static_cast<gpio_num_t>(PIN_BUTTON);
    rtc_gpio_pullup_en(button);
    rtc_gpio_pulldown_dis(button);
    esp_sleep_enable_ext0_wakeup(button, 0);
    esp_deep_sleep_start();
}
