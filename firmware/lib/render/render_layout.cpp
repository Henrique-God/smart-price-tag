// render: layouts padrão, de promoção e de etiqueta sem produto.
//
// Coordenadas em paisagem (296 x 128 px, 4,41 px/mm). Orçamento vertical, pela
// caixa de tinta das fontes (maiúsculas acentuadas e descendentes como "ç" e "g"):
//   y   1–23   nome (helvB14: 18 px acima e 4 abaixo da linha de base)
//   y  24–40   descrição (helvR10: 14 px acima e 2 abaixo)
//   y  41–89   "R$" + preço (logisoso46: dígitos de 46 px = 10,4 mm, RNF06; vírgula 2 px abaixo)
//   y  92–125  EAN-13, 2 px por módulo, sempre preto sobre branco (RNF07)
// Textos com acentos usam fontes U8g2 "_tf" (Latin-1) pela U8g2_for_Adafruit_GFX.

#include <stdio.h>
#include <string.h>

#include <U8g2_for_Adafruit_GFX.h>

#include "display.h"
#include "render.h"
#include "render_draw.h"
#include "spt_log.h"

namespace {

constexpr char TAG[] = "render";

constexpr int16_t MARGIN = 4;
constexpr int16_t TEXT_WIDTH = DISPLAY_WIDTH - 2 * MARGIN;  // 288 px

// Fontes do nome, da maior para a menor. Pior caso de 20 caracteres largos
// ("W"): helvB14 = 339 px, helvB12 = 299 px, helvB10 = 280 px.
const uint8_t* const NAME_FONTS[] = {
    u8g2_font_helvB14_tf,
    u8g2_font_helvB12_tf,
    u8g2_font_helvB10_tf,
};
constexpr int16_t NAME_BASELINE = 19;

// Fontes da descrição. Pior caso de 30 caracteres largos: helvR10 = 390 px,
// helvR08 = 270 px.
const uint8_t* const DESCRIPTION_FONTS[] = {
    u8g2_font_helvR10_tf,
    u8g2_font_helvR08_tf,
};
constexpr int16_t DESCRIPTION_BASELINE = 38;

// Preço: "R$" alinhado ao topo dos dígitos, à esquerda. Pior caso "999,99" = 163 px.
const uint8_t* const PRICE_FONT = u8g2_font_logisoso46_tn;
const uint8_t* const CURRENCY_FONT = u8g2_font_helvB14_tf;
constexpr int16_t PRICE_BASELINE = 87;
constexpr int16_t PRICE_TOP = PRICE_BASELINE - 46;  // altura dos dígitos da logisoso46
constexpr int16_t CURRENCY_GAP = 4;

// Promoção: coluna à direita do preço, alinhada à margem direita, com o preço
// anterior riscado (preto) e o destaque "OFERTA" (vermelho, RF10).
const uint8_t* const OLD_PRICE_FONT = u8g2_font_helvB12_tf;
const uint8_t* const OFFER_FONT = u8g2_font_helvB12_tf;
constexpr char OFFER_TEXT[] = "OFERTA";
constexpr int16_t OLD_PRICE_BASELINE = 56;
constexpr int16_t OFFER_TOP = 64;
constexpr int16_t OFFER_HEIGHT = 22;
constexpr int16_t OFFER_PADDING = 4;
constexpr int16_t STRIKE_THICKNESS = 2;

// EAN-13: 95 módulos de 2 px = 190 px; zonas de silêncio de 11 módulos à
// esquerda e 7 à direita (226 px no total, de x = 4 a x = 229).
constexpr int16_t EAN_MODULE_PX = 2;
constexpr int16_t EAN_QUIET_LEFT_MODULES = 11;
constexpr int16_t BARCODE_X = MARGIN + EAN_QUIET_LEFT_MODULES * EAN_MODULE_PX;
constexpr int16_t BARCODE_TOP = 92;
constexpr int16_t BARCODE_HEIGHT = DISPLAY_HEIGHT - BARCODE_TOP - 2;

// Tela sem produto.
constexpr char UNCONFIGURED_TITLE[] = "Etiqueta sem produto";
constexpr char UNCONFIGURED_HINT[] = "Cadastre na aplicação o ID:";
constexpr int16_t UNCONFIGURED_TITLE_BASELINE = 32;
constexpr int16_t UNCONFIGURED_HINT_BASELINE = 60;
constexpr int16_t UNCONFIGURED_ID_BASELINE = 100;

// Reticências em ASCII: as fontes "_tf" não têm o caractere U+2026.
constexpr char ELLIPSIS[] = "...";
constexpr size_t ELLIPSIS_LEN = sizeof(ELLIPSIS) - 1;

// Maior texto que passa por fit_text(): a descrição, mais as reticências.
constexpr size_t FIT_BUFFER_SIZE = SPT_DESCRIPTION_SIZE + ELLIPSIS_LEN;

// "1490" -> "14,90". O contrato limita o preço a 1..99999 centavos.
void format_price(int32_t cents, char* out, size_t size) {
    if (cents < 0) {
        cents = 0;
    }
    snprintf(out, size, "%ld,%02ld", static_cast<long>(cents / 100),
             static_cast<long>(cents % 100));
}

// A U8g2 volta ao modo não transparente a cada troca de fonte (u8g2_SetFont),
// e nesse modo pintaria a caixa inteira de cada glifo: reaplica o modo sempre.
void use_font(U8G2_FOR_ADAFRUIT_GFX& u8g2, const uint8_t* font) {
    u8g2.setFont(font);
    u8g2.setFontMode(1);
}

// Recua `len` até o início do último caractere UTF-8 de `text`.
size_t utf8_drop_last(const char* text, size_t len) {
    while (len > 0) {
        len--;
        if ((static_cast<uint8_t>(text[len]) & 0xC0) != 0x80) {
            break;  // achou o primeiro byte do caractere
        }
    }
    return len;
}

// Escolhe a maior fonte de `fonts` em que `text` cabe em `max_width` e copia o
// texto para `out` (FIT_BUFFER_SIZE bytes). Se nem a menor fonte couber, corta
// o texto sem partir caracteres UTF-8 e termina com "...". Deixa a fonte
// escolhida ativa em `u8g2`.
void fit_text(U8G2_FOR_ADAFRUIT_GFX& u8g2, const uint8_t* const* fonts, size_t count,
              const char* text, int16_t max_width, char* out) {
    snprintf(out, FIT_BUFFER_SIZE, "%s", text);
    for (size_t i = 0; i < count; i++) {
        use_font(u8g2, fonts[i]);
        if (u8g2.getUTF8Width(out) <= max_width) {
            return;
        }
    }

    // Continua com a menor fonte, já ativa.
    size_t len = strlen(out);
    while (len > 0) {
        len = utf8_drop_last(out, len);
        memcpy(out + len, ELLIPSIS, ELLIPSIS_LEN + 1);
        if (u8g2.getUTF8Width(out) <= max_width) {
            break;
        }
    }
    SPT_LOGW(TAG, "texto não coube em %d px e foi cortado: \"%s\"", max_width, out);
}

void draw_fitted(U8G2_FOR_ADAFRUIT_GFX& u8g2, const uint8_t* const* fonts, size_t count,
                 const char* text, int16_t baseline) {
    if (text[0] == '\0') {
        return;
    }
    char fitted[FIT_BUFFER_SIZE];
    fit_text(u8g2, fonts, count, text, TEXT_WIDTH, fitted);
    u8g2.setForegroundColor(DISPLAY_BLACK);
    u8g2.drawUTF8(MARGIN, baseline, fitted);
}

void draw_centered(U8G2_FOR_ADAFRUIT_GFX& u8g2, const uint8_t* font, const char* text,
                   int16_t baseline) {
    use_font(u8g2, font);
    u8g2.setForegroundColor(DISPLAY_BLACK);
    const int16_t width = u8g2.getUTF8Width(text);
    u8g2.drawUTF8((DISPLAY_WIDTH - width) / 2, baseline, text);
}

// Desenha "R$" e o preço a partir da margem esquerda. Retorna o x logo após o último dígito.
int16_t draw_price(U8G2_FOR_ADAFRUIT_GFX& u8g2, int32_t cents, uint16_t color) {
    char price[16];
    format_price(cents, price, sizeof(price));

    u8g2.setForegroundColor(color);
    use_font(u8g2, CURRENCY_FONT);
    int16_t x = MARGIN;
    x += u8g2.drawUTF8(x, PRICE_TOP + u8g2.getFontAscent(), "R$") + CURRENCY_GAP;
    use_font(u8g2, PRICE_FONT);
    x += u8g2.drawUTF8(x, PRICE_BASELINE, price);
    return x;
}

// Coluna da promoção: preço anterior riscado e destaque "OFERTA", alinhados à direita.
void draw_promotion_column(Adafruit_GFX& gfx, U8G2_FOR_ADAFRUIT_GFX& u8g2,
                           int32_t old_price_cents, int16_t price_end) {
    char old_price[24];
    char digits[16];
    format_price(old_price_cents, digits, sizeof(digits));
    snprintf(old_price, sizeof(old_price), "R$ %s", digits);

    const int16_t right = DISPLAY_WIDTH - MARGIN;

    use_font(u8g2, OFFER_FONT);
    const int16_t offer_width = u8g2.getUTF8Width(OFFER_TEXT) + 2 * OFFER_PADDING;
    use_font(u8g2, OLD_PRICE_FONT);
    const int16_t old_width = u8g2.getUTF8Width(old_price);
    const int16_t column_width = old_width > offer_width ? old_width : offer_width;
    if (right - column_width < price_end + MARGIN) {
        SPT_LOGW(TAG, "coluna da promoção encosta no preço (%d px livres, %d px necessários)",
                 right - price_end - MARGIN, column_width);
    }

    // Preço anterior, em preto, riscado na metade da altura dos dígitos.
    const int16_t old_x = right - old_width;
    u8g2.setForegroundColor(DISPLAY_BLACK);
    u8g2.drawUTF8(old_x, OLD_PRICE_BASELINE, old_price);
    gfx.fillRect(old_x - 1,
                 OLD_PRICE_BASELINE - u8g2.getFontAscent() / 2 - STRIKE_THICKNESS / 2,
                 old_width + 2, STRIKE_THICKNESS, DISPLAY_BLACK);

    // Destaque "OFERTA": texto branco sobre vermelho.
    const int16_t offer_x = right - offer_width;
    gfx.fillRect(offer_x, OFFER_TOP, offer_width, OFFER_HEIGHT, DISPLAY_RED);
    use_font(u8g2, OFFER_FONT);
    u8g2.setForegroundColor(DISPLAY_WHITE);
    u8g2.drawUTF8(offer_x + OFFER_PADDING,
                  OFFER_TOP + (OFFER_HEIGHT + u8g2.getFontAscent()) / 2, OFFER_TEXT);
}

// Código de barras em preto, com faixas contíguas desenhadas como um só retângulo.
void draw_ean13(Adafruit_GFX& gfx, const char* digits) {
    uint8_t modules[RENDER_EAN13_MODULES];
    if (!render_ean13_modules(digits, modules)) {
        SPT_LOGW(TAG, "EAN-13 inválido (\"%s\"): código de barras omitido", digits);
        return;
    }
    size_t i = 0;
    while (i < RENDER_EAN13_MODULES) {
        if (modules[i] == 0) {
            i++;
            continue;
        }
        const size_t start = i;
        while (i < RENDER_EAN13_MODULES && modules[i] != 0) {
            i++;
        }
        gfx.fillRect(static_cast<int16_t>(BARCODE_X + start * EAN_MODULE_PX), BARCODE_TOP,
                     static_cast<int16_t>((i - start) * EAN_MODULE_PX), BARCODE_HEIGHT,
                     DISPLAY_BLACK);
    }
}

void begin_text(U8G2_FOR_ADAFRUIT_GFX& u8g2, Adafruit_GFX& gfx) {
    u8g2.begin(gfx);
    u8g2.setFontDirection(0);
    u8g2.setBackgroundColor(DISPLAY_WHITE);  // não inicializada pela biblioteca
}

}  // namespace

