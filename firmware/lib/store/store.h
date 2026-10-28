// store: memória não volátil (camada de persistência).
//
// Guarda entre ciclos, na NVS, o que a etiqueta precisa lembrar: o último `seq`
// aceito (proteção contra repetição), o texto da última configuração válida
// (para redesenhar o layout padrão sem rede quando a promoção vence, RF11) e o
// que está desenhado no visor (para decidir se é preciso redesenhar).
// Não interpreta nem valida o conteúdo.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "spt_types.h"

// Tela desenhada no visor por este firmware.
enum class DisplayedScreen : uint8_t {
    None,           // nada desenhado ainda (NVS apagada)
    Unconfigured,   // tela sem produto
    Standard,       // layout padrão do produto
    Promotion,      // layout de promoção
};

// Estado persistido entre despertares.
struct StoredState {
    uint32_t last_seq;                         // último `seq` aceito; 0 se nunca configurada
    char config_data[SPT_CONFIG_DATA_SIZE];    // texto de `dados` da última configuração válida
    size_t config_len;                         // bytes de config_data; 0 se nenhuma
    char applied_version[SPT_VERSION_SIZE];    // `versao` desenhada no visor; "" se nenhuma
    DisplayedScreen screen;                    // tela desenhada no visor
    int64_t promotion_expires_at;              // `expira_em` da promoção exibida (epoch UTC, s)
};

// Lê o estado salvo. Se não houver estado (primeira execução) ou a leitura
// falhar, preenche *out com valores padrão (zeros) e retorna false.
bool store_load(StoredState* out);

// Salva o estado, regravando só os campos que mudaram. Retorna false se a escrita falhar.
bool store_save(const StoredState& state);
