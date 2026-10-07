# AGENTS.md: firmware do Smart Price Tag

Instruções para agentes de IA (e pessoas) que trabalham em `firmware/`. Leia este arquivo inteiro antes de alterar código.

## 1. Leitura obrigatória

| Arquivo | Para quê |
|---|---|
| `../CONTRATO.md` | formato exato das mensagens MQTT, HMAC, sequência e vetores de teste. É a fonte de verdade da integração com a aplicação |
| `README.md` | instalação, build, gravação, organização dos módulos e regras de fronteira |
| `include/board.h` | mapa de pinos (único lugar com números de GPIO) |
| `lib/types/spt_types.h` | structs do contrato já usadas pelos módulos |

O que a etiqueta faz: dorme em deep sleep, desperta uma vez por dia (ou pelo botão), busca a configuração retida no broker, verifica a autenticidade, redesenha o visor e-paper se o conteúdo mudou ou se a promoção venceu, publica seu estado e volta a dormir.

## 2. Regras que não se negociam

1. **Não altere `../CONTRATO.md`.** Se a implementação exigir mudança no contrato, pare e descreva a proposta: ela precisa do aceite da dupla da aplicação.
2. **O ciclo inteiro roda uma vez em `setup()`** e termina em `power_deep_sleep()`. `loop()` nunca é alcançado no firmware (só o programa de bancada usa `loop()`).
3. **Todo caminho termina em deep sleep**, inclusive falha de rede, de broker, de visor e mensagem inválida. Nenhuma espera sem prazo: use `power_deadline_remaining_ms()` (prazo total de 60 s, RNF08).
4. **Fronteiras dos módulos** (ver README): só `render` e `display` conhecem o e-paper; só `mqtt` conhece MQTT; só `auth` vê a chave HMAC; `config` só recebe texto já aceito por `auth`; serviços não se incluem entre si; o `main` é quem passa dados entre eles.
5. **Segredos nunca entram no Git.** `include/secrets.h` está no `.gitignore`. Não escreva chaves, senhas ou SSIDs reais em nenhum outro arquivo, nem em exemplos e comentários.
6. **Versões fixadas.** Não troque versões de plataforma ou biblioteca sem pedir. Ao adicionar uma biblioteca, fixe a versão exata em `lib_deps`.
7. **Núcleo Arduino-ESP32 2.0.17 (série 2.x), C++ `gnu++11`.** Não use exemplos da série 3.x nem recursos de C++14/17.
8. **Memória fixa no ciclo.** Use buffers de tamanho fixo (como em `spt_types.h`); evite `String` e alocação dinâmica.
9. **Estilo:** identificadores em inglês, comentários e mensagens de log em português, log só pelas macros `SPT_LOGx`. Cada stub tem um `TODO(Fn)`; ao implementar, remova o `TODO` correspondente.
10. **Antes de entregar:** `pio run -e demo`, `pio run -e prod` e `pio run -e bancada` compilam sem erros, e o build estrito do README não mostra warnings em `src/`, `lib/` ou `include/`.

## 3. Ambientes e comandos

Todos os comandos rodam dentro de `firmware/`.

| Ambiente | O que é | Precisa de `secrets.h`? |
|---|---|---|
| `demo` | firmware, desperta a cada 3 min, log debug | sim |
| `prod` | firmware, desperta a cada 24 h, log info | sim |
| `bancada` | teste de hardware (visor, botão, deep sleep), sem rede | não |

```bash
pio run -e bancada -t upload        # gravar
pio device monitor -e bancada       # monitor serial (Ctrl+C sai)
pio run -e demo -t upload && pio device monitor -e demo
```

No Windows, a porta aparece como `COMx` (liste com `pio device list`). Se o upload travar em `Connecting...`, segure **BOOT** até começar. Se a placa não aparecer, instale o driver CP210x da Silicon Labs.

## 4. Estado atual

| Item | Situação |
|---|---|
| Ambiente PlatformIO, esqueleto dos módulos, `main` mínimo | pronto (S4) |
| `display` (driver do e-paper) | **pronto**: `display_begin`, `display_draw_full`, `display_last_refresh_ms`, `display_hibernate` |
| Programa de bancada (`src/bancada/bancada.cpp`) | **pronto**, com o autoteste do EAN-13 (`e`) e as telas do `render` (`1` a `5`) |
| `render` | **implementado**: EAN-13 conferido no PC (`test/host/test_ean13.cpp`); falta conferir os layouts no visor (critérios do F2) |
| `net`, `mqtt`, `auth`, `config`, `store`, `power` (bateria, prazo, botão), ciclo no `main` | stubs com `TODO(F3)` a `TODO(F5)` |

