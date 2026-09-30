#include "mqtt.h"

#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>

#include "spt_secrets.h"

// TODO(F3): cliente PubSubClient sobre WiFiClient, com client.setBufferSize(1024):
// o buffer padrão de 256 bytes não comporta o envelope {dados, hmac}.

bool mqtt_connect(const char* tag_id, uint32_t timeout_ms) {
    // TODO(F3): setServer(MQTT_HOST, MQTT_PORT); connect(tag_id, tag_id, MQTT_PASSWORD) até timeout_ms
    (void)tag_id;
    (void)timeout_ms;
    return false;
}

MqttFetchResult mqtt_fetch_config(ConfigEnvelope* out, uint32_t timeout_ms) {
    // TODO(F3): assinar spt/{id}/config, chamar loop() até a mensagem retida chegar ou timeout_ms,
    // e separar o envelope com ArduinoJson copiando `dados` sem alterar nenhum byte
    (void)out;
    (void)timeout_ms;
    return MqttFetchResult::Disconnected;
}

bool mqtt_publish_status(const TagStatus& status) {
    // TODO(F3): serializar {versao, tensao_mv, rssi, firmware, instante} e publicar em spt/{id}/status
    (void)status;
    return false;
}

void mqtt_disconnect() {
    // TODO(F3): client.disconnect()
}
