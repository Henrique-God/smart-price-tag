#include "auth.h"

#include <string.h>

#include <ArduinoJson.h>
#include <mbedtls/md.h>

#include "spt_log.h"

// Único módulo autorizado a ver a chave HMAC.
#define SPT_SECRETS_WITH_HMAC_KEY
#include "spt_secrets.h"

static_assert(sizeof(TAG_HMAC_KEY_HEX) == 64 + 1,
              "TAG_HMAC_KEY_HEX deve ter 64 caracteres hex (32 bytes)");

namespace {
constexpr char TAG[] = "auth";

constexpr size_t KEY_SIZE = 32;
constexpr size_t KEY_HEX_LEN = 2 * KEY_SIZE;
// HMAC-SHA256 truncado em 128 bits (CONTRATO §6)
constexpr size_t MAC_SIZE = 16;
constexpr size_t MAC_HEX_LEN = 2 * MAC_SIZE;
constexpr size_t SHA256_SIZE = 32;

constexpr int32_t SEQ_MIN = 1;

uint8_t key[KEY_SIZE];
bool key_loaded = false;

// Valor de um dígito hex, ou -1. Maiúsculas só quando `allow_upper`.
int hex_value(char c, bool allow_upper) {
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return c - 'a' + 10;
    }
    if (allow_upper && c >= 'A' && c <= 'F') {
        return c - 'A' + 10;
    }
    return -1;
}

// Decodifica exatamente 2*size caracteres hex seguidos de '\0'.
bool decode_hex(const char* hex, size_t size, bool allow_upper, uint8_t* out) {
    if (hex == nullptr) {
        return false;
    }
    for (size_t i = 0; i < size; i++) {
        const int hi = hex_value(hex[2 * i], allow_upper);
        if (hi < 0) {
            return false;
        }
        const int lo = hex_value(hex[2 * i + 1], allow_upper);
        if (lo < 0) {
            return false;
        }
        out[i] = static_cast<uint8_t>((hi << 4) | lo);
    }
    return hex[2 * size] == '\0';
}

// Comparação que não para no primeiro byte diferente.
bool equal_constant_time(const uint8_t* a, const uint8_t* b, size_t size) {
    uint8_t diff = 0;
    for (size_t i = 0; i < size; i++) {
        diff |= a[i] ^ b[i];
    }
    return diff == 0;
}
}  // namespace

bool auth_begin() {
    return auth_begin_with_key_hex(TAG_HMAC_KEY_HEX);
}

bool auth_begin_with_key_hex(const char* key_hex) {
    uint8_t decoded[KEY_SIZE];
    const bool valid = decode_hex(key_hex, KEY_SIZE, true, decoded);
    if (valid) {
        memcpy(key, decoded, KEY_SIZE);
    } else {
        memset(key, 0, KEY_SIZE);
        SPT_LOGE(TAG, "chave HMAC inválida: esperados %u caracteres hex",
                 static_cast<unsigned>(KEY_HEX_LEN));
    }
    memset(decoded, 0, sizeof(decoded));
    key_loaded = valid;
    return valid;
}

AuthResult auth_verify(const char* data, size_t data_len, const char* hmac_hex,
                       uint32_t last_seq, uint32_t* out_seq) {
    if (!key_loaded) {
        return AuthResult::NoKey;
    }
    // Só hex minúsculo, como no contrato
    uint8_t received[MAC_SIZE];
    if (data == nullptr || !decode_hex(hmac_hex, MAC_SIZE, false, received)) {
        SPT_LOGW(TAG, "hmac deve ter %u caracteres hex minúsculos",
                 static_cast<unsigned>(MAC_HEX_LEN));
        return AuthResult::Malformed;
    }

    // O código é calculado ANTES de interpretar `dados` (CONTRATO §6)
    uint8_t computed[SHA256_SIZE];
    const mbedtls_md_info_t* info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if (info == nullptr ||
        mbedtls_md_hmac(info, key, KEY_SIZE, reinterpret_cast<const unsigned char*>(data),
                        data_len, computed) != 0) {
        SPT_LOGE(TAG, "falha ao calcular o HMAC");
        return AuthResult::BadHmac;
    }
    const bool match = equal_constant_time(computed, received, MAC_SIZE);
    memset(computed, 0, sizeof(computed));
    if (!match) {
        return AuthResult::BadHmac;
    }

    // Autêntico: lê apenas o campo `seq`
    JsonDocument filter;
    filter["seq"] = true;
    JsonDocument doc;
    const DeserializationError err =
        deserializeJson(doc, data, data_len, DeserializationOption::Filter(filter));
    if (err) {
        SPT_LOGW(TAG, "dados autênticos, mas JSON inválido: %s", err.c_str());
        return AuthResult::Malformed;
    }
    JsonVariant seq_field = doc["seq"];
    if (!seq_field.is<int32_t>() || seq_field.as<int32_t>() < SEQ_MIN) {
        SPT_LOGW(TAG, "seq ausente ou fora de 1..2147483647");
        return AuthResult::Malformed;
    }
    const uint32_t seq = static_cast<uint32_t>(seq_field.as<int32_t>());
    if (out_seq != nullptr) {
        *out_seq = seq;
    }

    if (seq < last_seq) {
        return AuthResult::Replay;
    }
    if (seq == last_seq) {
        return AuthResult::Unchanged;
    }
    return AuthResult::Ok;
}

const char* auth_result_name(AuthResult result) {
    switch (result) {
        case AuthResult::Ok:
            return "ok";
        case AuthResult::Unchanged:
            return "unchanged";
        case AuthResult::Replay:
            return "replay";
        case AuthResult::BadHmac:
            return "bad-hmac";
        case AuthResult::Malformed:
            return "malformed";
        case AuthResult::NoKey:
            return "no-key";
    }
    return "?";
}
