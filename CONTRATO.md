# Contrato de comunicação — Smart Price Tag

**Versão 0.1 — rascunho de 06/10/2026.** Vale para o firmware da etiqueta e para a aplicação de gerenciamento.

Este arquivo é a única fonte de verdade sobre o que trafega entre a aplicação e a etiqueta. Qualquer alteração precisa do aceite de pelo menos um integrante de cada dupla (firmware e aplicação). Os agentes de IA **não** alteram este arquivo; se uma implementação exigir mudança, ela é proposta à equipe.

Itens marcados com **⚠ a confirmar** ainda dependem do aceite da dupla da aplicação. Até lá, valem os valores escritos aqui.

---

## 1. Rede e broker

| Item | Valor |
|---|---|
| Rede | Wi-Fi 2,4 GHz, WPA2-Personal (hotspot de celular no protótipo) |
| Broker | Mosquitto 2.x, no mesmo computador da aplicação |
| Porta | 1883 (sem TLS) |
| Acesso anônimo | proibido |
| Persistência do broker | ativada, para que as mensagens retidas sobrevivam a um reinício do broker |

## 2. Identidade

| Item | Formato | Exemplo |
|---|---|---|
| Identificador da etiqueta (`id`) | endereço MAC da interface Wi-Fi (estação), 12 caracteres hexadecimais minúsculos, sem separadores | `a1b2c3d4e5f6` |
| Usuário MQTT da etiqueta | igual ao `id` | `a1b2c3d4e5f6` |
| Client ID MQTT da etiqueta | igual ao `id` | `a1b2c3d4e5f6` |
| Usuário MQTT da aplicação | `aplicacao` | — |

## 3. Tópicos

| Tópico | Publicado por | QoS | Retido | Conteúdo |
|---|---|---|---|---|
| `spt/{id}/config` | aplicação | 1 | **sim** | envelope de configuração (seção 4) |
| `spt/{id}/status` | etiqueta | 0 | não | estado da etiqueta (seção 7) |

A aplicação assina `spt/+/status`. A etiqueta conecta com sessão limpa e sem mensagem de *Last Will*.

## 4. Envelope de configuração

Objeto JSON com exatamente dois campos:

| Campo | Tipo | Regra |
|---|---|---|
| `dados` | texto | a configuração (seção 5) serializada em JSON, guardada como **texto** dentro do envelope |
| `hmac` | texto | 32 caracteres hexadecimais minúsculos (seção 6) |

- Codificação: UTF-8.
- **Tamanho máximo da mensagem inteira: 512 bytes.** O firmware usa buffer MQTT de 1024 bytes.

## 5. Conteúdo de `dados`

```json
{
  "produto":  { "nome": "...", "preco": 1490, "descricao": "...", "ean13": "7891234567895" },
  "promocao": { "preco": 1190, "expira_em": 1795680000 },
  "versao": "5af98e6c",
  "seq": 42
}
```

| Campo | Tipo | Regra |
|---|---|---|
| `produto` | objeto ou `null` | `null` = etiqueta sem produto; o visor é limpo |
| `produto.nome` | texto | 1 a **20** caracteres ⚠ a confirmar no F2 |
| `produto.preco` | inteiro | preço em **centavos**, de 1 a 99999 (R$ 0,01 a R$ 999,99) |
| `produto.descricao` | texto | 0 a **30** caracteres ⚠ a confirmar no F2 |
| `produto.ean13` | texto | exatamente 13 dígitos, com dígito verificador válido (a aplicação valida) |
| `promocao` | objeto ou `null` | `null` = sem promoção. Só pode existir se `produto` não for `null` |
| `promocao.preco` | inteiro | centavos, maior que 0 e menor que `produto.preco` |
| `promocao.expira_em` | inteiro | instante de término, em segundos desde 01/01/1970 **UTC** |
| `versao` | texto | 8 caracteres hexadecimais minúsculos (regra abaixo) |
| `seq` | inteiro | de 1 a 2147483647, crescente por etiqueta |

