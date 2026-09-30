#include "display.h"

#include <GxEPD2_3C.h>

#include "board.h"

namespace {

// Painel WeAct 2,9" 296x128 preto/branco/vermelho, controlador SSD1680.
// TODO(F2): confirmar na placa a classe GxEPD2_290_C90c (alternativa: GxEPD2_290_Z13c)
using Panel = GxEPD2_290_C90c;

// Buffer da altura inteira (uma única página): ~9,5 KB de RAM.
// O construtor só guarda os pinos; nada é enviado ao painel antes de display_begin().
GxEPD2_3C<Panel, Panel::HEIGHT> epd(Panel(PIN_EPD_CS, PIN_EPD_DC, PIN_EPD_RST, PIN_EPD_BUSY));

}  // namespace

bool display_begin() {
    // TODO(F2): epd.init(115200, true, 2, false), SPI em PIN_EPD_CLK/PIN_EPD_DIN, setRotation(1)
    return false;
}

bool display_draw_full(DisplayDrawFn fn, void* ctx) {
    // TODO(F2): setFullWindow(); firstPage(); do { fillScreen(DISPLAY_WHITE); fn(epd, ctx); } while (nextPage());
    (void)fn;
    (void)ctx;
    return false;
}

void display_hibernate() {
    // TODO(F2): epd.hibernate()
}
