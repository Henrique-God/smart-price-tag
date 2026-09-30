#include "auth.h"

// Único módulo autorizado a ver a chave HMAC.
#define SPT_SECRETS_WITH_HMAC_KEY
#include "spt_secrets.h"

static_assert(sizeof(TAG_HMAC_KEY_HEX) == 64 + 1,
              "TAG_HMAC_KEY_HEX deve ter 64 caracteres hex (32 bytes)");

bool auth_begin() {
    // TODO(F4): decodificar TAG_HMAC_KEY_HEX para 32 bytes e rejeitar caracteres não hex
    return false;
}

AuthResult auth_verify(const char* data, size_t data_len, const char* hmac_hex,
                       uint32_t last_seq, uint32_t* out_seq) {
    // TODO(F4): HMAC-SHA256 (mbedtls) sobre data[0..data_len), truncar em 16 bytes,
    // comparar com hmac_hex em tempo constante; depois extrair `seq` e comparar com last_seq
    (void)data;
    (void)data_len;
    (void)hmac_hex;
    (void)last_seq;
    (void)out_seq;
    return AuthResult::Malformed;
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
