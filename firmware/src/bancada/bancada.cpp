// Programa de bancada: testa o hardware da etiqueta sem rede, sem broker e sem bateria.
//
// Não faz parte do firmware: só é compilado no ambiente `bancada`
// (pio run -e bancada -t upload && pio device monitor -e bancada).
// A placa pode ficar alimentada pelo USB.
//
// O que verifica:
//   1. comunicação SPI e linha BUSY entre ESP32 e visor (display_begin);
//   2. as três cores, a orientação e a escala real em mm (tela de teste);
//   3. o tempo de uma atualização completa (RNF02: <= 30 s);
//   4. o botão em IO33, por leitura direta e como fonte de despertar do deep sleep;
//   5. que a imagem permanece no visor durante o deep sleep (biestabilidade);
//   6. o módulo render (F2): EAN-13 (sem visor) e os layouts reais da etiqueta.
//
// Comandos pelo monitor serial:
//   r  redesenha (alternando entre as duas telas de teste)
//   e  autoteste do EAN-13 contra as referências do AGENTS.md (não usa o visor)
//   1  layout de promoção com os dados do vetor V1 do contrato
//   2  layout padrão com os dados do vetor V2 (acentos)
//   3  tela sem produto (vetor V3), com o ID desta placa
//   4  pior caso: nome de 20 "W", descrição de 30 "W", 999,99 em promoção
//   5  pior caso com acentos em maiúsculas
//   s  entra em deep sleep; acorda pelo botão ou em 60 s
//   ?  mostra os comandos
//
// As telas de teste usam as fontes ASCII do Adafruit GFX (sem acentos de
// propósito); as telas 1 a 5 usam o render, com as fontes U8g2.

#include <Arduino.h>
#include <Fonts/FreeSans9pt7b.h>
#include <Fonts/FreeSansBold12pt7b.h>
#include <Fonts/FreeSansBold9pt7b.h>
#include <driver/rtc_io.h>
#include <esp_sleep.h>

#include "board.h"
#include "display.h"
#include "power.h"
#include "render.h"
#include "spt_log.h"

#ifndef FW_VERSION
#define FW_VERSION "bancada"
#endif

