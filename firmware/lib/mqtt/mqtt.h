// mqtt: conexão ao broker, recepção da configuração e publicação do estado
// (camada de serviços).
//
// Único módulo que conhece MQTT (PubSubClient fica escondido no .cpp).
// Tópicos: assina spt/{id}/config (mensagem retida) e publica em spt/{id}/status.
// Separa o envelope JSON {dados, hmac} recebido, mas NÃO verifica nem interpreta
// `dados`: isso é papel de `auth` e `config`, chamados pelo `main`.
// Pressupõe que `net` já conectou o Wi-Fi.
#pragma once

#include <stdint.h>

#include "spt_types.h"

// Resultado da espera pela configuração.
enum class MqttFetchResult : uint8_t {
    Received,       // envelope recebido e separado em *out
    NoMessage,      // nenhuma mensagem no tópico dentro do prazo
    Malformed,      // mensagem recebida, mas o envelope é inválido ou grande demais
    Disconnected,   // sem conexão com o broker
};

// Conecta ao broker de secrets.h usando `tag_id` como client id e usuário.
// Retorna false se não conectar em `timeout_ms`.
bool mqtt_connect(const char* tag_id, uint32_t timeout_ms);

// Assina spt/{id}/config e espera a mensagem retida por até `timeout_ms`.
// Em caso de sucesso, copia o texto exato de `dados` e o `hmac` para *out.
MqttFetchResult mqtt_fetch_config(ConfigEnvelope* out, uint32_t timeout_ms);

// Serializa `status` em JSON e publica em spt/{id}/status.
bool mqtt_publish_status(const TagStatus& status);

// Encerra a sessão com o broker.
void mqtt_disconnect();
