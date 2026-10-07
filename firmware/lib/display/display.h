// display: driver do visor e-paper (camada de hardware).
//
// Encapsula o GxEPD2: inicialização do painel, laço de páginas da atualização
// completa e hibernação. Não sabe O QUE desenhar; quem desenha é `render`,
// pela API do Adafruit GFX recebida no callback.
//
// Apenas `render` deve incluir este header (só render e display conhecem o
// e-paper). Exceção: o programa de bancada em src/bancada/, que testa o
// hardware isoladamente e não entra nos ambientes prod e demo.
#pragma once

#include <stdint.h>

#include <Adafruit_GFX.h>
#include <GxEPD2.h>

// Dimensões em paisagem (rotação aplicada por display_begin()).
constexpr int16_t DISPLAY_WIDTH = 296;
constexpr int16_t DISPLAY_HEIGHT = 128;

// Escala do painel: área ativa de 66,89 x 29,05 mm (GDEM029C90).
// Útil para converter requisitos em mm (ex.: dígitos >= 10 mm => >= 45 px).
constexpr float DISPLAY_PX_PER_MM = 4.41f;

// Cores disponíveis no painel de três cores.
constexpr uint16_t DISPLAY_WHITE = GxEPD_WHITE;
constexpr uint16_t DISPLAY_BLACK = GxEPD_BLACK;
constexpr uint16_t DISPLAY_RED = GxEPD_RED;

// Desenha a tela inteira em `gfx`. Pode ser chamado mais de uma vez por
// atualização (uma por página), então deve ser determinístico e sem efeitos colaterais.
using DisplayDrawFn = void (*)(Adafruit_GFX& gfx, void* ctx);

// Inicializa SPI e painel em paisagem e confere a linha BUSY.
// Retorna false se a BUSY não voltar a nível baixo após o reset do painel
// (fio de BUSY solto, painel sem alimentação ou jumper de interface errado).
bool display_begin();

// Atualização completa (painéis de três cores não têm atualização parcial).
// Chama `fn(gfx, ctx)` para cada página e espera o painel terminar.
// Retorna false se display_begin() não foi bem-sucedido ou se a duração da
// atualização indicar que a linha BUSY não está funcionando.
bool display_draw_full(DisplayDrawFn fn, void* ctx);

// Duração da última atualização completa, em ms (0 se nenhuma ocorreu).
// Usada para verificar o RNF02 (redesenho <= 30 s).
uint32_t display_last_refresh_ms();

// Desliga o painel (a imagem permanece). Chamar antes do deep sleep.
// Depois de hibernar, a próxima display_draw_full() reinicia o painel sozinha.
void display_hibernate();
