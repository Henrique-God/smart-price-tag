// main: orquestração do ciclo da etiqueta.
//
// Cada despertar do deep sleep reinicia o ESP32, então o ciclo inteiro roda
// uma única vez em setup() e termina em deep sleep; loop() nunca é alcançado.
// Os serviços não se chamam entre si: os dados entre eles passam por aqui.
//
// Estados (diagrama da documentação): Inicialização -> Conectando -> Verificando
// -> Decidindo -> Redesenhando (só se preciso) -> Encerrando.
//
// display.h não é incluído aqui: só render e display conhecem o e-paper.

#include <Arduino.h>
#include <string.h>

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
// Na rede local o broker fecha a conexão em poucos ms após o DISCONNECT.
constexpr uint32_t MQTT_DISCONNECT_TIMEOUT_MS = 1000;

// Um redesenho leva ~27 s; com menos prazo que isto, fica para o próximo despertar.
constexpr uint32_t REDRAW_MIN_BUDGET_MS = 30000;
constexpr uint32_t MIN_SLEEP_S = 1;

// static: juntos passam de 1,5 KB, melhor fora da pilha do setup()
StoredState state;
ConfigEnvelope envelope;
TagConfig config;

uint32_t budget_ms(uint32_t step_ms) {
    const uint32_t remaining = power_deadline_remaining_ms();
    return step_ms < remaining ? step_ms : remaining;
}

void log_state(const char* name) {
    SPT_LOGI(TAG, "estado: %s", name);
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

const char* screen_name(DisplayedScreen screen) {
    switch (screen) {
        case DisplayedScreen::Unconfigured:
            return "sem produto";
        case DisplayedScreen::Standard:
            return "padrão";
        case DisplayedScreen::Promotion:
            return "promoção";
        default:
            return "nenhuma";
    }
}

// Verificando: busca, autentica e interpreta a configuração retida. Se for
// aceita, guarda o texto e o `seq` em `state`; senão, mantém a última válida.
void receive_config() {
    const MqttFetchResult result = mqtt_fetch_config(&envelope, budget_ms(MQTT_FETCH_TIMEOUT_MS));
    SPT_LOGI(TAG, "busca da configuração: %s", fetch_result_name(result));
    if (result != MqttFetchResult::Received) {
        return;
    }
    uint32_t seq = 0;
    const AuthResult auth = auth_verify(envelope.data, envelope.data_len, envelope.hmac_hex,
                                        state.last_seq, &seq);
    SPT_LOGI(TAG, "autenticação: %s, seq=%lu (último aceito %lu)", auth_result_name(auth),
             static_cast<unsigned long>(seq), static_cast<unsigned long>(state.last_seq));
    // seq igual também é aceito: a retida é reentregue a cada ciclo (CONTRATO §6)
    if (auth != AuthResult::Ok && auth != AuthResult::Unchanged) {
        SPT_LOGW(TAG, "configuração rejeitada; o visor não muda");
        return;
    }
    if (!config_parse(envelope.data, envelope.data_len, &config)) {
        SPT_LOGW(TAG, "configuração autêntica, mas fora do contrato; descartada");
        return;
    }
    state.last_seq = seq;
    memcpy(state.config_data, envelope.data, envelope.data_len);
    state.config_data[envelope.data_len] = '\0';
    state.config_len = envelope.data_len;
    SPT_LOGI(TAG, "configuração aceita: versão %s", config.version);
}

// Decidindo: tela que o visor deveria mostrar com a configuração guardada.
DisplayedScreen desired_screen(bool has_config, int64_t now_utc) {
    if (!has_config || !config.has_product) {
        return DisplayedScreen::Unconfigured;
    }
    return config_promotion_active(config, now_utc) ? DisplayedScreen::Promotion
                                                    : DisplayedScreen::Standard;
}

// Redesenhando: desenha `screen` e, se der certo, registra em `state` o que está no visor.
bool redraw(DisplayedScreen screen, const char* version, const char* tag_id) {
    const bool ok = screen == DisplayedScreen::Unconfigured
                        ? render_unconfigured(tag_id)
                        : render_product(config.product, screen == DisplayedScreen::Promotion
                                                             ? &config.promotion
                                                             : nullptr);
    if (!ok) {
        return false;
    }
    state.screen = screen;
    snprintf(state.applied_version, sizeof(state.applied_version), "%s", version);
    state.promotion_expires_at =
        screen == DisplayedScreen::Promotion ? config.promotion.expires_at : 0;
    return true;
}

// Próximo despertar: o intervalo de verificação ou o fim da promoção exibida, o que vier antes.
uint32_t next_wake_s(int64_t now_utc) {
    uint32_t seconds = CHECK_INTERVAL_S;
    // Sem relógio válido não dá para calcular o fim: a promoção fica até a próxima verificação
    if (state.screen == DisplayedScreen::Promotion && now_utc != 0) {
        const int64_t left = state.promotion_expires_at - now_utc;
        if (left < static_cast<int64_t>(seconds)) {
            seconds = left > static_cast<int64_t>(MIN_SLEEP_S) ? static_cast<uint32_t>(left)
                                                                : MIN_SLEEP_S;
        }
    }
    return seconds;
}

void publish_status() {
    TagStatus status = {};
    snprintf(status.version, sizeof(status.version), "%s", state.applied_version);
    status.voltage_mv = power_battery_mv();
    status.rssi_dbm = net_rssi_dbm();
    snprintf(status.firmware, sizeof(status.firmware), "%s", FW_VERSION);
    status.timestamp = net_now_utc();
    mqtt_publish_status(status);
}
}  // namespace

