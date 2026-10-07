# Smart Price Tag · firmware

Firmware da etiqueta eletrônica de preço (PCS3858, Poli-USP). Roda em um ESP32 DevKit V1 com visor e-paper WeAct 2,9" de três cores.

A etiqueta passa quase todo o tempo em deep sleep. Ela desperta uma vez por dia, ou quando o botão é pressionado. A cada despertar, busca a configuração no broker MQTT, redesenha o visor se necessário, publica seu estado e volta a dormir.

> **Estado atual (S5):** ambiente, esqueleto, driver do visor (`display`) e programa de bancada prontos. O firmware imprime a versão, a causa do despertar e o ID da etiqueta, e depois dorme. Os demais módulos têm stubs marcados com `TODO(F2)` a `TODO(F5)`.
>
> Antes de implementar, leia [`AGENTS.md`](AGENTS.md) (regras, tarefas F1–F6 e critérios de aceitação) e o [`CONTRATO.md`](../CONTRATO.md) (mensagens trocadas com a aplicação).

## 1. Instalar o PlatformIO

Escolha **uma** das opções:

- **VS Code (recomendado):** instale a extensão *PlatformIO IDE*. Ao abrir a pasta `firmware/`, o VS Code sugere a extensão automaticamente. Os comandos `pio` abaixo funcionam no terminal *PlatformIO Core CLI* da extensão.
- **Só linha de comando:**

  ```bash
  pip install -U platformio
  ```

  No macOS também dá para usar `brew install platformio`.

O primeiro build baixa o toolchain do ESP32 e as bibliotecas (~1 GB em `~/.platformio`). Isso acontece uma vez só.

**Driver USB-serial:** se a placa não aparecer como porta serial, instale o driver do conversor dela. O DevKit V1 usa CP210x (Silicon Labs) ou CH340 (WCH), e o nome está gravado no chip ao lado do conector USB.

## 2. Configurar os segredos

As credenciais ficam em `include/secrets.h`, que **não é versionado** (está no `.gitignore`). Crie o arquivo a partir do modelo:

```bash
cp include/secrets.example.h include/secrets.h
```

Depois, edite `include/secrets.h`:

| Macro | Conteúdo |
|---|---|
| `WIFI_SSID`, `WIFI_PASSWORD` | rede Wi-Fi da loja |
| `MQTT_HOST`, `MQTT_PORT` | endereço e porta do broker |
| `MQTT_PASSWORD` | senha desta etiqueta no broker (o usuário é o ID da etiqueta) |
| `TAG_HMAC_KEY_HEX` | chave HMAC desta etiqueta, 64 caracteres hex (32 bytes), igual à cadastrada na aplicação |

Sem esse arquivo, o build falha com a mensagem `include/secrets.h nao encontrado`. **Nunca** coloque valores reais em `secrets.example.h`.

## 3. Compilar

Todos os comandos rodam dentro de `firmware/`.

```bash
pio run -e prod
```

```bash
pio run -e demo
```

| Ambiente | Despertar periódico | Log |
|---|---|---|
| `prod` | a cada 24 h (`CHECK_INTERVAL_S=86400`) | info |
| `demo` | a cada 3 min (`CHECK_INTERVAL_S=180`) | debug |

`demo` é o ambiente padrão quando `-e` é omitido. A versão do firmware (`FW_VERSION`) fica em `build_flags` no `platformio.ini`.

### Build estrito (warnings do projeto)

O `platformio.ini` só liga `-Wall -Wextra` em `src/`, para não misturar os warnings do núcleo Arduino e das bibliotecas com os nossos. Antes de abrir um PR, compile com os warnings ligados em tudo e filtre os caminhos do projeto:

```bash
pio run -t clean -e demo && PLATFORMIO_BUILD_FLAGS="-Wall -Wextra" pio run -e demo 2>&1 | grep -E "^(src|lib|include)/.*warning"
```

A saída deve ser vazia.

## 4. Gravar a placa

Conecte o DevKit por USB e rode:

```bash
pio run -e demo -t upload
```

- Se houver mais de uma porta serial, indique a certa com `--upload-port`. No macOS, é algo como `/dev/cu.usbserial-0001` (liste com `pio device list`).
- Se o upload ficar em `Connecting...`, segure o botão **BOOT** da placa até a gravação começar.

## 5. Monitor serial

```bash
pio device monitor -e demo
```

A velocidade (115200) e o decodificador de exceções vêm do `platformio.ini`. Para sair, use `Ctrl+C`.

### Conferir o ambiente em uma placa sem nada ligado

1. Grave o ambiente `demo` e abra o monitor.
2. Aperte **EN** (reset). A saída deve ser parecida com:

   ```
   I (    12) [main] firmware 1.0.0
   I (    12) [main] despertar: reset
   I (    13) [main] etiqueta: a4cf12ab34cd
   I (    13) [main] dormindo por 180 s
   ```

