// auth: autenticidade e ordem da configuração (camada de serviços).
//
// Único módulo que manipula a chave secreta da etiqueta. Verifica o HMAC-SHA256
// (truncado em 128 bits) sobre o texto EXATO de `dados`, por isso recebe o texto
// bruto e nunca uma estrutura já interpretada. Também extrai o `seq` e o compara
// com o último aceito, para rejeitar repetições.
//
// Não lê nem grava a NVS: o `main` informa o último `seq` e persiste o novo via `store`.
#pragma once

#include <stddef.h>
#include <stdint.h>

// Resultado da verificação de uma configuração.
enum class AuthResult : uint8_t {
    Ok,          // HMAC válido e seq > último aceito: configuração nova
    Unchanged,   // HMAC válido e seq == último aceito: nada novo
    Replay,      // HMAC válido, mas seq < último aceito: rejeitar
    BadHmac,     // HMAC não confere: rejeitar
    Malformed,   // hmac_hex ou `seq` ausente/inválido
    NoKey,       // auth_begin() não carregou a chave
};

// Carrega a chave HMAC de secrets.h. Retorna false se a chave for inválida.
bool auth_begin();

// Verifica `data` (texto exato de `dados`, `data_len` bytes) contra `hmac_hex`
// (32 caracteres hex) e compara seu `seq` com `last_seq`.
// Com resultado Ok, Unchanged ou Replay, escreve o `seq` lido em *out_seq.
AuthResult auth_verify(const char* data, size_t data_len, const char* hmac_hex,
                       uint32_t last_seq, uint32_t* out_seq);

// Nome curto do resultado, para log.
const char* auth_result_name(AuthResult result);
