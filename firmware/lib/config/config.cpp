#include "config.h"

#include <string.h>

#include <ArduinoJson.h>

#include "spt_log.h"

namespace {
constexpr char TAG[] = "config";

// Limites do CONTRATO §5 (textos em caracteres, não em bytes).
constexpr size_t NAME_MIN_CHARS = 1;
constexpr size_t NAME_MAX_CHARS = 20;
constexpr size_t DESCRIPTION_MAX_CHARS = 30;
constexpr int32_t PRICE_MIN_CENTS = 1;
constexpr int32_t PRICE_MAX_CENTS = 99999;
constexpr size_t VERSION_LEN = 8;
constexpr int32_t SEQ_MIN = 1;

// Conta os caracteres de um texto UTF-8. Retorna false se a codificação for inválida.
bool utf8_count(const char* text, size_t len, size_t* out_chars) {
    size_t chars = 0;
    size_t i = 0;
    while (i < len) {
        const uint8_t lead = static_cast<uint8_t>(text[i]);
        size_t extra;
        if (lead < 0x80) {
            extra = 0;
        } else if (lead >= 0xC2 && lead <= 0xDF) {
            extra = 1;
        } else if (lead >= 0xE0 && lead <= 0xEF) {
            extra = 2;
        } else if (lead >= 0xF0 && lead <= 0xF4) {
            extra = 3;
        } else {
            return false;
        }
        if (i + extra >= len) {
            return false;  // sequência cortada no fim do texto
        }
        for (size_t k = 1; k <= extra; ++k) {
            if ((static_cast<uint8_t>(text[i + k]) & 0xC0) != 0x80) {
                return false;
            }
        }
        i += extra + 1;
        ++chars;
    }
    *out_chars = chars;
    return true;
}

// Copia o texto `field` para `out` se tiver entre min_chars e max_chars caracteres e couber no buffer.
bool copy_text(JsonVariantConst field, size_t min_chars, size_t max_chars, char* out,
               size_t out_size, const char* name) {
    if (!field.is<JsonString>()) {
        SPT_LOGW(TAG, "%s ausente ou não é texto", name);
        return false;
    }
    const JsonString text = field.as<JsonString>();
    size_t chars = 0;
    if (!utf8_count(text.c_str(), text.size(), &chars)) {
        SPT_LOGW(TAG, "%s não é UTF-8 válido", name);
        return false;
    }
    if (chars < min_chars || chars > max_chars || text.size() >= out_size) {
        SPT_LOGW(TAG, "%s com %u caracteres fora de %u..%u", name, static_cast<unsigned>(chars),
                 static_cast<unsigned>(min_chars), static_cast<unsigned>(max_chars));
        return false;
    }
    memcpy(out, text.c_str(), text.size());
    out[text.size()] = '\0';
    return true;
}

// 13 dígitos com dígito verificador válido (pesos 1 e 3 a partir da esquerda).
bool ean13_valid(JsonVariantConst field, char* out) {
    if (!field.is<JsonString>()) {
        return false;
    }
    const JsonString text = field.as<JsonString>();
    if (text.size() != SPT_EAN13_SIZE - 1) {
        return false;
    }
    int sum = 0;
    for (size_t i = 0; i < text.size(); ++i) {
        const char c = text.c_str()[i];
        if (c < '0' || c > '9') {
            return false;
        }
        if (i < 12) {
            sum += (c - '0') * (i % 2 == 0 ? 1 : 3);
        }
    }
    if ((10 - sum % 10) % 10 != text.c_str()[12] - '0') {
        return false;
    }
    memcpy(out, text.c_str(), text.size());
    out[text.size()] = '\0';
    return true;
}

bool price_valid(JsonVariantConst field, int32_t max_cents, int32_t* out) {
    if (!field.is<int32_t>()) {
        return false;
    }
    const int32_t cents = field.as<int32_t>();
    if (cents < PRICE_MIN_CENTS || cents > max_cents) {
        return false;
    }
    *out = cents;
    return true;
}

bool parse_product(JsonObjectConst obj, Product* out) {
    if (!copy_text(obj["nome"], NAME_MIN_CHARS, NAME_MAX_CHARS, out->name, sizeof(out->name),
                   "produto.nome") ||
        !copy_text(obj["descricao"], 0, DESCRIPTION_MAX_CHARS, out->description,
                   sizeof(out->description), "produto.descricao")) {
        return false;
    }
    if (!price_valid(obj["preco"], PRICE_MAX_CENTS, &out->price_cents)) {
        SPT_LOGW(TAG, "produto.preco ausente ou fora de 1..99999");
        return false;
    }
    if (!ean13_valid(obj["ean13"], out->ean13)) {
        SPT_LOGW(TAG, "produto.ean13 não tem 13 dígitos com verificador válido");
        return false;
    }
    return true;
}

bool parse_promotion(JsonObjectConst obj, int32_t product_cents, Promotion* out) {
    // Preço promocional maior que 0 e menor que o do produto
    if (!price_valid(obj["preco"], product_cents - 1, &out->price_cents)) {
        SPT_LOGW(TAG, "promocao.preco ausente ou não é menor que o preço do produto");
        return false;
    }
    JsonVariantConst expires = obj["expira_em"];
    if (!expires.is<int64_t>() || expires.as<int64_t>() <= 0) {
        SPT_LOGW(TAG, "promocao.expira_em ausente ou inválido");
        return false;
    }
    out->expires_at = expires.as<int64_t>();
    return true;
}

bool version_valid(JsonVariantConst field, char* out) {
    if (!field.is<JsonString>()) {
        return false;
    }
    const JsonString text = field.as<JsonString>();
    if (text.size() != VERSION_LEN) {
        return false;
    }
    for (size_t i = 0; i < text.size(); ++i) {
        const char c = text.c_str()[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) {
            return false;
        }
    }
    memcpy(out, text.c_str(), text.size());
    out[text.size()] = '\0';
    return true;
}

bool parse_fields(JsonObjectConst root, TagConfig* out) {
    // `produto` e `promocao` são obrigatórios, mas podem ser null (CONTRATO §5)
    JsonVariantConst product = root["produto"];
    JsonVariantConst promotion = root["promocao"];
    if (product.isUnbound() || promotion.isUnbound()) {
        SPT_LOGW(TAG, "campo produto ou promocao ausente");
        return false;
    }
    if (!product.isNull()) {
        if (!product.is<JsonObjectConst>() ||
            !parse_product(product.as<JsonObjectConst>(), &out->product)) {
            return false;
        }
        out->has_product = true;
    }
    if (!promotion.isNull()) {
        if (!out->has_product) {
            SPT_LOGW(TAG, "promocao sem produto");
            return false;
        }
        if (!promotion.is<JsonObjectConst>() ||
            !parse_promotion(promotion.as<JsonObjectConst>(), out->product.price_cents,
                             &out->promotion)) {
            return false;
        }
        out->has_promotion = true;
    }
    if (!version_valid(root["versao"], out->version)) {
        SPT_LOGW(TAG, "versao ausente ou não tem 8 hex minúsculos");
        return false;
    }
    JsonVariantConst seq = root["seq"];
    if (!seq.is<int32_t>() || seq.as<int32_t>() < SEQ_MIN) {
        SPT_LOGW(TAG, "seq ausente ou fora de 1..2147483647");
        return false;
    }
    out->seq = static_cast<uint32_t>(seq.as<int32_t>());
    return true;
}
}  // namespace

bool config_parse(const char* data, size_t data_len, TagConfig* out) {
    memset(out, 0, sizeof(*out));
    JsonDocument doc;
    const DeserializationError err = deserializeJson(doc, data, data_len);
    if (err) {
        SPT_LOGW(TAG, "dados não são JSON válido: %s", err.c_str());
        return false;
    }
    if (!doc.is<JsonObjectConst>() || !parse_fields(doc.as<JsonObjectConst>(), out)) {
        memset(out, 0, sizeof(*out));
        return false;
    }
    return true;
}

bool config_promotion_active(const TagConfig& cfg, int64_t now_utc) {
    if (!cfg.has_promotion) {
        return false;
    }
    // Sem relógio válido não dá para saber se venceu: mantém a promoção
    return now_utc == 0 || now_utc < cfg.promotion.expires_at;
}
