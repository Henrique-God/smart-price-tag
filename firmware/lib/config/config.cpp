#include "config.h"

#include <string.h>

#include <ArduinoJson.h>

bool config_parse(const char* data, size_t data_len, TagConfig* out) {
    // TODO(F5): deserializeJson de data[0..data_len) e preencher/validar produto, promocao, versao e seq
    (void)data;
    (void)data_len;
    memset(out, 0, sizeof(*out));
    return false;
}

bool config_promotion_active(const TagConfig& cfg, int64_t now_utc) {
    // TODO(F5): cfg.has_promotion && now_utc < cfg.promotion.expires_at (relógio não sincronizado → decidir)
    (void)cfg;
    (void)now_utc;
    return false;
}
