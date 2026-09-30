#include "render.h"

#include "display.h"

bool render_product(const Product& product, const Promotion* promotion) {
    // TODO(F2): layouts padrão e de promoção em display_draw_full(), depois display_hibernate()
    (void)product;
    (void)promotion;
    return false;
}

bool render_unconfigured(const char* tag_id) {
    // TODO(F2): tela "etiqueta sem produto" com tag_id legível
    (void)tag_id;
    return false;
}

bool render_ean13_modules(const char* digits, uint8_t modules[RENDER_EAN13_MODULES]) {
    // TODO(F2): validar dígito verificador e codificar (guardas + conjuntos L/G/R pela paridade do 1º dígito)
    (void)digits;
    (void)modules;
    return false;
}
