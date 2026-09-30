// Log pela serial com nível e prefixo do módulo (camada base).
//
// Formato de saída:  I (  1234) [net] mensagem
//                    ^   ^       ^
//                    |   |       módulo (TAG)
//                    |   milissegundos desde o boot
//                    nível: E, W, I ou D
//
// Uso em cada .cpp:
//   constexpr char TAG[] = "net";
//   SPT_LOGI(TAG, "conectado em %u ms", elapsed);
//
// O nível máximo é definido em tempo de compilação por SPT_LOG_LEVEL
// (platformio.ini); chamadas acima dele não geram código.
#pragma once

#define SPT_LOG_LEVEL_NONE 0
#define SPT_LOG_LEVEL_ERROR 1
#define SPT_LOG_LEVEL_WARN 2
#define SPT_LOG_LEVEL_INFO 3
#define SPT_LOG_LEVEL_DEBUG 4

#ifndef SPT_LOG_LEVEL
#define SPT_LOG_LEVEL SPT_LOG_LEVEL_INFO
#endif

// Escreve uma linha de log. Prefira as macros SPT_LOGx abaixo.
void spt_log_write(char level, const char* tag, const char* fmt, ...)
    __attribute__((format(printf, 3, 4)));

#if SPT_LOG_LEVEL >= SPT_LOG_LEVEL_ERROR
#define SPT_LOGE(tag, fmt, ...) spt_log_write('E', tag, fmt, ##__VA_ARGS__)
#else
#define SPT_LOGE(tag, fmt, ...) ((void)0)
#endif

#if SPT_LOG_LEVEL >= SPT_LOG_LEVEL_WARN
#define SPT_LOGW(tag, fmt, ...) spt_log_write('W', tag, fmt, ##__VA_ARGS__)
#else
#define SPT_LOGW(tag, fmt, ...) ((void)0)
#endif

#if SPT_LOG_LEVEL >= SPT_LOG_LEVEL_INFO
#define SPT_LOGI(tag, fmt, ...) spt_log_write('I', tag, fmt, ##__VA_ARGS__)
#else
#define SPT_LOGI(tag, fmt, ...) ((void)0)
#endif

#if SPT_LOG_LEVEL >= SPT_LOG_LEVEL_DEBUG
#define SPT_LOGD(tag, fmt, ...) spt_log_write('D', tag, fmt, ##__VA_ARGS__)
#else
#define SPT_LOGD(tag, fmt, ...) ((void)0)
#endif
