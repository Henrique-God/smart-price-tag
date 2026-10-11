// net: Wi-Fi e relógio por SNTP (camada de serviços).
//
// Conecta à rede local com as credenciais de secrets.h, sincroniza o relógio
// em UTC e informa a qualidade do sinal. Não conhece MQTT nem o conteúdo das
// mensagens; não chama outros serviços.
#pragma once

#include <stdint.h>

// Conecta ao Wi-Fi em modo station. Retorna false se não conectar em `timeout_ms`.
bool net_connect(uint32_t timeout_ms);

// Dispara a sincronização do relógio por SNTP (pool.ntp.org): resolve o nome
// (até 1 s) e envia a consulta, sem esperar a resposta. Chame logo após
// conectar e faça outras etapas (MQTT) enquanto a resposta não chega.
void net_sync_time_start();

// Espera até `timeout_ms` pela sincronização disparada por net_sync_time_start()
// (dispara agora, se ainda não foi). Após sucesso, net_now_utc() é confiável.
bool net_sync_time(uint32_t timeout_ms);

// Instante atual em epoch UTC (segundos). 0 se o relógio não é válido
// (anterior a 2025, CONTRATO §8). O relógio do RTC sobrevive ao deep sleep.
int64_t net_now_utc();

// Intensidade do sinal da rede conectada, em dBm. 0 se desconectado.
int16_t net_rssi_dbm();

// Desconecta e desliga o rádio. Chamar antes do deep sleep.
void net_disconnect();
