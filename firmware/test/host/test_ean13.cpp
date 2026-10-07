// Teste no PC de render_ean13_modules (F2), sem placa e sem visor.
//
// Compila o mesmo lib/render/render_ean13.cpp usado no firmware. Rode a partir
// de firmware/ (ver "Teste do EAN-13 no PC" no README):
//
//   g++ -std=gnu++11 -Wall -Wextra -I lib/render -I lib/types test/host/test_ean13.cpp lib/render/render_ean13.cpp -o .pio/test_ean13
//   .pio/test_ean13
//
// Saída 0 quando todos os casos passam.

#include <stdio.h>
#include <string.h>

#include "render.h"

namespace {

int failures = 0;

// Referências do AGENTS.md (F2), conferidas com uma biblioteca independente.
struct ValidCase {
    const char* digits;
    const char* expected;
};

const ValidCase VALID[] = {
    {"7891234567895",
     "10101101110010111001100100110110111101001110101010100111010100001000100100100011101001001110101"},
    {"7896089012453",
     "10101101110010111010111101001110110111001011101010111001011001101101100101110010011101000010101"},
};

struct InvalidCase {
    const char* name;
    const char* digits;
};

const InvalidCase INVALID[] = {
    {"verificador errado", "7891234567896"},
    {"12 digitos", "789123456789"},
    {"14 digitos", "78912345678950"},
    {"nao numerico", "789123456789a"},
    {"espaco no meio", "789123 567895"},
    {"vazio", ""},
    {"nulo", nullptr},
};

void check_valid(const ValidCase& c) {
    uint8_t modules[RENDER_EAN13_MODULES];
    char got[RENDER_EAN13_MODULES + 1];
    if (!render_ean13_modules(c.digits, modules)) {
        printf("FALHOU %s: retornou false\n", c.digits);
        failures++;
        return;
    }
    for (size_t i = 0; i < RENDER_EAN13_MODULES; i++) {
        got[i] = modules[i] ? '1' : '0';
    }
    got[RENDER_EAN13_MODULES] = '\0';
    if (strcmp(got, c.expected) != 0) {
        printf("FALHOU %s:\n  esperado %s\n  obtido   %s\n", c.digits, c.expected, got);
        failures++;
        return;
    }
    printf("ok     %s\n", c.digits);
}

void check_invalid(const InvalidCase& c) {
    uint8_t modules[RENDER_EAN13_MODULES];
    if (render_ean13_modules(c.digits, modules)) {
        printf("FALHOU %s: aceitou entrada invalida\n", c.name);
        failures++;
        return;
    }
    printf("ok     %s -> false\n", c.name);
}

}  // namespace

int main() {
    for (const ValidCase& c : VALID) {
        check_valid(c);
    }
    for (const InvalidCase& c : INVALID) {
        check_invalid(c);
    }
    printf("%s: %d falha(s)\n", failures == 0 ? "PASSOU" : "FALHOU", failures);
    return failures == 0 ? 0 : 1;
}
