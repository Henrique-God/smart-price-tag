// power: energia e sistema do chip (camada de hardware).
//
// Responsável por: causa do despertar, identidade da etiqueta (derivada do MAC),
// leitura da bateria, prazo máximo do ciclo e entrada em deep sleep.
// Não conhece rede, MQTT nem o visor.
#pragma once

#include <stdint.h>

// Por que o chip começou a executar setup() neste ciclo.
enum class WakeCause : uint8_t {
    Reset,    // energização ou reset (EN), não é despertar do deep sleep
    Timer,    // fim do intervalo de verificação
    Button,   // botão (ext0 em PIN_BUTTON)
    Other,    // qualquer outra fonte de despertar
};

// Prazo máximo de um ciclo acordado, medido desde o boot.
constexpr uint32_t POWER_CYCLE_DEADLINE_MS = 60000;

// Causa do despertar atual.
WakeCause power_wake_cause();

// Nome curto da causa, para log ("reset", "timer", "button", "other").
const char* power_wake_cause_name(WakeCause cause);

// Identificador da etiqueta: 12 caracteres hex minúsculos do MAC station
// (ex.: "a4cf12ab34cd"). Usado nos tópicos spt/{id}/... e como usuário MQTT.
// Retorna ponteiro para buffer estático, válido durante todo o ciclo.
// Se o MAC não puder ser lido ou for inválido (todo zero), retorna "" e
// registra erro: a etiqueta não deve se conectar ao broker sem um ID válido.
const char* power_tag_id();

// Tensão da bateria em mV, já compensando o divisor. 0 se a leitura falhar.
uint16_t power_battery_mv();

// Tempo restante até o prazo do ciclo, em ms. 0 significa "dormir já".
uint32_t power_deadline_remaining_ms();

// Entra em deep sleep por `seconds` segundos. Não retorna: o próximo
// despertar reinicia o chip a partir de setup().
[[noreturn]] void power_deep_sleep(uint32_t seconds);