Os limites de caracteres contam caracteres, não bytes ("ã" conta como 1).

**Cálculo de `versao` (feito só pela aplicação; o firmware apenas compara):** os 8 primeiros caracteres hexadecimais do SHA-256 da serialização canônica de `{"produto": ..., "promocao": ...}`, com chaves ordenadas, sem espaços (`separators=(",", ":")`) e caracteres não ASCII preservados em UTF-8. Em Python:

```python
c = json.dumps({"produto": p, "promocao": pr}, sort_keys=True,
               separators=(",", ":"), ensure_ascii=False)
versao = hashlib.sha256(c.encode("utf-8")).hexdigest()[:8]
```

**Acentos ⚠ a confirmar:** a aplicação envia o texto com acentos em UTF-8, e o firmware desenha com fontes que têm acentuação (U8g2_for_Adafruit_GFX). A alternativa, caso a dupla do firmware não consiga, é a aplicação remover os acentos antes de enviar.

## 6. Autenticação (HMAC)

1. **Chave da etiqueta:** `chave_etiqueta = HMAC-SHA256(chave = chave_mestra, mensagem = id em ASCII)`, 32 bytes.
   - A chave-mestra (32 bytes) fica só com a aplicação.
   - A etiqueta recebe apenas a sua chave derivada, gravada no firmware na compilação como 64 caracteres hexadecimais.
2. **Código:** `hmac = hex(HMAC-SHA256(chave = chave_etiqueta, mensagem = bytes UTF-8 do texto de dados))[:32]`, em minúsculas.
   - "Texto de `dados`" é o valor **já decodificado** do campo do envelope, ou seja, sem as barras de escape (`\"`) que aparecem no JSON do envelope.
   - A etiqueta calcula o código **antes** de interpretar `dados`.
   - A comparação é feita em tempo constante.
3. **Sequência:** a etiqueta guarda em memória não volátil o último `seq` aceito (valor inicial 0).
   - `seq` **menor** que o último aceito: rejeitada.
   - `seq` **igual**: aceita, porque a mensagem retida é reentregue a cada ciclo.
   - `seq` **maior**: aceita, e o novo valor é gravado.
   - A aplicação nunca reinicia a contagem de uma etiqueta. Se o banco da aplicação for apagado, a etiqueta precisa ser regravada apagando a memória não volátil (`pio run -t erase`).
4. Qualquer mensagem que não siga este contrato é descartada (JSON inválido, campo ausente, tipo errado, limite excedido, código divergente), e a etiqueta mantém a imagem atual.

## 7. Mensagem de estado

```json
{ "versao": "5af98e6c", "tensao_mv": 3920, "rssi": -61, "firmware": "1.0.0", "instante": 1795248312 }
```

| Campo | Tipo | Regra |
|---|---|---|
| `versao` | texto | versão da última configuração aplicada; `""` se nenhuma foi aceita ainda |
| `tensao_mv` | inteiro | tensão da bateria em milivolts; `0` se não houver leitura (placa alimentada só pelo USB) |
| `rssi` | inteiro | intensidade do sinal Wi-Fi em dBm |
| `firmware` | texto | versão do firmware no formato `x.y.z` |
| `instante` | inteiro | segundos UTC do ciclo; **`0` se o relógio nunca foi sincronizado** |

A mensagem de estado não é autenticada e tem no máximo 256 bytes.

## 8. Relógio

- A etiqueta sincroniza por SNTP com `pool.ntp.org`.
- Todos os instantes trafegam em UTC; a conversão para o horário local é feita só na aplicação.
- O relógio é considerado válido quando o instante é maior ou igual a `1735689600` (01/01/2025).

---

## 9. Vetores de teste

Valores **só para teste**. Nunca use esta chave-mestra em produção nem no protótipo da demonstração.