void render_draw_product(Adafruit_GFX& gfx, const Product& product, const Promotion* promotion) {
    U8G2_FOR_ADAFRUIT_GFX u8g2;
    begin_text(u8g2, gfx);

    draw_fitted(u8g2, NAME_FONTS, sizeof(NAME_FONTS) / sizeof(NAME_FONTS[0]), product.name,
                NAME_BASELINE);
    draw_fitted(u8g2, DESCRIPTION_FONTS, sizeof(DESCRIPTION_FONTS) / sizeof(DESCRIPTION_FONTS[0]),
                product.description, DESCRIPTION_BASELINE);

    if (promotion != nullptr) {
        // Só o preço promocional e o destaque de oferta ficam em vermelho (RF10).
        const int16_t price_end = draw_price(u8g2, promotion->price_cents, DISPLAY_RED);
        draw_promotion_column(gfx, u8g2, product.price_cents, price_end);
    } else {
        draw_price(u8g2, product.price_cents, DISPLAY_BLACK);
    }

    draw_ean13(gfx, product.ean13);
}

void render_draw_unconfigured(Adafruit_GFX& gfx, const char* tag_id) {
    U8G2_FOR_ADAFRUIT_GFX u8g2;
    begin_text(u8g2, gfx);

    // Moldura: distingue a tela de um visor em branco ou sem imagem.
    gfx.drawRect(0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_BLACK);
    gfx.drawRect(1, 1, DISPLAY_WIDTH - 2, DISPLAY_HEIGHT - 2, DISPLAY_BLACK);

    draw_centered(u8g2, u8g2_font_helvB14_tf, UNCONFIGURED_TITLE, UNCONFIGURED_TITLE_BASELINE);
    draw_centered(u8g2, u8g2_font_helvR10_tf, UNCONFIGURED_HINT, UNCONFIGURED_HINT_BASELINE);
    draw_centered(u8g2, u8g2_font_helvB24_tf,
                  (tag_id != nullptr && tag_id[0] != '\0') ? tag_id : "(indisponível)",
                  UNCONFIGURED_ID_BASELINE);
}
