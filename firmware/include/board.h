// Mapa de pinos da etiqueta (ESP32 DevKit V1, ESP32-WROOM-32).
//
// Único lugar do firmware onde números de GPIO aparecem. Usado pelos módulos
// de hardware: `display` (visor) e `power` (botão e bateria).
#pragma once

#include <stdint.h>

// Visor e-paper WeAct 2,9" (SPI de hardware, VSPI)
constexpr uint8_t PIN_EPD_BUSY = 4;   // entrada
constexpr uint8_t PIN_EPD_RST = 16;
constexpr uint8_t PIN_EPD_DC = 17;
constexpr uint8_t PIN_EPD_CS = 5;     // pino de strapping: precisa estar alto no boot (CS ocioso é alto)
constexpr uint8_t PIN_EPD_CLK = 18;   // VSPI SCK
constexpr uint8_t PIN_EPD_DIN = 23;   // VSPI MOSI

// Botão: domínio RTC (RTC_GPIO8), ativo em nível baixo; desperta o chip por ext0
constexpr uint8_t PIN_BUTTON = 33;

// Bateria: ADC1_CH6, somente entrada, atrás de um divisor resistivo por 2
constexpr uint8_t PIN_BATTERY = 34;
constexpr uint8_t BATTERY_DIVIDER = 2;
