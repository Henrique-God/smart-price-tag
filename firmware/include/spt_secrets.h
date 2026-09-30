// Ponto único de acesso aos segredos. Falha o build com instrução clara se
// include/secrets.h não existir.
//
// Incluído apenas por net.cpp, mqtt.cpp e auth.cpp. A chave HMAC só é definida
// quando SPT_SECRETS_WITH_HMAC_KEY está definido antes do include (apenas auth.cpp).
#pragma once

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "include/secrets.h nao encontrado: copie include/secrets.example.h para include/secrets.h e preencha (ver firmware/README.md)"
#endif
