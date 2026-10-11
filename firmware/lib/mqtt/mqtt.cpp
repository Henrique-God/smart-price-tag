#include "mqtt.h"

#include <stdio.h>
#include <string.h>

#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>

#include "spt_log.h"
#include "spt_secrets.h"

namespace {
constexpr char TAG[] = "mqtt";

// O buffer padrão do PubSubClient (256 bytes) descarta SEM erro o envelope
// de 274 bytes do contrato; 1024 cobre o máximo de 512 com folga (CONTRATO §4).
constexpr uint16_t BUFFER_SIZE = 1024;

// "spt/" + 12 hex + "/config" + '\0'
constexpr size_t TOPIC_SIZE = 4 + SPT_TAG_ID_SIZE + 7;

// Mensagem de estado: no máximo 256 bytes (CONTRATO §7).
constexpr size_t STATUS_SIZE = 256;

constexpr uint32_t RETRY_MS = 250;
constexpr uint32_t POLL_MS = 10;

// Trecho de `dados` por linha de log (o log trunca linhas longas).
constexpr int LOG_CHUNK = 120;

WiFiClient wifi_client;
PubSubClient client(wifi_client);

char tag_id_copy[SPT_TAG_ID_SIZE] = "";
char config_topic[TOPIC_SIZE] = "";

// Preenchidos pelo callback durante client.loop(); interpretados fora dele.
uint8_t rx_payload[BUFFER_SIZE];
size_t rx_len = 0;
bool rx_done = false;

void on_message(char* topic, uint8_t* payload, unsigned int length) {
    if (rx_done || strcmp(topic, config_topic) != 0) {
        return;
    }
    // O PubSubClient já descarta mensagens maiores que o próprio buffer
    rx_len = length < sizeof(rx_payload) ? length : sizeof(rx_payload);
    memcpy(rx_payload, payload, rx_len);
    rx_done = true;
}

// Texto que pode ir entre aspas no JSON sem escape.
bool json_plain(const char* text) {
    for (const char* c = text; *c != '\0'; ++c) {
        if (*c == '"' || *c == '\\' || static_cast<unsigned char>(*c) < 0x20) {
            return false;
        }
    }
    return true;
}

// Separa {dados, hmac} de rx_payload em *out. Copia o valor DECODIFICADO de
// `dados` byte a byte: é sobre esses bytes que o HMAC foi calculado.
MqttFetchResult parse_envelope(ConfigEnvelope* out) {
    JsonDocument doc;
    const DeserializationError err = deserializeJson(doc, rx_payload, rx_len);
    if (err) {
        SPT_LOGW(TAG, "envelope não é JSON válido: %s", err.c_str());
        return MqttFetchResult::Malformed;
    }

    JsonObject envelope = doc.as<JsonObject>();
    JsonVariant data = envelope["dados"];
    JsonVariant mac = envelope["hmac"];
    if (envelope.isNull() || envelope.size() != 2 || !data.is<JsonString>() ||
        !mac.is<JsonString>()) {
        SPT_LOGW(TAG, "envelope precisa ter exatamente os textos `dados` e `hmac`");
        return MqttFetchResult::Malformed;
    }

    const JsonString data_text = data.as<JsonString>();
    const JsonString mac_text = mac.as<JsonString>();
    if (data_text.size() >= sizeof(out->data)) {
        SPT_LOGW(TAG, "`dados` com %u bytes excede o limite de %u",
                 static_cast<unsigned>(data_text.size()),
                 static_cast<unsigned>(sizeof(out->data) - 1));
        return MqttFetchResult::Malformed;
    }
    if (mac_text.size() >= sizeof(out->hmac_hex)) {
        SPT_LOGW(TAG, "`hmac` com %u caracteres excede o limite de %u",
                 static_cast<unsigned>(mac_text.size()),
                 static_cast<unsigned>(sizeof(out->hmac_hex) - 1));
        return MqttFetchResult::Malformed;
    }

    memcpy(out->data, data_text.c_str(), data_text.size());
    out->data[data_text.size()] = '\0';
    out->data_len = data_text.size();
    memcpy(out->hmac_hex, mac_text.c_str(), mac_text.size());
    out->hmac_hex[mac_text.size()] = '\0';
    return MqttFetchResult::Received;
}
}  // namespace