namespace {

constexpr char TAG[] = "bancada";

// Intervalo mínimo entre dois redesenhos pedidos na bancada. Os painéis de
// três cores não devem ser atualizados em sequência rápida; isto também evita
// que um botão com repique dispare vários redesenhos seguidos.
constexpr uint32_t MIN_REDRAW_GAP_MS = 20000;
constexpr uint32_t DEBOUNCE_MS = 50;
constexpr uint32_t SLEEP_TEST_S = 60;

// Converte mm em pixels para as barras de calibração (ver DISPLAY_PX_PER_MM).
constexpr int16_t mm_to_px(float mm) {
    return static_cast<int16_t>(mm * DISPLAY_PX_PER_MM + 0.5f);
}

struct ScreenData {
    const char* tag_id;
    uint32_t last_refresh_ms;
    uint16_t button_presses;
};

void print_at(Adafruit_GFX& gfx, int16_t x, int16_t baseline, const GFXfont* font,
              uint16_t color, const char* text) {
    gfx.setFont(font);
    gfx.setTextColor(color);
    gfx.setCursor(x, baseline);
    gfx.print(text);
}

// Tela A: borda, textos em preto, bloco vermelho, bloco preto e barras de 10 mm e 40 mm.
void draw_test_screen(Adafruit_GFX& gfx, void* ctx) {
    const auto* data = static_cast<const ScreenData*>(ctx);
    char line[48];

    gfx.drawRect(0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_BLACK);

    // Se este texto aparecer no canto superior esquerdo e legível, a rotação está certa.
    print_at(gfx, 6, 17, &FreeSansBold9pt7b, DISPLAY_BLACK, "SUP. ESQ. - bancada");
    snprintf(line, sizeof(line), "ID %s", data->tag_id[0] != '\0' ? data->tag_id : "?");
    print_at(gfx, 6, 36, &FreeSans9pt7b, DISPLAY_BLACK, line);

    gfx.fillRect(6, 44, 104, 34, DISPLAY_RED);
    print_at(gfx, 14, 67, &FreeSansBold9pt7b, DISPLAY_WHITE, "VERMELHO");
    gfx.fillRect(116, 44, 80, 34, DISPLAY_BLACK);
    print_at(gfx, 128, 67, &FreeSansBold9pt7b, DISPLAY_WHITE, "PRETO");

    // Barra vertical de 10 mm (altura mínima dos dígitos do preço, RNF06).
    const int16_t bar10 = mm_to_px(10.0f);
    gfx.fillRect(206, 44, 6, bar10, DISPLAY_BLACK);
    print_at(gfx, 218, 64, &FreeSans9pt7b, DISPLAY_BLACK, "10 mm");

    // Barra horizontal de 40 mm (confere a escala no outro eixo).
    const int16_t bar40 = mm_to_px(40.0f);
    gfx.fillRect(6, 100, bar40, 6, DISPLAY_BLACK);
    print_at(gfx, bar40 + 14, 108, &FreeSans9pt7b, DISPLAY_BLACK, "40 mm");

    // Duração do redesenho anterior (o atual ainda está acontecendo).
    if (data->last_refresh_ms > 0) {
        snprintf(line, sizeof(line), "%lu.%lu s",
                 static_cast<unsigned long>(data->last_refresh_ms / 1000),
                 static_cast<unsigned long>((data->last_refresh_ms % 1000) / 100));
        gfx.setFont(nullptr);  // fonte padrão 6x8; com ela o cursor é o canto superior
        gfx.setTextColor(DISPLAY_BLACK);
        gfx.setCursor(244, 116);
        gfx.print(line);
    }
}

// Tela B: fundo vermelho (uniformidade da cor) com textos brancos e um bloco preto.
void draw_red_screen(Adafruit_GFX& gfx, void* ctx) {
    const auto* data = static_cast<const ScreenData*>(ctx);
    char line[48];

    gfx.fillScreen(DISPLAY_RED);
    print_at(gfx, 10, 30, &FreeSansBold12pt7b, DISPLAY_WHITE, "TELA 2: VERMELHO");
    gfx.fillRect(10, 46, 276, 40, DISPLAY_BLACK);
    snprintf(line, sizeof(line), "botao: %u toque(s)", data->button_presses);
    print_at(gfx, 20, 72, &FreeSansBold9pt7b, DISPLAY_WHITE, line);
    snprintf(line, sizeof(line), "ultimo redesenho: %lu.%lu s",
             static_cast<unsigned long>(data->last_refresh_ms / 1000),
             static_cast<unsigned long>((data->last_refresh_ms % 1000) / 100));
    print_at(gfx, 10, 112, &FreeSans9pt7b, DISPLAY_WHITE, line);
}

// Dados das telas do render. V1 a V3 são os vetores da seção 9 do contrato.
const Product V1_PRODUCT = {"Dipirona 500 mg", 1490, "caixa com 20 comprimidos", "7891234567895"};
const Promotion V1_PROMOTION = {1190, 1795680000};
const Product V2_PRODUCT = {"Café Pilão 500 g", 2490, "torrado e moído", "7896089012453"};
const Product WORST_PRODUCT = {"WWWWWWWWWWWWWWWWWWWW", 99999, "WWWWWWWWWWWWWWWWWWWWWWWWWWWWWW",
                               "7891234567895"};
const Product WORST_ACCENTS_PRODUCT = {"ÁÉÍÓÚÇÃÕÂÊÔÀÁÉÍÓÚÇÃÕ", 99999,
                                       "ãçéõúãçéõúãçéõúãçéõúãçéõúãçéõ", "7896089012453"};
const Promotion WORST_PROMOTION = {99998, 1795680000};

// Referências do AGENTS.md (F2); os mesmos casos de test/host/test_ean13.cpp.
struct Ean13Case {
    const char* digits;
    const char* expected;  // nullptr = deve ser rejeitado
};

const Ean13Case EAN13_CASES[] = {
    {"7891234567895",
     "10101101110010111001100100110110111101001110101010100111010100001000100100100011101001001110101"},
    {"7896089012453",
     "10101101110010111010111101001110110111001011101010111001011001101101100101110010011101000010101"},
    {"7891234567896", nullptr},   // verificador errado
    {"789123456789", nullptr},    // 12 dígitos
    {"78912345678950", nullptr},  // 14 dígitos
    {"789123456789a", nullptr},   // não numérico
    {"789123 567895", nullptr},   // espaço no meio
    {"", nullptr},
    {nullptr, nullptr},
};

ScreenData screen{"", 0, 0};
bool display_ok = false;
bool next_is_red = false;
uint32_t last_draw_end_ms = 0;
bool have_drawn = false;

bool button_pressed_raw() {
    return digitalRead(PIN_BUTTON) == LOW;  // ativo em nível baixo
}

void print_help() {
    SPT_LOGI(TAG, "comandos: r = redesenhar | s = deep sleep (acorda pelo botao ou em %lu s) | ? = ajuda",
             static_cast<unsigned long>(SLEEP_TEST_S));
    SPT_LOGI(TAG, "render: e = autoteste EAN-13 | 1 = V1 promocao | 2 = V2 acentos | 3 = sem produto"
                  " | 4 = pior caso | 5 = pior caso com acentos");
    SPT_LOGI(TAG, "o botao (IO%u) tambem redesenha", PIN_BUTTON);
}

// Confere se o visor respondeu e se já passou o intervalo mínimo desde o último redesenho.
bool can_redraw() {
    if (!display_ok) {
        SPT_LOGE(TAG, "visor nao inicializado; corrija a ligacao e aperte EN");
        return false;
    }
    const uint32_t since = millis() - last_draw_end_ms;
    if (have_drawn && since < MIN_REDRAW_GAP_MS) {
        SPT_LOGW(TAG, "aguarde mais %lu s antes de redesenhar",
                 static_cast<unsigned long>((MIN_REDRAW_GAP_MS - since + 999) / 1000));
        return false;
    }
    return true;
}

void redraw() {
    if (!can_redraw()) {
        return;
    }

    const bool red = next_is_red;
    SPT_LOGI(TAG, "redesenhando tela %s (leva ~25 s; o visor pisca varias vezes, e normal)",
             red ? "B (vermelha)" : "A (teste)");
    const bool ok = display_draw_full(red ? draw_red_screen : draw_test_screen, &screen);
    display_hibernate();
    last_draw_end_ms = millis();
    have_drawn = true;

    screen.last_refresh_ms = display_last_refresh_ms();
    const unsigned long ms = static_cast<unsigned long>(screen.last_refresh_ms);
    if (!ok) {
        SPT_LOGE(TAG, "FALHA no redesenho (%lu ms)", ms);
        return;
    }
    SPT_LOGI(TAG, "RNF02 (redesenho <= 30 s): %s, %lu ms", ms <= 30000 ? "OK" : "FALHOU", ms);
    next_is_red = !red;
}

// Autoteste de render_ean13_modules: não depende do visor.
void run_ean13_selftest() {
    unsigned failures = 0;
    uint8_t modules[RENDER_EAN13_MODULES];
    char got[RENDER_EAN13_MODULES + 1];
    for (const Ean13Case& c : EAN13_CASES) {
        const char* label =
            c.digits == nullptr ? "(nulo)" : (c.digits[0] == '\0' ? "(vazio)" : c.digits);
        const bool accepted = render_ean13_modules(c.digits, modules);
        if (c.expected == nullptr) {
            if (accepted) {
                failures++;
            }
            SPT_LOGI(TAG, "EAN13 %s: %s", label,
                     accepted ? "FALHOU (aceitou entrada invalida)" : "OK (rejeitado)");
            continue;
        }
        if (!accepted) {
            failures++;
            SPT_LOGI(TAG, "EAN13 %s: FALHOU (rejeitou codigo valido)", label);
            continue;
        }
        for (size_t i = 0; i < RENDER_EAN13_MODULES; i++) {
            got[i] = modules[i] != 0 ? '1' : '0';
        }
        got[RENDER_EAN13_MODULES] = '\0';
        if (strcmp(got, c.expected) != 0) {
            failures++;
            SPT_LOGI(TAG, "EAN13 %s: FALHOU", label);
            SPT_LOGI(TAG, "  esperado %s", c.expected);
            SPT_LOGI(TAG, "  obtido   %s", got);
            continue;
        }
        SPT_LOGI(TAG, "EAN13 %s: OK (igual a referencia)", label);
    }
    SPT_LOGI(TAG, "EAN13 autoteste: %s (%u falha(s))", failures == 0 ? "PASSOU" : "FALHOU",
             failures);
}

// Desenha uma tela do render pelo mesmo caminho do firmware (inicializa, desenha e hiberna).
void draw_render_screen(char which) {
    if (!can_redraw()) {
        return;
    }
    SPT_LOGI(TAG, "redesenhando tela %c do render (leva ~27 s)", which);
    bool ok = false;
    switch (which) {
        case '1':
            ok = render_product(V1_PRODUCT, &V1_PROMOTION);
            break;
        case '2':
            ok = render_product(V2_PRODUCT, nullptr);
            break;
        case '3':
            ok = render_unconfigured(screen.tag_id);
            break;
        case '4':
            ok = render_product(WORST_PRODUCT, &WORST_PROMOTION);
            break;
        case '5':
            ok = render_product(WORST_ACCENTS_PRODUCT, &WORST_PROMOTION);
            break;
        default:
            return;
    }
    last_draw_end_ms = millis();
    have_drawn = true;
    screen.last_refresh_ms = display_last_refresh_ms();
    const unsigned long ms = static_cast<unsigned long>(screen.last_refresh_ms);
    if (!ok) {
        SPT_LOGE(TAG, "FALHA no redesenho da tela %c (render retornou false)", which);
        return;
    }
    SPT_LOGI(TAG, "RNF02 (redesenho <= 30 s): %s, %lu ms", ms <= 30000 ? "OK" : "FALHOU", ms);
}

void enter_sleep_test() {
    SPT_LOGI(TAG, "deep sleep: aperte o botao para acordar (ou espere %lu s).",
             static_cast<unsigned long>(SLEEP_TEST_S));
    SPT_LOGI(TAG, "a imagem deve continuar no visor enquanto a placa dorme");
    Serial.flush();
    const gpio_num_t button = static_cast<gpio_num_t>(PIN_BUTTON);
    // Pull-up interno do domínio RTC, além do resistor externo de 10 kΩ.
    rtc_gpio_pullup_en(button);
    rtc_gpio_pulldown_dis(button);
    esp_sleep_enable_ext0_wakeup(button, 0);
    esp_sleep_enable_timer_wakeup(static_cast<uint64_t>(SLEEP_TEST_S) * 1000000ULL);
    esp_deep_sleep_start();
}

}  // namespace

