#include "display.h"

#include <Arduino.h>
#include <GxEPD2_3C.h>

#include "board.h"
#include "spt_log.h"

namespace {

constexpr char TAG[] = "display";

// Painel WeAct 2,9" 296x128 preto/branco/vermelho, controlador SSD1680.
// Se a imagem sair deslocada, espelhada ou só em preto, teste GxEPD2_290_Z13c
// (ver roteiro de bancada no AGENTS.md).
using Panel = GxEPD2_290_C90c;

// Buffer da altura inteira (uma única página): ~9,5 KB de RAM.
// O construtor só guarda os pinos; nada é enviado ao painel antes de display_begin().
GxEPD2_3C<Panel, Panel::HEIGHT> epd(Panel(PIN_EPD_CS, PIN_EPD_DC, PIN_EPD_RST, PIN_EPD_BUSY));

// O GxEPD2 chama SPI.begin() sem argumentos, que usa os pinos padrão do VSPI.
// Se board.h mudar CLK ou DIN, é preciso passar a usar epd.init(..., SPI, settings).
static_assert(PIN_EPD_CLK == SCK, "PIN_EPD_CLK deve ser o SCK padrão do VSPI (IO18)");
static_assert(PIN_EPD_DIN == MOSI, "PIN_EPD_DIN deve ser o MOSI padrão do VSPI (IO23)");

// Duração mínima plausível de uma atualização completa. O painel leva ~26 s
// (GxEPD2: full_refresh_time = 27000 ms); muito menos que isso significa que
// a biblioteca não esperou a BUSY, ou seja, a linha não está ligada.
constexpr uint32_t MIN_PLAUSIBLE_REFRESH_MS = 5000;

// Timeout interno do GxEPD2 para esta classe de painel (30 s por espera).
constexpr uint32_t GXEPD2_BUSY_TIMEOUT_MS = 30000;

// Após o reset, o SSD1680 baixa a BUSY em poucos ms.
constexpr uint32_t BUSY_IDLE_TIMEOUT_MS = 1000;

// Duração do pulso de reset do painel, em ms. 20 ms é o padrão do GxEPD2 para
// placas sem o circuito de reset "inteligente" da Waveshare, caso do módulo WeAct.
constexpr uint16_t RESET_DURATION_MS = 20;

// Diagnóstico interno do GxEPD2 (tempos de cada etapa) só no nível debug.
#if SPT_LOG_LEVEL >= SPT_LOG_LEVEL_DEBUG
constexpr uint32_t GXEPD2_DIAG_BITRATE = 115200;
#else
constexpr uint32_t GXEPD2_DIAG_BITRATE = 0;
#endif

bool ready = false;
uint32_t last_refresh_ms = 0;

// Espera a BUSY ficar em nível baixo. Usa pull-up interno durante a espera:
// com o painel ligado, a saída dele domina; com o fio solto, a linha fica alta
// e a função expira em vez de "passar" por causa de um pino flutuante.
bool wait_busy_low(uint32_t timeout_ms) {
    pinMode(PIN_EPD_BUSY, INPUT_PULLUP);
    const uint32_t start = millis();
    bool idle = false;
    while (millis() - start < timeout_ms) {
        if (digitalRead(PIN_EPD_BUSY) == LOW) {
            idle = true;
            break;
        }
        delay(5);
    }
    pinMode(PIN_EPD_BUSY, INPUT);  // devolve o pino como o GxEPD2 o configura
    return idle;
}

}  // namespace

bool display_begin() {
    epd.init(GXEPD2_DIAG_BITRATE, true, RESET_DURATION_MS, false);
    epd.setRotation(1);  // paisagem: 296 x 128

    if (!wait_busy_low(BUSY_IDLE_TIMEOUT_MS)) {
        SPT_LOGE(TAG, "BUSY (IO%u) não baixou após o reset: confira o fio de BUSY, "
                      "a alimentação do visor e o jumper de interface (4-line SPI)",
                 PIN_EPD_BUSY);
        ready = false;
        return false;
    }
    SPT_LOGD(TAG, "painel pronto, %dx%d", epd.width(), epd.height());
    ready = true;
    return true;
}

bool display_draw_full(DisplayDrawFn fn, void* ctx) {
    if (!ready) {
        SPT_LOGE(TAG, "display_draw_full sem display_begin bem-sucedido");
        return false;
    }

    const uint32_t start = millis();
    epd.setFullWindow();
    epd.firstPage();
    do {
        epd.fillScreen(DISPLAY_WHITE);
        fn(epd, ctx);
    } while (epd.nextPage());  // a última chamada envia o buffer e espera o refresh
    last_refresh_ms = millis() - start;

    if (last_refresh_ms < MIN_PLAUSIBLE_REFRESH_MS) {
        SPT_LOGE(TAG, "atualização terminou em %lu ms, rápido demais: a linha BUSY "
                      "não está sendo lida (fio solto ou pino errado)",
                 static_cast<unsigned long>(last_refresh_ms));
        return false;
    }
    if (last_refresh_ms >= GXEPD2_BUSY_TIMEOUT_MS) {
        SPT_LOGW(TAG, "atualização levou %lu ms: provável timeout da BUSY "
                      "(painel não terminou ou BUSY presa em nível alto)",
                 static_cast<unsigned long>(last_refresh_ms));
    } else {
        SPT_LOGI(TAG, "atualização completa em %lu ms",
                 static_cast<unsigned long>(last_refresh_ms));
    }
    return true;
}

uint32_t display_last_refresh_ms() {
    return last_refresh_ms;
}

void display_hibernate() {
    epd.hibernate();
}
