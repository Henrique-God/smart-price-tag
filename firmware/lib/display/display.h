// display: driver do visor e-paper (camada de hardware).
//
// Encapsula o GxEPD2: inicialização do SPI e do painel, laço de páginas da
// atualização completa e hibernação. Não sabe O QUE desenhar; quem desenha é
// `render`, pela API do Adafruit GFX recebida no callback.
//
// Apenas `render` deve incluir este header (só render e display conhecem o e-paper).
#pragma once

#include <stdint.h>

#include <Adafruit_GFX.h>
#include <GxEPD2.h>

// Dimensões em paisagem (rotação aplicada por display_begin()).
constexpr int16_t DISPLAY_WIDTH = 296;
constexpr int16_t DISPLAY_HEIGHT = 128;

// Cores disponíveis no painel de três cores.
constexpr uint16_t DISPLAY_WHITE = GxEPD_WHITE;
constexpr uint16_t DISPLAY_BLACK = GxEPD_BLACK;
constexpr uint16_t DISPLAY_RED = GxEPD_RED;

// Desenha a tela inteira em `gfx`. Pode ser chamado mais de uma vez por
// atualização (uma por página), então deve ser determinístico e sem efeitos colaterais.
using DisplayDrawFn = void (*)(Adafruit_GFX& gfx, void* ctx);

// Inicializa SPI e painel em paisagem. Retorna false se o painel não responder.
bool display_begin();

// Atualização completa (painéis de três cores não têm atualização parcial).
// Chama `fn(gfx, ctx)` para cada página e espera o painel terminar.
bool display_draw_full(DisplayDrawFn fn, void* ctx);

// Desliga o painel (a imagem permanece). Chamar antes do deep sleep.
void display_hibernate();