```bash
grep -rn "TODO(F" src lib include
```

## 5. Tarefas, entregas e critérios de aceitação

Cada tarefa só está concluída quando todos os critérios passarem na placa. Registre a evidência (trecho do log serial ou foto do visor) no PR.

### F1: bring-up do hardware (S4–S5)

Entrega: circuito montado na protoboard e o roteiro de bancada da seção 6 executado com sucesso.

- [ ] `visor (SPI + BUSY): OK` no log da bancada.
- [ ] Tela A legível, com "SUP. ESQ." no canto superior esquerdo, bloco vermelho vermelho e bloco preto preto.
- [ ] Barra de "10 mm" medida com régua entre 9,5 e 10,5 mm; barra de "40 mm" entre 39 e 41 mm. Se a escala divergir, corrija `DISPLAY_PX_PER_MM` em `display.h`.
- [ ] Duração do redesenho registrada (linha `RNF02 ...`). Avise a equipe: a documentação cita 19 s, mas a biblioteca indica ~26–27 s para este painel.
- [ ] Botão: o toque aparece no log; o comando `s` adormece a placa, e o botão a acorda com `acordou do deep sleep por BOTAO (ext0 OK)`; a imagem continua no visor durante o sono.

### F2: renderização (S5–S6)

Entrega: `render_product`, `render_unconfigured` e `render_ean13_modules` implementados.

Restrições já calculadas para o painel (4,41 px/mm, 296 × 128 px):

| Elemento | Restrição | Origem |
|---|---|---|
| Dígitos do preço | altura ≥ 45 px (10 mm). `u8g2_font_logisoso46_tn` tem dígitos de 46 px e inclui a vírgula, mas **não** tem "R" nem "$" | RNF06 |
| Fonte padrão do Adafruit GFX | `FreeSansBold24pt7b` tem dígitos de só 35 px (7,9 mm): **não atende** | RNF06 |
| Acentos | as fontes do Adafruit GFX são só ASCII. Use **U8g2_for_Adafruit_GFX** (adicione `olikraus/U8g2_for_Adafruit_GFX @ 1.8.0` em `lib_deps`) com fontes `_tf` (ex.: `u8g2_font_helvB14_tf`, `u8g2_font_helvR10_tf`), que têm ç, ã, é, õ, e `enableUTF8Print()` | CONTRATO §5 |
| EAN-13 | 2 px por módulo: 95 módulos = 190 px (43 mm). Zonas de silêncio de 11 módulos à esquerda e 7 à direita: 226 px no total | RNF07 |
| Cor do EAN-13 | **sempre preto sobre branco**, inclusive no modo promoção: leitores a laser não enxergam barras vermelhas | RNF07 |
| Textos | nome até 20 caracteres, descrição até 30 (CONTRATO §5). O pior caso tem que caber: 20 letras largas ("WWWW...") e acentos | CONTRATO §5 |
| Preço | de R$ 0,01 a R$ 999,99. O pior caso "999,99" tem que caber | CONTRATO §5 |
| Vermelho | só o preço promocional e o destaque de oferta (RF10); o preço anterior é riscado em preto | RF10 |

Orçamento vertical sugerido (128 px), a ajustar no visor real:

```
y   4–20   nome do produto (helvB14)
y  24–36   descrição (helvR10)
y  40–88   "R$" pequeno + preço (logisoso46): 48 px
y  92–124  código de barras, 2 px/módulo, barras de ~32 px (sem dígitos legíveis embaixo, se faltar espaço)
```

Três telas:

- **Padrão:** nome, descrição, preço em preto, EAN-13.
- **Promoção:** preço promocional em vermelho no lugar do preço; preço anterior riscado em preto, menor, ao lado ou acima; EAN-13 igual ao padrão.
- **Sem produto (`render_unconfigured`):** "Etiqueta sem produto" e o `tag_id` legível, para o cadastro na aplicação.

Critérios:

