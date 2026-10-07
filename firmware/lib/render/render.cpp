#include "render.h"

#include "display.h"
#include "render_draw.h"
#include "spt_log.h"

namespace {

constexpr char TAG[] = "render";

struct ProductScreen {
    const Product* product;
    const Promotion* promotion;
};

void draw_product(Adafruit_GFX& gfx, void* ctx) {
    const auto* screen = static_cast<const ProductScreen*>(ctx);
    render_draw_product(gfx, *screen->product, screen->promotion);
}

void draw_unconfigured(Adafruit_GFX& gfx, void* ctx) {
    render_draw_unconfigured(gfx, static_cast<const char*>(ctx));
}

// Inicializa o visor, desenha e hiberna o painel, mesmo se algo falhar antes.
bool draw_and_hibernate(DisplayDrawFn fn, void* ctx) {
    const bool ok = display_begin() && display_draw_full(fn, ctx);
    display_hibernate();
    if (!ok) {
        SPT_LOGE(TAG, "falha ao redesenhar o visor");
    }
    return ok;
}

}  // namespace

bool render_product(const Product& product, const Promotion* promotion) {
    SPT_LOGI(TAG, "desenhando layout %s: \"%s\"", promotion != nullptr ? "de promoção" : "padrão",
             product.name);
    ProductScreen screen{&product, promotion};
    return draw_and_hibernate(draw_product, &screen);
}

bool render_unconfigured(const char* tag_id) {
    SPT_LOGI(TAG, "desenhando tela sem produto");
    return draw_and_hibernate(draw_unconfigured, const_cast<char*>(tag_id));
}
