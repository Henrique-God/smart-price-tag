// net: Wi-Fi e relógio por SNTP (camada de serviços).
//
// Conecta à rede local com as credenciais de secrets.h, sincroniza o relógio
// em UTC e informa a qualidade do sinal. Não conhece MQTT nem o conteúdo das
// mensagens; não chama outros serviços.
#pragma once

#include <stdint.h>

// Conecta ao Wi-Fi em modo station. Retorna false se não conectar em `timeout_ms`.
bool net_connect(uint32_t timeout_ms);

// Sincroniza o relógio por SNTP. Após sucesso, net_now_utc() é confiável.
bool net_sync_time(uint32_t timeout_ms);

// Instante atual em epoch UTC (segundos). 0 se o relógio não foi sincronizado.
int64_t net_now_utc();

// Intensidade do sinal da rede conectada, em dBm. 0 se desconectado.
int16_t net_rssi_dbm();

// Desconecta e desliga o rádio. Chamar antes do deep sleep.
void net_disconnect();
