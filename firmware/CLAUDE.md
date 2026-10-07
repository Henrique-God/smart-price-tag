# Instruções para o Claude Code (firmware)

As regras do firmware ficam no AGENTS.md (compartilhado com outros agentes) e o
contrato com a aplicação no CONTRATO.md da raiz. Os dois entram no contexto por import:

@AGENTS.md
@../CONTRATO.md

## Ambiente local (Windows)

- Shell: PowerShell. Rode os comandos a partir desta pasta (`firmware`).
- Se `pio` não estiver no PATH, use `& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe"`.
- Placa: ESP32 DevKit V1 com micro-USB e ponte CH9102, normalmente em `COM5`
  (confira em `pio device list`).
  - Gravar: `pio run -e <ambiente> -t upload --upload-port COM5`
  - Monitor: `pio device monitor -e <ambiente> --port COM5`
  - O monitor serial prende a porta: feche-o antes de gravar.
- Depois de qualquer mudança, compile pelo menos `pio run -e demo` e `pio run -e prod`
  antes de dizer que terminou.

## Como trabalhar comigo

- Não faça commit nem push sem eu pedir. Mensagens de commit em português, no estilo
  `firmware: <o que mudou>`.
- Nunca leia, crie ou exiba `include/secrets.h` com valores reais; use `secrets.example.h`.
- Quando um teste depender do hardware (visor, botão, sono, bateria), diga exatamente
  o que devo observar no visor ou no log e espere eu relatar o resultado.
