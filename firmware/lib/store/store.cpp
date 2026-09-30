#include "store.h"

#include <string.h>

bool store_load(StoredState* out) {
    // TODO(F5): ler da NVS com Preferences (namespace "spt")
    memset(out, 0, sizeof(*out));
    return false;
}

bool store_save(const StoredState& state) {
    // TODO(F5): gravar na NVS com Preferences, só os campos que mudaram
    (void)state;
    return false;
}