3. Cerca de 3 minutos depois, a placa reinicia sozinha e imprime `despertar: timer`.
4. O ID é o MAC station sem `:` e em minúsculas. Ele deve bater com o `MAC:` que o `esptool` mostra durante o upload.

## 6. Teste de bancada (sem rede)

O ambiente `bancada` grava um programa de teste de hardware, que não é o firmware: confere a ligação SPI e a linha BUSY do visor, as três cores, a orientação, a escala em mm, o tempo de redesenho, o botão e o despertar do deep sleep. Não precisa de `include/secrets.h` nem de bateria (a placa fica no USB).

```bash
pio run -e bancada -t upload
```

```bash
pio device monitor -e bancada
```

No monitor: `r` redesenha, `s` adormece a placa (o botão acorda), `?` mostra os comandos. As ligações e o roteiro completo, com a tabela de sintomas, estão na seção 6 do [`AGENTS.md`](AGENTS.md).

Para o módulo `render` (F2): `e` roda o autoteste do EAN-13 (também roda no boot e não precisa do visor); `1` a `5` desenham as telas reais da etiqueta pelo mesmo caminho do firmware: `1` promoção (vetor V1), `2` padrão com acentos (V2), `3` sem produto com o ID da placa (V3), `4` pior caso com letras largas, `5` pior caso com acentos.

### Teste do EAN-13 no PC

`render_ean13_modules` fica em `lib/render/render_ean13.cpp`, sem dependência de Arduino, e é testado no PC contra as referências do F2. Precisa de um `g++` com suporte a C++11 no PATH (no Windows, MinGW ou MSYS2). A partir de `firmware/`:

```bash
g++ -std=gnu++11 -Wall -Wextra -I lib/render -I lib/types test/host/test_ean13.cpp lib/render/render_ean13.cpp -o .pio/test_ean13
```

```bash
.pio/test_ean13
```

A última linha deve ser `PASSOU: 0 falha(s)`.

## Organização do código

```
include/   board.h (pinos), secrets.example.h, spt_secrets.h
src/       main.cpp: orquestra o ciclo (roda uma vez em setup())
src/bancada/  programa de teste de hardware (só no ambiente `bancada`)
test/host/    testes que rodam no PC, sem placa (g++)
lib/       um módulo por pasta, cada um com <modulo>.h (interface) e <modulo>.cpp
```

| Camada | Módulo | Responsabilidade |
|---|---|---|
| Orquestração | `main` | ciclo completo; único ponto que passa dados entre serviços |
| Serviços | `net` | Wi-Fi e relógio por SNTP |
| | `mqtt` | broker, recebe `spt/{id}/config`, publica `spt/{id}/status` |
| | `auth` | HMAC da configuração e número de sequência |
| | `config` | interpretação da configuração já autenticada |
| | `render` | layouts padrão e de promoção, EAN-13 |
| Hardware e persistência | `power` | causa do despertar, ID da etiqueta, bateria, prazo, deep sleep |
| | `store` | NVS |
| | `display` | driver do e-paper (GxEPD2) |
| Base | `types` | structs do contrato de mensagens (`spt_types.h`) |
| | `log` | `SPT_LOGE/W/I/D(TAG, ...)` pela serial |

Regras de fronteira:

- Só `render` e `display` conhecem o e-paper. Apenas `render` inclui `display.h`.
- Só `mqtt` conhece MQTT (PubSubClient fica escondido no `.cpp`).
- Só `auth` vê a chave HMAC: ela só é definida quando `SPT_SECRETS_WITH_HMAC_KEY` vem antes do include.
- `config` recebe apenas conteúdo já aceito por `auth`.
- Serviços podem usar as camadas de baixo, mas não se incluem entre si.
- Identificadores em inglês, comentários em português.

### Tarefas pendentes

Cada stub tem um `TODO(Fn)` com a tarefa que vai implementá-lo. Para listar todos:

```bash
grep -rn "TODO(F" src lib include
```

## Versões fixadas

| Pacote | Versão |
|---|---|
| plataforma `espressif32` | 7.1.3 (Arduino-ESP32 2.0.17, ESP-IDF 4.4) |
| GxEPD2 | 1.6.9 |
| Adafruit GFX Library | 1.12.6 |
| Adafruit BusIO | 1.17.4 (dependência do GFX) |
| PubSubClient | 2.8 |
| ArduinoJson | 7.4.3 |

O núcleo Arduino é a série **2.x**. Exemplos escritos para a 3.x podem não compilar (a 3.x mudou, por exemplo, as APIs de LEDC e de timers).
