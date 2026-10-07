// render: desenho dos layouts sobre o Adafruit GFX (uso interno do render).
//
// Separado de render.cpp, que cuida do visor, para que os layouts possam ser
// conferidos sem o e-paper (por exemplo, numa pré-visualização no PC).
// O main não inclui este header: usa render.h.
#pragma once

#include <Adafruit_GFX.h>

#include "spt_types.h"

// Desenha a etiqueta do produto (layout de promoção se `promotion` != nullptr).
// Pode ser chamada uma vez por página: não guarda estado entre chamadas.
void render_draw_product(Adafruit_GFX& gfx, const Product& product, const Promotion* promotion);

// Desenha a tela de etiqueta sem produto, com `tag_id` legível.
void render_draw_unconfigured(Adafruit_GFX& gfx, const char* tag_id);
