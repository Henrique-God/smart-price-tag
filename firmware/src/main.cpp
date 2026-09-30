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
}

void setup() {
    Serial.begin(115200);

    SPT_LOGI(TAG, "firmware %s", FW_VERSION);
    SPT_LOGI(TAG, "despertar: %s", power_wake_cause_name(power_wake_cause()));
    const char* tag_id = power_tag_id();
    SPT_LOGI(TAG, "etiqueta: %s", tag_id[0] != '\0' ? tag_id : "(indisponível)");

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
