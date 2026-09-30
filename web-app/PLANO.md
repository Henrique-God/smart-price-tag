# Plano do Smart Price Tag

Fonte: `../main (1).pdf`, sobretudo os Quadros 1 e 2 do capítulo 2 e as seções 3.3.2, 3.4 e 3.6. **Os IDs abaixo seguem as tabelas do capítulo 2**; as remissões no texto posterior trocam alguns RNF.

## Etapas

| Etapa | Resultado nesta entrega | Pendente |
|---|---|---|
| E1 — estrutura e banco | FastAPI/Jinja2/SQLite, migração das colunas MQTT de `etiqueta` preservando bancos antigos | — |
| E2 — administrador | Login, bcrypt, sessão e CSRF testados | — |
| E3 — catálogo | Produtos, etiquetas, vínculos e promoções testados | — |
| E4 — comunicação | Mosquitto com senha e ACL testado; aplicação monta HMAC, sequência e publicação retida com recuperação após reconexão | Provisionamento e autenticação no firmware; operação na LAN real |
| E5 — monitoramento | Estados MQTT válidos persistidos; interface separa publicação, espera e versão confirmada | Validação com estados da etiqueta física e prova de aplicação no visor |
| E6 — firmware/hardware | — | Toda a implementação e montagem |
| E7 — integração | Teste automatizado com broker Mosquitto temporário e clientes de teste | Ensaios com firmware, visor, botão, consumo e prazos |

## Matriz de requisitos

| ID | Requisito dos Quadros 1 e 2 | Situação comprovada |
|---|---|---|
| RF01 | CRUD de produtos, nome, preço, descrição, EAN-13 | Concluído na aplicação |
| RF02 | Cadastro e vínculo/desvínculo de etiquetas | Concluído na aplicação |
| RF03 | Promoção com preço e término | Concluído na aplicação |
| RF04 | Entrega no despertar seguinte | Parcial: configuração retida e reconexão verificadas no broker; despertar real TODO |
| RF05 | Autenticação antes de alterações | Concluído na aplicação |
| RF06 | Estado aplicado, bateria e última comunicação | Parcial: persistência/interface com estados MQTT de teste; confirmação física TODO |
| RF07 | Ciclo completo a cada despertar | TODO — firmware/hardware |
| RF08 | Botão executa o mesmo ciclo | TODO — firmware/hardware |
| RF09 | Nome, preço, descrição e EAN-13 no visor | TODO — firmware/hardware |
| RF10 | Layout promocional, preço anterior riscado e vermelho | TODO — firmware/hardware |
| RF11 | Reversão local ao expirar promoção | TODO — firmware/hardware |
| RF12 | Publicação de estado pela etiqueta | TODO — firmware/hardware; receptor web testado com mensagem sintética |
| RF13 | Última imagem válida em falha de rede/broker | TODO — firmware/hardware |
| RNF01 | Autonomia estimada ≥ 180 dias nas condições da tabela | TODO — hardware/ensaio |
| RNF02 | Redesenho completo ≤ 30 s | TODO — firmware/hardware |
| RNF03 | Ciclo sem redesenho ≤ 10 s | TODO — firmware/hardware |
| RNF04 | Atualização ≤ 24 h ou ≤ 45 s pelo botão | TODO — firmware/hardware/ensaio |
| RNF05 | E-paper 2,9", 296 × 128, três cores | TODO — hardware |
| RNF06 | Dígitos do preço ≥ 10 mm, legíveis a 1,5 m | TODO — hardware/ensaio |
| RNF07 | EAN-13 preto, legível de 10 a 25 cm | TODO — hardware/ensaio |
| RNF08 | Deep sleep em todos os caminhos, ciclo ≤ 60 s | TODO — firmware/hardware |
| RNF09 | Broker exige usuário e senha | Concluído na configuração e no teste Mosquitto local |
| RNF10 | ACL limita cada etiqueta aos próprios tópicos | Concluído na configuração e no teste Mosquitto local |
| RNF11 | Senhas de usuários somente como hash | Concluído para administrador e arquivo de senhas Mosquitto |
| RNF12 | Etiqueta descarta configuração falsa ou antiga | Parcial: app produz HMAC e sequência; rejeição no firmware TODO |
| RNF13 | Bateria Li-Po ≥ 1200 mAh protegida | TODO — hardware |

## Contrato implementado nesta entrega

- `publisher` serializa `produto` e `promocao`, deriva uma versão SHA-256 curta do conteúdo, incrementa `seq` quando ele muda e grava envelope `dados`/`hmac` no SQLite. Sem produto, ambos são `null`. A última configuração desejada fica disponível para republicação após falhas.
- `security` deriva a chave individual por HMAC-SHA256 da mestra e do MAC e trunca o HMAC da mensagem em 128 bits. A chave mestra vem de ambiente; o provisionamento grava chaves individuais em arquivos locais ignorados.
- `mqtt` assina `spt/+/status`, publica com QoS 1 e `retain=true`, grava versão publicada após confirmação do broker e republica na reconexão/inicialização. Usa sessão limpa, sem Last Will. Execute somente um processo web conectado ao broker.
- `monitor` valida tópico, esquema, tamanho, intervalos e instante dos estados, grava bateria, RSSI, firmware, instante e versão confirmada. Estado antigo não substitui estado novo. A página calcula “Aplicada” quando a versão confirmada coincide com a publicada e o estado foi recebido para a sequência atual.
- A migração SQLite adiciona colunas a `etiqueta` sem trocar os nomes das tabelas/colunas anteriores. Dados locais continuam fora do Git.

## Verificação

- [x] Monografia lida; IDs conferidos com os Quadros 1 e 2.
- [x] Testes de autenticação e catálogo anteriores continuam passando.
- [x] Testes de serialização, HMAC exato, versão, sequência e validação de estados passaram.
- [x] Teste de integração com Mosquitto 2.1.2 instalado localmente passou: autenticação, ACL de leitura/escrita, configuração retida, estado MQTT sintético, atualização depois de derrubar/reiniciar o broker e recusa de ACK para publicação não autorizada.
- [ ] Teste com etiqueta ESP32 real, aceitação/rejeição HMAC e sequência no firmware, confirmação do visor, autonomia e limites de tempo.

Comando executado: `.\.venv\Scripts\python -m pytest -q`. O aviso de depreciação é da combinação Starlette/httpx usada pelo cliente de teste.
