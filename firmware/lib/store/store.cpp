#include "store.h"

#include <string.h>

#include <Preferences.h>

#include "spt_log.h"

namespace {
constexpr char TAG[] = "store";
constexpr char NAMESPACE[] = "spt";

// Chaves da NVS (no máximo 15 caracteres).
constexpr char KEY_SEQ[] = "seq";
constexpr char KEY_CONFIG[] = "cfg";
constexpr char KEY_VERSION[] = "ver";
constexpr char KEY_SCREEN[] = "screen";
constexpr char KEY_PROMO_EXPIRES[] = "promo_exp";

Preferences prefs;

// Para comparar com o que já está gravado sem usar a pilha.
uint8_t scratch[SPT_CONFIG_DATA_SIZE];

// Lê um blob de até `size - 1` bytes em `out`, terminado em '\0'. Retorna o
// tamanho lido; 0 se a chave não existe ou não cabe.
size_t read_blob(const char* key, char* out, size_t size) {
    out[0] = '\0';
    const size_t len = prefs.getBytesLength(key);
    if (len == 0 || len >= size || prefs.getBytes(key, out, len) != len) {
        return 0;
    }
    out[len] = '\0';
    return len;
}

// Grava `len` bytes em `key` só se diferirem do conteúdo atual.
// Vazio remove a chave (a NVS não distingue blob vazio de falha na escrita).
bool write_blob_if_changed(const char* key, const void* data, size_t len) {
    const size_t old_len = prefs.getBytesLength(key);
    if (len == 0) {
        return old_len == 0 || prefs.remove(key);
    }
    if (old_len == len && prefs.getBytes(key, scratch, sizeof(scratch)) == len &&
        memcmp(scratch, data, len) == 0) {
        return true;
    }
    SPT_LOGD(TAG, "gravando %s (%u bytes)", key, static_cast<unsigned>(len));
    return prefs.putBytes(key, data, len) == len;
}
}  // namespace

bool store_load(StoredState* out) {
    memset(out, 0, sizeof(*out));
    // Leitura e escrita: abrir só para leitura falha (com erro no log) se o namespace não existe
    if (!prefs.begin(NAMESPACE, false)) {
        SPT_LOGE(TAG, "falha ao abrir a NVS");
        return false;
    }
    const bool found = prefs.getBytesLength(KEY_CONFIG) > 0 || prefs.getUInt(KEY_SEQ, 0) != 0;
    out->last_seq = prefs.getUInt(KEY_SEQ, 0);
    out->config_len = read_blob(KEY_CONFIG, out->config_data, sizeof(out->config_data));
    read_blob(KEY_VERSION, out->applied_version, sizeof(out->applied_version));
    const uint8_t screen = prefs.getUChar(KEY_SCREEN, 0);
    out->screen = screen <= static_cast<uint8_t>(DisplayedScreen::Promotion)
                      ? static_cast<DisplayedScreen>(screen)
                      : DisplayedScreen::None;
    out->promotion_expires_at = prefs.getLong64(KEY_PROMO_EXPIRES, 0);
    prefs.end();

    SPT_LOGI(TAG, "estado salvo: seq=%lu, config=%u bytes, versão \"%s\", tela %u",
             static_cast<unsigned long>(out->last_seq), static_cast<unsigned>(out->config_len),
             out->applied_version, static_cast<unsigned>(out->screen));
    return found;
}

bool store_save(const StoredState& state) {
    if (!prefs.begin(NAMESPACE, false)) {
        SPT_LOGE(TAG, "falha ao abrir a NVS");
        return false;
    }
    bool ok = true;
    if (prefs.getUInt(KEY_SEQ, 0) != state.last_seq) {
        ok = prefs.putUInt(KEY_SEQ, state.last_seq) != 0 && ok;
    }
    ok = write_blob_if_changed(KEY_CONFIG, state.config_data, state.config_len) && ok;
    ok = write_blob_if_changed(KEY_VERSION, state.applied_version,
                               strnlen(state.applied_version, sizeof(state.applied_version))) &&
         ok;
    const uint8_t screen = static_cast<uint8_t>(state.screen);
    if (prefs.getUChar(KEY_SCREEN, 0) != screen) {
        ok = prefs.putUChar(KEY_SCREEN, screen) != 0 && ok;
    }
    if (prefs.getLong64(KEY_PROMO_EXPIRES, 0) != state.promotion_expires_at) {
        ok = prefs.putLong64(KEY_PROMO_EXPIRES, state.promotion_expires_at) != 0 && ok;
    }
    prefs.end();
    if (!ok) {
        SPT_LOGE(TAG, "falha ao gravar o estado na NVS");
    }
    return ok;
}