| Item | Valor |
|---|---|
| Chave-mestra (hex) | `000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f` |
| `id` | `a1b2c3d4e5f6` |
| Chave da etiqueta (hex) | `d4c08c076e44144313962c8344e2629ea372ae885e07f354e1bd0cd8523fe573` |

| Vetor | Situação | Último `seq` aceito antes | `hmac` | Resultado esperado |
|---|---|---|---|---|
| V1 | produto com promoção | 0 | `9bb4c082b6209aa642ccf1652b2a5397` | aceita |
| V2 | produto com acentos, sem promoção | 42 | `4f8f7929e872ef07e6a85fba574771ef` | aceita |
| V3 | etiqueta sem produto | 43 | `d9e4ebd4a9acd35286ddeef317dabc8a` | aceita; visor limpo |
| V4 | V1 com o preço adulterado (1490 → 990), mesmo `hmac` | 0 | `9bb4c082b6209aa642ccf1652b2a5397` | **rejeitada** (código divergente) |
| V5 | V1 com `seq` 41, código válido | 42 | `829fa9736b1d7049bbe52de46f0c6dc3` | **rejeitada** (sequência antiga) |
| V6 | V1 assinada com a chave de outra etiqueta (`ffffffffffff`) | 0 | `2aa16b0291bb89d50167c2ab381e9421` | **rejeitada** (código divergente) |

Texto exato de `dados` de cada vetor (o `hmac` é calculado sobre estes bytes):

```text
V1: {"produto":{"nome":"Dipirona 500 mg","preco":1490,"descricao":"caixa com 20 comprimidos","ean13":"7891234567895"},"promocao":{"preco":1190,"expira_em":1795680000},"versao":"5af98e6c","seq":42}
V2: {"produto":{"nome":"Café Pilão 500 g","preco":2490,"descricao":"torrado e moído","ean13":"7896089012453"},"promocao":null,"versao":"5d527b68","seq":43}
V3: {"produto":null,"promocao":null,"versao":"ebf5fe64","seq":44}
V4: {"produto":{"nome":"Dipirona 500 mg","preco":990,"descricao":"caixa com 20 comprimidos","ean13":"7891234567895"},"promocao":{"preco":1190,"expira_em":1795680000},"versao":"5af98e6c","seq":42}
V5: {"produto":{"nome":"Dipirona 500 mg","preco":1490,"descricao":"caixa com 20 comprimidos","ean13":"7891234567895"},"promocao":{"preco":1190,"expira_em":1795680000},"versao":"5af98e6c","seq":41}
```

V6 usa o mesmo texto de V1, com o código calculado pela chave de outra etiqueta.

Mensagem V1 exatamente como trafega no tópico (274 bytes):

```text
{"dados":"{\"produto\":{\"nome\":\"Dipirona 500 mg\",\"preco\":1490,\"descricao\":\"caixa com 20 comprimidos\",\"ean13\":\"7891234567895\"},\"promocao\":{\"preco\":1190,\"expira_em\":1795680000},\"versao\":\"5af98e6c\",\"seq\":42}","hmac":"9bb4c082b6209aa642ccf1652b2a5397"}
```

O script `tools/publicar_config.py` publica qualquer um desses vetores no broker (`--vetor V1`), gera configurações novas assinadas e confere esta tabela (`--conferir`).

---

## Apêndice — configuração do Mosquitto

`mosquitto.conf`:

```
listener 1883
allow_anonymous false
password_file /caminho/para/passwd
acl_file /caminho/para/acl
persistence true
persistence_location /caminho/para/dados/
```

`acl`:

```
user aplicacao
topic readwrite spt/#

pattern read  spt/%u/config
pattern write spt/%u/status
```

Criação dos usuários:

```bash
mosquitto_passwd -c passwd aplicacao
mosquitto_passwd passwd a1b2c3d4e5f6
```

No Windows, libere a porta TCP 1883 no firewall para conexões de entrada.