- [ ] `render_ean13_modules("7891234567895", m)` produz exatamente:
  `10101101110010111001100100110110111101001110101010100111010100001000100100100011101001001110101`
  e `render_ean13_modules("7896089012453", m)` produz:
  `10101101110010111010111101001110110111001011101010111001011001101101100101110010011101000010101`
  (conferidos com uma biblioteca independente). Dígito verificador errado, tamanho errado ou caractere não numérico retornam `false`.
- [ ] As três telas desenhadas na placa com os dados dos vetores V1, V2 e V3 do contrato; "Café Pilão 500 g" e "torrado e moído" com acentos corretos.
- [ ] Dígitos do preço medidos com régua ≥ 10 mm.
- [ ] Código de barras lido por um aplicativo de celular a 10–25 cm em até duas tentativas, nos layouts padrão e promoção.
- [ ] Pior caso (nome de 20 caracteres largos, descrição de 30, preço 999,99, promoção) sem texto cortado ou sobreposto.
- [ ] `render_product` e `render_unconfigured` chamam `display_hibernate()` ao final e retornam `false` se `display_draw_full` falhar.

Para iterar no layout sem gastar redesenhos (cada um leva ~27 s), crie uma tela de teste no programa de bancada que chame as funções de desenho do `render`; mantenha a exceção de inclusão de `display.h` restrita a `src/bancada/`.

### F3: conectividade Wi-Fi, relógio e MQTT (S5)

Entrega: `net` e `mqtt` implementados. Pré-requisito: `include/secrets.h` preenchido e o Mosquitto configurado como no apêndice do contrato.

- `net_connect`: modo station, `WiFi.persistent(false)` (não gravar credenciais na flash a cada ciclo), espera até `timeout_ms`.
- `net_sync_time`: `configTime(0, 0, "pool.ntp.org")`; relógio válido quando o instante ≥ 1735689600 (CONTRATO §8). `net_now_utc()` retorna 0 enquanto não for válido.
- `mqtt_connect`: client id e usuário = `tag_id`; sessão limpa; **sem** Last Will; `setBufferSize(1024)` antes de conectar (o padrão de 256 bytes descarta a mensagem de 274 bytes **sem erro**).
- `mqtt_fetch_config`: assina `spt/{id}/config`, chama `loop()` até a retida chegar ou o prazo acabar; separa o envelope com ArduinoJson e copia o **valor decodificado** de `dados` para `ConfigEnvelope.data` sem alterar nenhum byte (é sobre esses bytes que o HMAC foi calculado); mensagem vazia (retida apagada) conta como `NoMessage`.
- `mqtt_publish_status`: JSON da seção 7 do contrato em `spt/{id}/status`, QoS 0, não retido.

Critérios (use `../tools/publicar_config.py`, seção 7):

- [ ] Com `publicar` de um produto próprio para o `id` da placa (seção 7), o log mostra `data_len` igual ao número de bytes do texto `dados` impresso pelo script e o mesmo `hmac`. Teste também um nome com acentos: o tamanho em bytes tem que bater.
- [ ] Com a retida apagada (`limpar`), o resultado é `NoMessage` dentro do prazo, sem travar.
- [ ] Com o broker desligado ou a senha errada, `mqtt_connect` retorna `false` dentro do prazo.
- [ ] Com o Wi-Fi desligado, `net_connect` retorna `false` dentro do prazo.
- [ ] `escutar` mostra o estado publicado, com `instante` coerente com a hora atual.

### F4: autenticação e sequência (S6)

Entrega: `auth_begin`, `auth_verify`.

- HMAC-SHA256 com `mbedtls_md_hmac` (`mbedtls/md.h`, já incluso no núcleo), sobre `data[0..data_len)`; compare os 16 primeiros bytes com `hmac_hex` em **tempo constante** (aceite só hex minúsculo, como no contrato).
- Verifique o HMAC **antes** de interpretar o JSON; só depois extraia `seq` (ArduinoJson, apenas o campo `seq`).
- `seq` menor que o último aceito → `Replay`; igual → `Unchanged`; maior → `Ok`.
- Para testar com os vetores sem mexer no `secrets.h` real, separe a decodificação da chave numa função `bool auth_begin_with_key_hex(const char* key_hex)`, chamada por `auth_begin()` e pelos testes.

Critérios (vetores da seção 9 do contrato, chave `d4c08c07...`):