void setup() {
    Serial.begin(115200);
    delay(200);

    const WakeCause cause = power_wake_cause();
    screen.tag_id = power_tag_id();

    SPT_LOGI(TAG, "=== bancada Smart Price Tag (%s) ===", FW_VERSION);
    SPT_LOGI(TAG, "despertar: %s | etiqueta: %s", power_wake_cause_name(cause),
             screen.tag_id[0] != '\0' ? screen.tag_id : "(indisponivel)");
    SPT_LOGI(TAG, "pinos: BUSY=%u RST=%u DC=%u CS=%u CLK=%u DIN=%u BOTAO=%u", PIN_EPD_BUSY,
             PIN_EPD_RST, PIN_EPD_DC, PIN_EPD_CS, PIN_EPD_CLK, PIN_EPD_DIN, PIN_BUTTON);

    // Depois de um despertar por ext0, o pino ainda está no domínio RTC: devolve ao GPIO comum.
    rtc_gpio_deinit(static_cast<gpio_num_t>(PIN_BUTTON));
    pinMode(PIN_BUTTON, INPUT_PULLUP);
    SPT_LOGI(TAG, "botao em repouso: %s",
             button_pressed_raw() ? "LOW (pressionado ou ligado errado!)" : "HIGH (ok)");

    run_ean13_selftest();

    display_ok = display_begin();
    SPT_LOGI(TAG, "visor (SPI + BUSY): %s", display_ok ? "OK" : "FALHOU");

    if (cause == WakeCause::Button || cause == WakeCause::Timer) {
        // Não redesenha: a imagem anterior deve ter permanecido durante o sono.
        SPT_LOGI(TAG, "acordou do deep sleep por %s: confira se a imagem continua no visor",
                 cause == WakeCause::Button ? "BOTAO (ext0 OK)" : "TEMPORIZADOR");
    } else {
        redraw();
    }
    print_help();
}

void loop() {
    // Botão: registra cada toque (detecção de borda com debounce) e redesenha.
    static bool last_state = false;
    static uint32_t last_change_ms = 0;
    const bool pressed = button_pressed_raw();
    if (pressed != last_state && millis() - last_change_ms > DEBOUNCE_MS) {
        last_change_ms = millis();
        last_state = pressed;
        if (pressed) {
            screen.button_presses++;
            SPT_LOGI(TAG, "botao pressionado (%u)", screen.button_presses);
            redraw();
        }
    }

    if (Serial.available() > 0) {
        const int c = Serial.read();
        if (c == 'r' || c == 'R') {
            redraw();
        } else if (c == 'e' || c == 'E') {
            run_ean13_selftest();
        } else if (c >= '1' && c <= '5') {
            draw_render_screen(static_cast<char>(c));
        } else if (c == 's' || c == 'S') {
            enter_sleep_test();
        } else if (c == '?') {
            print_help();
        }
    }
    delay(10);
}
