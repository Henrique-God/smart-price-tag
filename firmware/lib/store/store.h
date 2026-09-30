// store: memória não volátil (camada de persistência).
//
// Guarda entre ciclos, na NVS, o que a etiqueta precisa lembrar: o último `seq`
// aceito (proteção contra repetição) e o que está desenhado no visor (para
// decidir se é preciso redesenhar). Não interpreta nem valida o conteúdo.
#pragma once

#include <stdint.h>

#include "spt_types.h"

// Estado persistido entre despertares.
struct StoredState {
    uint32_t last_seq;                         // último `seq` aceito; 0 se nunca configurada
    char applied_version[SPT_VERSION_SIZE];    // `versao` desenhada no visor; "" se nenhuma
    bool showing_promotion;                    // o visor mostra o layout de promoção
    int64_t promotion_expires_at;              // `expira_em` da promoção exibida (epoch UTC, s)
};

// Lê o estado salvo. Se não houver estado (primeira execução) ou a leitura
// falhar, preenche *out com valores padrão (zeros) e retorna false.
bool store_load(StoredState* out);

// Salva o estado. Retorna false se a escrita falhar.
bool store_save(const StoredState& state);