- [ ] V1 com último seq 0 → `Ok`, seq 42; V1 de novo com último seq 42 → `Unchanged`.
- [ ] V2 com último 42 → `Ok`; V3 com último 43 → `Ok`.
- [ ] V4 → `BadHmac`; V5 com último 42 → `Replay`; V6 → `BadHmac`.
- [ ] `hmac_hex` com tamanho errado ou caracteres não hex → `Malformed`; chave inválida → `auth_begin` retorna `false` e `auth_verify` retorna `NoKey`.

### F5: ciclo de energia e agendamento (S7)

Entrega: `config`, `store`, partes pendentes de `power`, e o ciclo completo no `main`, seguindo o diagrama de estados da documentação (Inicialização → Conectando → Verificando → Decidindo → Redesenhando → Encerrando).

- **`store` precisa guardar a última configuração válida inteira** (o texto de `dados`, até 768 bytes), não só a versão: ao fim de uma promoção sem rede, a etiqueta tem que redesenhar o layout padrão com os dados do produto (RF11). Estenda `StoredState` e grave na NVS (`Preferences`, namespace `"spt"`) só quando algo mudar.
- `config_parse`: valida os campos conforme o contrato; `config_promotion_active`: com relógio inválido (`now_utc == 0`), **mantém** a promoção.
- Decisão de redesenho: redesenhe se a `versao` aplicada mudou **ou** se o visor mostra promoção e ela venceu. Sem configuração válida guardada, mostre `render_unconfigured`.
- Próximo despertar: o menor entre `CHECK_INTERVAL_S` e o tempo até `expira_em` da promoção em exibição (mínimo de 1 s).
- `power_deep_sleep`: habilita também o despertar pelo botão (ext0 em `PIN_BUTTON`, nível baixo, com `rtc_gpio_pullup_en`); depois de um despertar por ext0, chame `rtc_gpio_deinit` antes de usar o pino como GPIO comum.
- `power_battery_mv`: `analogReadMilliVolts(PIN_BATTERY) * BATTERY_DIVIDER`. Sem bateria ligada (placa no USB), o valor é próximo de 0, e o contrato aceita 0.
- `power_deadline_remaining_ms`: `POWER_CYCLE_DEADLINE_MS - millis()`, saturando em 0.
- Antes de dormir: `display_hibernate` (via `render`), `mqtt_disconnect`, `net_disconnect`.

Critérios (ambiente `demo`, intervalo de 3 min):

- [ ] RF07/RF08: ciclo completo pelo temporizador e pelo botão, com o log de cada estado.
- [ ] RF11: publique uma promoção de 2 min (`--promo-minutos 2`), espere aplicar, **desligue o hotspot** e confira que a etiqueta acorda sozinha no fim da promoção e volta ao layout padrão.
- [ ] RF13: com o hotspot desligado, o botão não altera nem apaga o visor.
- [ ] RNF03: ciclo sem redesenho ≤ 10 s, do despertar ao deep sleep (marcas de tempo do log).
- [ ] RNF04: alteração publicada aparece em ≤ 45 s após apertar o botão.
- [ ] RNF08: com o broker parado, o ciclo termina em deep sleep em ≤ 60 s.
- [ ] RNF12: V4 e V5 publicados não alteram o visor.

### F6: testes isolados (S8)

Execute de novo todos os critérios de F1 a F5 a partir de uma placa com a NVS apagada (`pio run -e demo -t erase` e depois gravar), e registre os resultados. Esses registros vão para o capítulo de testes da documentação.

## 6. Roteiro de bancada (F1, sem rede e sem bateria)

Ligações, com a placa **desconectada** do USB:

| Visor (WeAct) | ESP32 | | Botão | ESP32 |
|---|---|---|---|---|
| VCC | 3V3 | | um terminal | IO33 (D33) |
| GND | GND | | terminal na diagonal | GND |
| SDA (dados) | IO23 (D23) | | resistor 10 kΩ | entre IO33 e 3V3 |
| SCL (clock) | IO18 (D18) | | | |
| CS | IO5 (D5) | | | |
| D/C | IO17 (TX2) | | | |
| RES | IO16 (RX2) | | | |
| BUSY | IO4 (D4) | | | |

- No módulo WeAct, os rótulos SDA e SCL são do SPI (dados e clock), não de I2C. Se houver jumper ou chave de interface na placa do visor, ele deve estar em **4-line SPI**.
- Nesta fase, a placa é alimentada pelo USB; bateria, carregador e regulador ficam de fora.
- Não desencaixe o cabo flat do painel; manuseie o visor pelas bordas.

