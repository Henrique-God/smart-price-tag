// render: conteúdo do visor (camada de serviços).
//
// Desenha o layout padrão, o layout de promoção e o código de barras EAN-13,
// usando `display` como driver. Não sabe de onde vêm os dados nem decide se a
// promoção vale: o `main` passa o produto e, se aplicável, a promoção.
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "spt_types.h"

// Largura do EAN-13 em módulos (barras finas), incluindo as guardas.
constexpr size_t RENDER_EAN13_MODULES = 95;

// Desenha a etiqueta do produto. Com `promotion` == nullptr usa o layout
// padrão; caso contrário, o layout de promoção. Faz a atualização completa
// do visor e o hiberna. Retorna false se o visor falhar.
bool render_product(const Product& product, const Promotion* promotion);

// Desenha a tela de etiqueta ainda não configurada, exibindo `tag_id` para
// cadastro na aplicação.
bool render_unconfigured(const char* tag_id);

// Codifica `digits` (13 dígitos, com verificador) em módulos EAN-13:
// modules[i] = 1 para barra, 0 para espaço. Retorna false se `digits` for
// inválido (tamanho, caracteres ou dígito verificador). Função pura.
bool render_ean13_modules(const char* digits, uint8_t modules[RENDER_EAN13_MODULES]);
