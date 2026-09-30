// Tipos compartilhados do contrato de mensagens (camada base).
//
// Contém apenas dados, sem lógica e sem dependência de Arduino, para que
// qualquer módulo possa usá-lo sem criar acoplamento com outro módulo e para
// que compile também no ambiente `native` de testes.
//
// Todos os textos são terminados em '\0'; os tamanhos já incluem o terminador.
#pragma once

#include <stddef.h>
#include <stdint.h>

constexpr size_t SPT_TAG_ID_SIZE = 13;         // 12 hex + '\0'
constexpr size_t SPT_NAME_SIZE = 64;           // UTF-8
constexpr size_t SPT_DESCRIPTION_SIZE = 128;   // UTF-8
constexpr size_t SPT_EAN13_SIZE = 14;          // 13 dígitos + '\0'
constexpr size_t SPT_VERSION_SIZE = 65;        // cabe um SHA-256 em hex
constexpr size_t SPT_FIRMWARE_SIZE = 16;
constexpr size_t SPT_HMAC_HEX_SIZE = 33;       // 32 hex (HMAC-SHA256 truncado em 128 bits) + '\0'
constexpr size_t SPT_CONFIG_DATA_SIZE = 768;   // texto bruto de `dados` + '\0'

// Produto exibido na etiqueta (campo `produto` da configuração).
struct Product {
    char name[SPT_NAME_SIZE];                  // `nome`
    int32_t price_cents;                       // `preco`, em centavos
    char description[SPT_DESCRIPTION_SIZE];    // `descricao`
    char ean13[SPT_EAN13_SIZE];                // `ean13`, 13 dígitos
};

// Preço promocional (campo `promocao` da configuração).
struct Promotion {
    int32_t price_cents;                       // `preco`, em centavos
    int64_t expires_at;                        // `expira_em`, epoch UTC em segundos
};

// Configuração da etiqueta já autenticada e interpretada.
struct TagConfig {
    bool has_product;                          // `produto` é opcional
    Product product;
    bool has_promotion;                        // `promocao` é opcional
    Promotion promotion;
    char version[SPT_VERSION_SIZE];            // `versao`, resumo do conteúdo
    uint32_t seq;                              // `seq`, crescente
};

// Estado publicado pela etiqueta em spt/{id}/status.
struct TagStatus {
    char version[SPT_VERSION_SIZE];            // `versao` aplicada no visor
    int32_t voltage_mv;                        // `tensao_mv`
    int16_t rssi_dbm;                          // `rssi`, em dBm
    char firmware[SPT_FIRMWARE_SIZE];          // `firmware`
    int64_t timestamp;                         // `instante`, epoch UTC em segundos
};

// Envelope recebido em spt/{id}/config, já separado em seus dois campos.
// `data` guarda o texto EXATO de `dados`, sobre o qual o HMAC foi calculado.
struct ConfigEnvelope {
    char data[SPT_CONFIG_DATA_SIZE];           // `dados`, configuração serializada
    size_t data_len;
    char hmac_hex[SPT_HMAC_HEX_SIZE];          // `hmac`, 32 caracteres hex
};
