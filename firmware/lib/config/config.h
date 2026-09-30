// config: interpretação da configuração (camada de serviços).
//
// Converte o texto de `dados` em TagConfig e valida os campos (tamanhos,
// EAN-13 com 13 dígitos, preços não negativos). Recebe APENAS conteúdo já
// aceito por `auth`; não verifica autenticidade nem ordem.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "spt_types.h"

// Interpreta `data` (JSON de `dados`, `data_len` bytes) em *out.
// Retorna false se o JSON for inválido ou algum campo violar o contrato;
// nesse caso *out fica zerado.
bool config_parse(const char* data, size_t data_len, TagConfig* out);

// Indica se a promoção de `cfg` existe e ainda vale no instante `now_utc` (epoch UTC, s).
bool config_promotion_active(const TagConfig& cfg, int64_t now_utc);
