#include "spt_log.h"

#include <stdarg.h>
#include <stdio.h>

#ifdef ARDUINO
#include <Arduino.h>
#else
#include <chrono>
#endif

namespace {

// Linha maior que isso é truncada; suficiente para os logs do firmware.
constexpr size_t LINE_SIZE = 192;

unsigned long uptime_ms() {
#ifdef ARDUINO
    return millis();
#else
    // Ambiente nativo (testes): relógio do host
    using namespace std::chrono;
    static const auto start = steady_clock::now();
    return static_cast<unsigned long>(
        duration_cast<milliseconds>(steady_clock::now() - start).count());
#endif
}

}  // namespace

void spt_log_write(char level, const char* tag, const char* fmt, ...) {
    char line[LINE_SIZE];
    va_list args;
    va_start(args, fmt);
    vsnprintf(line, sizeof(line), fmt, args);
    va_end(args);

#ifdef ARDUINO
    // \r\n: terminais seriais "crus" (ex.: Wokwi) não voltam ao início da linha só com \n
    Serial.printf("%c (%6lu) [%s] %s\r\n", level, uptime_ms(), tag, line);
#else
    printf("%c (%6lu) [%s] %s\n", level, uptime_ms(), tag, line);
#endif
}
