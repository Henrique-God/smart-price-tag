// main: orquestração do ciclo da etiqueta.
//
// Cada despertar do deep sleep reinicia o ESP32, então o ciclo inteiro roda
// uma única vez em setup() e termina em deep sleep; loop() nunca é alcançado.
// Os serviços não se chamam entre si: os dados entre eles passam por aqui.
//
// display.h não é incluído aqui: só render e display conhecem o e-paper.

#include <Arduino.h>

#include "auth.h"
#include "config.h"
#include "mqtt.h"
#include "net.h"
#include "power.h"
#include "render.h"
#include "spt_log.h"
#include "store.h"

#ifndef FW_VERSION
#error "FW_VERSION não definido (ver build_flags em platformio.ini)"
#endif

#ifndef CHECK_INTERVAL_S
#error "CHECK_INTERVAL_S não definido (use -e prod ou -e demo)"
#endif

namespace {
constexpr char TAG[] = "main";

// Prazos de cada etapa de rede, sempre limitados pelo prazo total do ciclo.
constexpr uint32_t WIFI_TIMEOUT_MS = 15000;
constexpr uint32_t NTP_TIMEOUT_MS = 5000;
constexpr uint32_t MQTT_CONNECT_TIMEOUT_MS = 5000;
// A retida chega logo após a assinatura; sem ela, só se perde este tempo.
constexpr uint32_t MQTT_FETCH_TIMEOUT_MS = 3000;

uint32_t budget_ms(uint32_t step_ms) {
    const uint32_t remaining = power_deadline_remaining_ms();
    return step_ms < remaining ? step_ms : remaining;
}

const char* fetch_result_name(MqttFetchResult result) {
    switch (result) {
        case MqttFetchResult::Received:
            return "Received";
        case MqttFetchResult::NoMessage:
            return "NoMessage";
        case MqttFetchResult::Malformed:
            return "Malformed";
        default:
            return "Disconnected";
    }
}

// Etapa de rede da F3: busca a configuração e publica o estado, sem aplicar nada.
void network_step(const char* tag_id) {
    if (!net_connect(budget_ms(WIFI_TIMEOUT_MS))) {
        return;
    }
    // O SNTP corre em paralelo com o MQTT; o relógio só é necessário no estado
    net_sync_time_start();

    if (tag_id[0] == '\0' || !mqtt_connect(tag_id, budget_ms(MQTT_CONNECT_TIMEOUT_MS))) {
        net_disconnect();
        return;
    }
    // static: o envelope tem ~800 bytes, melhor fora da pilha do setup()
    static ConfigEnvelope envelope;
    const MqttFetchResult result = mqtt_fetch_config(&envelope, budget_ms(MQTT_FETCH_TIMEOUT_MS));
    SPT_LOGI(TAG, "busca da configuração: %s", fetch_result_name(result));
    net_sync_time(budget_ms(NTP_TIMEOUT_MS));

    TagStatus status = {};
    // TODO(F5): versão aplicada vinda do store
    status.voltage_mv = power_battery_mv();
    status.rssi_dbm = net_rssi_dbm();
    snprintf(status.firmware, sizeof(status.firmware), "%s", FW_VERSION);
    status.timestamp = net_now_utc();
    mqtt_publish_status(status);
    mqtt_disconnect();
    net_disconnect();
}
}  // namespace

void setup() {
    Serial.begin(115200);

    SPT_LOGI(TAG, "firmware %s", FW_VERSION);
    SPT_LOGI(TAG, "despertar: %s", power_wake_cause_name(power_wake_cause()));
    const char* tag_id = power_tag_id();
    SPT_LOGI(TAG, "etiqueta: %s", tag_id[0] != '\0' ? tag_id : "(indisponível)");

    network_step(tag_id);

    // TODO(F5): ciclo completo dentro de POWER_CYCLE_DEADLINE_MS:
    //   store_load -> net_connect/net_sync_time -> mqtt_connect/mqtt_fetch_config
    //   -> auth_verify -> config_parse -> render_* (se versão ou promoção mudou)
    //   -> store_save -> mqtt_publish_status -> desconectar -> agendar próximo despertar

    SPT_LOGI(TAG, "dormindo por %lu s", static_cast<unsigned long>(CHECK_INTERVAL_S));
    Serial.flush();
    power_deep_sleep(CHECK_INTERVAL_S);
}

void loop() {
    // Nunca alcançado: setup() sempre termina em deep sleep.
}
