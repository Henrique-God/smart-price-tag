#include "net.h"

#include <WiFi.h>

#include "spt_secrets.h"

bool net_connect(uint32_t timeout_ms) {
    // TODO(F3): WiFi.mode(WIFI_STA); WiFi.begin(WIFI_SSID, WIFI_PASSWORD); aguardar até timeout_ms
    (void)timeout_ms;
    return false;
}

bool net_sync_time(uint32_t timeout_ms) {
    // TODO(F3): configTime(0, 0, <servidores NTP>) e aguardar sincronização até timeout_ms
    (void)timeout_ms;
    return false;
}

int64_t net_now_utc() {
    // TODO(F3): time(nullptr), devolvendo 0 enquanto o relógio não estiver sincronizado
    return 0;
}

int16_t net_rssi_dbm() {
    // TODO(F3): WiFi.RSSI() quando conectado
    return 0;
}

void net_disconnect() {
    // TODO(F3): WiFi.disconnect(true); WiFi.mode(WIFI_OFF)
}