bool mqtt_connect(const char* tag_id, uint32_t timeout_ms) {
    if (tag_id == nullptr || strlen(tag_id) != SPT_TAG_ID_SIZE - 1) {
        SPT_LOGE(TAG, "ID da etiqueta inválido; sem conexão ao broker");
        return false;
    }
    strncpy(tag_id_copy, tag_id, sizeof(tag_id_copy));
    snprintf(config_topic, sizeof(config_topic), "spt/%s/config", tag_id_copy);

    if (!client.setBufferSize(BUFFER_SIZE)) {
        SPT_LOGE(TAG, "sem memória para o buffer MQTT de %u bytes",
                 static_cast<unsigned>(BUFFER_SIZE));
        return false;
    }
    client.setServer(MQTT_HOST, MQTT_PORT);
    client.setCallback(on_message);

    const uint32_t start = millis();
    while (true) {
        const uint32_t elapsed = millis() - start;
        if (elapsed >= timeout_ms) {
            SPT_LOGW(TAG, "broker %s:%d não respondeu em %lu ms (estado %d)", MQTT_HOST,
                     MQTT_PORT, static_cast<unsigned long>(timeout_ms), client.state());
            return false;
        }
        // A conexão TCP e a espera do CONNACK dividem o prazo restante (mínimo de 1 s cada)
        const uint32_t step_s = (timeout_ms - elapsed) / 2000;
        wifi_client.setTimeout(step_s > 0 ? step_s : 1);
        client.setSocketTimeout(static_cast<uint16_t>(step_s > 0 ? step_s : 1));

        // Usuário = client id = tag_id; sessão limpa e sem Last Will (CONTRATO §2 e §3)
        if (client.connect(tag_id_copy, tag_id_copy, MQTT_PASSWORD)) {
            SPT_LOGI(TAG, "conectado ao broker %s:%d em %lu ms", MQTT_HOST, MQTT_PORT,
                     static_cast<unsigned long>(millis() - start));
            return true;
        }
        const int state = client.state();
        if (state == MQTT_CONNECT_BAD_CREDENTIALS || state == MQTT_CONNECT_UNAUTHORIZED) {
            // Repetir não muda a resposta do broker
            SPT_LOGE(TAG, "broker recusou usuário/senha (estado %d)", state);
            return false;
        }
        SPT_LOGD(TAG, "tentativa de conexão falhou (estado %d)", state);
        delay(RETRY_MS);
    }
}

MqttFetchResult mqtt_fetch_config(ConfigEnvelope* out, uint32_t timeout_ms) {
    if (!client.connected()) {
        return MqttFetchResult::Disconnected;
    }
    rx_done = false;
    rx_len = 0;
    if (!client.subscribe(config_topic, 1)) {
        SPT_LOGW(TAG, "falha ao assinar %s", config_topic);
        return MqttFetchResult::Disconnected;
    }
    SPT_LOGD(TAG, "assinado %s", config_topic);

    const uint32_t start = millis();
    while (!rx_done) {
        if (millis() - start >= timeout_ms) {
            SPT_LOGI(TAG, "nenhuma configuração retida em %lu ms",
                     static_cast<unsigned long>(timeout_ms));
            return MqttFetchResult::NoMessage;
        }
        if (!client.loop()) {
            SPT_LOGW(TAG, "conexão com o broker caiu durante a espera");
            return MqttFetchResult::Disconnected;
        }
        delay(POLL_MS);
    }

    if (rx_len == 0) {
        // Retida apagada pela aplicação
        SPT_LOGI(TAG, "configuração retida vazia");
        return MqttFetchResult::NoMessage;
    }
    SPT_LOGD(TAG, "mensagem de %u bytes em %lu ms", static_cast<unsigned>(rx_len),
             static_cast<unsigned long>(millis() - start));

    const MqttFetchResult result = parse_envelope(out);
    if (result == MqttFetchResult::Received) {
        SPT_LOGI(TAG, "config recebida: data_len=%u hmac=%s",
                 static_cast<unsigned>(out->data_len), out->hmac_hex);
        for (size_t i = 0; i < out->data_len; i += LOG_CHUNK) {
            SPT_LOGD(TAG, "dados[%u]: %.*s", static_cast<unsigned>(i), LOG_CHUNK, out->data + i);
        }
    }
    return result;
}

bool mqtt_publish_status(const TagStatus& status) {
    if (!client.connected()) {
        return false;
    }
    if (!json_plain(status.version) || !json_plain(status.firmware)) {
        SPT_LOGE(TAG, "estado com caracteres inválidos para JSON; não publicado");
        return false;
    }

    char payload[STATUS_SIZE];
    const int len = snprintf(payload, sizeof(payload),
                             "{\"versao\":\"%s\",\"tensao_mv\":%ld,\"rssi\":%d,"
                             "\"firmware\":\"%s\",\"instante\":%lld}",
                             status.version, static_cast<long>(status.voltage_mv),
                             static_cast<int>(status.rssi_dbm), status.firmware,
                             static_cast<long long>(status.timestamp));
    if (len < 0 || static_cast<size_t>(len) >= sizeof(payload)) {
        SPT_LOGE(TAG, "estado excede %u bytes", static_cast<unsigned>(STATUS_SIZE));
        return false;
    }

    char topic[TOPIC_SIZE];
    snprintf(topic, sizeof(topic), "spt/%s/status", tag_id_copy);
    // QoS 0, não retido (CONTRATO §3)
    if (!client.publish(topic, payload, false)) {
        SPT_LOGW(TAG, "falha ao publicar em %s", topic);
        return false;
    }
    SPT_LOGI(TAG, "estado publicado em %s: %s", topic, payload);
    return true;
}

void mqtt_disconnect() {
    if (client.connected()) {
        client.disconnect();
    }
    wifi_client.stop();
}
