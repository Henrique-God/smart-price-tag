// render: codificação EAN-13 em módulos.
//
// Arquivo sem dependência de Arduino nem do visor, para que o mesmo código
// seja testado no PC (test/host/test_ean13.cpp) e usado na placa.

#include "render.h"

namespace {

constexpr size_t EAN13_DIGITS = 13;
constexpr size_t DIGIT_MODULES = 7;

// Conjunto L (ímpar), 7 módulos por dígito, bit mais significativo primeiro.
// O conjunto R é o complemento de L; o conjunto G é R espelhado.
constexpr uint8_t L_CODES[10] = {
    0x0D, 0x19, 0x13, 0x3D, 0x23, 0x31, 0x2F, 0x3B, 0x37, 0x0B,
};

// Paridade dos dígitos 2 a 7 pelo primeiro dígito: bit 1 = conjunto G.
// O bit mais significativo (de 6) corresponde ao dígito 2.
constexpr uint8_t PARITY_G[10] = {
    0x00, 0x0B, 0x0D, 0x0E, 0x13, 0x19, 0x1C, 0x15, 0x16, 0x1A,
};

uint8_t reverse7(uint8_t code) {
    uint8_t out = 0;
    for (size_t i = 0; i < DIGIT_MODULES; i++) {
        out = static_cast<uint8_t>((out << 1) | ((code >> i) & 1));
    }
    return out;
}

// Escreve `count` módulos de `code` (bit mais significativo primeiro) a partir de `pos`.
size_t put_bits(uint8_t* modules, size_t pos, uint8_t code, size_t count) {
    for (size_t i = 0; i < count; i++) {
        modules[pos++] = static_cast<uint8_t>((code >> (count - 1 - i)) & 1);
    }
    return pos;
}

}  // namespace

bool render_ean13_modules(const char* digits, uint8_t modules[RENDER_EAN13_MODULES]) {
    if (digits == nullptr || modules == nullptr) {
        return false;
    }

    uint8_t d[EAN13_DIGITS];
    for (size_t i = 0; i < EAN13_DIGITS; i++) {
        if (digits[i] < '0' || digits[i] > '9') {
            return false;  // não numérico ou texto curto demais (achou o '\0')
        }
        d[i] = static_cast<uint8_t>(digits[i] - '0');
    }
    if (digits[EAN13_DIGITS] != '\0') {
        return false;  // texto longo demais
    }

    // Verificador: pesos 1 e 3 alternados a partir do primeiro dígito.
    unsigned sum = 0;
    for (size_t i = 0; i < EAN13_DIGITS - 1; i++) {
        sum += d[i] * ((i % 2 == 0) ? 1u : 3u);
    }
    if ((10 - sum % 10) % 10 != d[EAN13_DIGITS - 1]) {
        return false;
    }

    size_t pos = put_bits(modules, 0, 0x5, 3);  // guarda inicial 101
    const uint8_t parity = PARITY_G[d[0]];
    for (size_t i = 1; i <= 6; i++) {
        const bool use_g = ((parity >> (6 - i)) & 1) != 0;
        const uint8_t l = L_CODES[d[i]];
        pos = put_bits(modules, pos, use_g ? reverse7(static_cast<uint8_t>(~l & 0x7F)) : l,
                       DIGIT_MODULES);
    }
    pos = put_bits(modules, pos, 0x0A, 5);  // guarda central 01010
    for (size_t i = 7; i < EAN13_DIGITS; i++) {
        pos = put_bits(modules, pos, static_cast<uint8_t>(~L_CODES[d[i]] & 0x7F), DIGIT_MODULES);
    }
    put_bits(modules, pos, 0x5, 3);  // guarda final 101
    return true;
}
