// Modelo de segredos da etiqueta. Este arquivo é versionado: NÃO coloque valores reais aqui.
//
// Para configurar:
//   cp include/secrets.example.h include/secrets.h
// e preencha include/secrets.h, que está no .gitignore.
//
// Não inclua este arquivo diretamente: use "spt_secrets.h".
#pragma once

// Rede Wi-Fi local (usado apenas por `net`)
#define WIFI_SSID "minha-rede"
#define WIFI_PASSWORD "minha-senha"

// Broker MQTT (usado apenas por `mqtt`). O usuário MQTT é o próprio ID da etiqueta.
#define MQTT_HOST "192.168.0.10"
#define MQTT_PORT 1883
#define MQTT_PASSWORD "senha-da-etiqueta"

// Chave HMAC-SHA256 desta etiqueta: 32 bytes em hex (64 caracteres).
// Visível apenas para o módulo `auth`, que define SPT_SECRETS_WITH_HMAC_KEY antes de incluir.
#ifdef SPT_SECRETS_WITH_HMAC_KEY
#define TAG_HMAC_KEY_HEX "0000000000000000000000000000000000000000000000000000000000000000"
#endif