void setup() {
    Serial.begin(115200);

    log_state("Inicialização");
    SPT_LOGI(TAG, "firmware %s", FW_VERSION);
    SPT_LOGI(TAG, "despertar: %s", power_wake_cause_name(power_wake_cause()));
    const char* tag_id = power_tag_id();
    SPT_LOGI(TAG, "etiqueta: %s", tag_id[0] != '\0' ? tag_id : "(indisponível)");
    if (!auth_begin()) {
        SPT_LOGE(TAG, "sem chave HMAC: nenhuma configuração será aceita");
    }
    store_load(&state);

    log_state("Conectando");
    const bool wifi_ok = net_connect(budget_ms(WIFI_TIMEOUT_MS));
    bool mqtt_ok = false;
    if (wifi_ok) {
        // O SNTP corre em paralelo com o MQTT; o relógio só é necessário ao decidir
        net_sync_time_start();
        mqtt_ok = tag_id[0] != '\0' && mqtt_connect(tag_id, budget_ms(MQTT_CONNECT_TIMEOUT_MS));
    }

    log_state("Verificando");
    if (mqtt_ok) {
        receive_config();
    } else {
        SPT_LOGW(TAG, "sem broker: usa a configuração guardada");
    }
    if (wifi_ok) {
        net_sync_time(budget_ms(NTP_TIMEOUT_MS));
        if (!mqtt_ok) {
            // Sem broker não há o que publicar: desliga o rádio antes de um possível redesenho
            net_disconnect();
        }
    }

    log_state("Decidindo");
    // O relógio do RTC sobrevive ao deep sleep: vale mesmo sem rede neste ciclo
    const int64_t now = net_now_utc();
    const bool has_config =
        state.config_len > 0 && config_parse(state.config_data, state.config_len, &config);
    const DisplayedScreen screen = desired_screen(has_config, now);
    const char* version = has_config ? config.version : "";
    const bool needs_redraw =
        screen != state.screen || strcmp(version, state.applied_version) != 0;
    SPT_LOGI(TAG, "visor: %s \"%s\" -> %s \"%s\" (agora %lld)%s", screen_name(state.screen),
             state.applied_version, screen_name(screen), version, static_cast<long long>(now),
             needs_redraw ? "" : ", sem redesenho");

    bool retry_soon = false;
    bool redraw_failed = false;
    if (needs_redraw) {
        if (power_deadline_remaining_ms() < REDRAW_MIN_BUDGET_MS) {
            SPT_LOGW(TAG, "só restam %lu ms do prazo: redesenho no próximo despertar",
                     static_cast<unsigned long>(power_deadline_remaining_ms()));
            retry_soon = true;
        } else {
            log_state("Redesenhando");
            redraw_failed = !redraw(screen, version, tag_id);
        }
    }

    log_state("Encerrando");
    store_save(state);
    if (mqtt_ok) {
        publish_status();
    }
    mqtt_disconnect(budget_ms(MQTT_DISCONNECT_TIMEOUT_MS));
    net_disconnect();

    uint32_t sleep_s = next_wake_s(now);
    if (retry_soon) {
        sleep_s = MIN_SLEEP_S;
    } else if (redraw_failed) {
        // Visor com defeito: não insistir a cada segundo gastando a bateria
        sleep_s = CHECK_INTERVAL_S;
    }
    SPT_LOGI(TAG, "ciclo de %lu ms; dormindo por %lu s", static_cast<unsigned long>(millis()),
             static_cast<unsigned long>(sleep_s));
    Serial.flush();
    power_deep_sleep(sleep_s);
}

void loop() {
    // Nunca alcançado: setup() sempre termina em deep sleep.
}