Passos:

1. `pio run -e bancada -t upload`, depois `pio device monitor -e bancada`, depois aperte **EN**.
2. Espere `visor (SPI + BUSY): OK` e o redesenho (~27 s, o visor pisca várias vezes).
3. Confira a tela A, meça as barras de 10 mm e 40 mm e anote a linha `RNF02`.
4. Aperte o botão (ou digite `r`) após 20 s: deve aparecer a tela B, vermelha.
5. Digite `s`, espere a placa dormir e aperte o botão: o log deve mostrar `BOTAO (ext0 OK)` e a imagem não pode ter sumido.

| Sintoma | Causa provável |
|---|---|
| `BUSY ... não baixou após o reset` | fio de BUSY solto ou trocado, visor sem 3V3/GND, jumper de interface errado |
| `atualização terminou em N ms, rápido demais` | BUSY não está sendo lida: fio em outro pino ou solto |
| redesenho chega a ~30 s com `Busy Timeout!` | BUSY presa em nível alto: confira RES (IO16) e D/C (IO17) |
| tela branca ou só ruído, sem erros | SDA/SCL invertidos, CS errado, ou classe de painel errada (teste `GxEPD2_290_Z13c` em `display.cpp`) |
| imagem espelhada ou de cabeça para baixo | troque `setRotation(1)` por `setRotation(3)` em `display.cpp` |
| vermelho aparece preto | classe de painel errada (o painel é de três cores) |
| `botao em repouso: LOW` | botão ligado nos dois terminais do mesmo par: use terminais na diagonal |
| placa não grava | cabo só de carga, driver CP210x ausente ou falta segurar BOOT |

## 7. Testar sem a aplicação

`../tools/publicar_config.py` (precisa de `pip install paho-mqtt`) faz o papel da aplicação:

```bash
python ../tools/publicar_config.py conferir                          # vetores do contrato (sem rede)
python ../tools/publicar_config.py chave --id <id da placa>          # linha TAG_HMAC_KEY_HEX para o secrets.h
python ../tools/publicar_config.py publicar --host <IP> --senha <senha da aplicacao> --id <id> \
    --nome "Dipirona 500 mg" --preco 1490 --descricao "caixa com 20 comprimidos" \
    --ean13 7891234567895 --promo-preco 1190 --promo-minutos 2
python ../tools/publicar_config.py escutar --host <IP> --senha <senha>
python ../tools/publicar_config.py limpar --host <IP> --senha <senha> --id <id>
```

- **Produto próprio:** gere a chave da sua placa com `chave --id <id>` (o `id` aparece no log de qualquer ambiente) e cole a linha no `secrets.h`. Sem `--chave-mestra`, o script usa a chave-mestra de teste, o que basta para o desenvolvimento.
- **Vetores V1–V6 na sua placa:** os vetores são da etiqueta `a1b2c3d4e5f6`. Para usá-los, grave no `secrets.h` a chave de teste `d4c08c076e44144313962c8344e2629ea372ae885e07f354e1bd0cd8523fe573` e, só para esse teste, force o `tag_id` a `a1b2c3d4e5f6` com uma flag de build temporária. Não deixe isso no código entregue.
- O `seq` padrão do script é o instante atual, que sempre cresce. Depois de publicar com `seq` alto, os vetores (seq 41–44) passam a ser rejeitados como repetição, o que é o comportamento correto; apague a NVS (`-t erase`) para repetir os testes de vetores.
- O broker roda no notebook; a etiqueta e o notebook ficam no mesmo hotspot. Confira o IP do notebook a cada sessão e use-o em `MQTT_HOST`. Mosquitto precisa de `listener 1883` e da porta 1883 liberada no firewall do Windows (CONTRATO, apêndice).

## 8. Divergências conhecidas com a documentação

Avise a equipe ao confirmar na placa; a documentação será atualizada com os valores medidos.

| Tema | Documentação | Valor de referência atual |
|---|---|---|
| Duração do redesenho | 19 s (Quadro 11) | ~26–27 s (GxEPD2, painel GDEM029C90); ainda dentro dos 30 s do RNF02 |
| Ciclo com redesenho pelo botão | 23–25 s | ~32–35 s; ainda dentro dos 45 s do RNF04 |
| Fonte do preço | não especificada | logisoso46 (46 px); as fontes padrão do Adafruit GFX não atingem 10 mm |
