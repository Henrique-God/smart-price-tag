# Plano do Smart Price Tag

Fonte: `../main (1).pdf`, sobretudo os Quadros 1 e 2 do capítulo 2 e as seções 3.3.2, 3.4 e 3.6. **Os IDs abaixo seguem as tabelas do capítulo 2**; as remissões no texto posterior trocam alguns RNF.

## Etapas

| Etapa | Resultado nesta entrega | Pendente |
|---|---|---|
| E1 — estrutura e banco | FastAPI/Jinja2/SQLite, migração das colunas MQTT de `etiqueta` preservando bancos antigos | — |
| E2 — administrador | Login, bcrypt, sessão e CSRF testados | — |
| E3 — catálogo | Produtos, etiquetas, vínculos e promoções testados | — |
| E4 — comunicação | Mosquitto local gerenciado pela tela administrativa, credenciais individuais, ACL por etiqueta, tópicos com o formato de letras usado pela ESP, HMAC, sequência e publicação retida; conexão e entrega observadas na LAN com uma ESP | Verificar HMAC/seq no firmware e entrega no ciclo de despertar |
| E5 — monitoramento | Estado inicial da ESP física recebido e persistido; interface separa ausência de estado, estado recebido e versão confirmada; painel expansível por etiqueta com atualização periódica | ESP informar versão aplicada; confirmar conteúdo no visor e medir operação prolongada |
| E6 — firmware/hardware | ESP externa ao repositório autenticou, recebeu configuração e publicou status inicial | Código do firmware, visor, botão, energia e validação de HMAC/seq ainda não avaliados |
| E7 — integração | Teste automatizado com broker temporário e observação de conexão, configuração retida e status inicial na LAN real | Ciclo completo de aplicação no firmware/visor, consumo e prazos |

## Matriz de requisitos

| ID | Requisito dos Quadros 1 e 2 | Situação comprovada |
|---|---|---|
| RF01 | CRUD de produtos, nome, preço, descrição, EAN-13 | Concluído na aplicação |
| RF02 | Cadastro e vínculo/desvínculo de etiquetas | Concluído na aplicação |
| RF03 | Promoção com preço e término | Concluído na aplicação |
| RF04 | Entrega no despertar seguinte | Parcial: configuração retida entregue à ESP física; despertar seguinte ainda não medido |
| RF05 | Autenticação antes de alterações | Concluído na aplicação |
| RF06 | Estado aplicado, bateria e última comunicação | Parcial: status inicial real, RSSI, firmware e último recebimento visíveis; bateria não medida e versão aplicada não informada |
| RF07 | Ciclo completo a cada despertar | TODO — firmware/hardware |
| RF08 | Botão executa o mesmo ciclo | TODO — firmware/hardware |
| RF09 | Nome, preço, descrição e EAN-13 no visor | TODO — firmware/hardware |
| RF10 | Layout promocional, preço anterior riscado e vermelho | TODO — firmware/hardware |
| RF11 | Reversão local ao expirar promoção | TODO — firmware/hardware |
| RF12 | Publicação de estado pela etiqueta | Parcial: ESP física publicou status inicial e a aplicação registrou o recebimento; versão aplicada ainda não informada |
| RF13 | Última imagem válida em falha de rede/broker | TODO — firmware/hardware |
| RNF01 | Autonomia estimada ≥ 180 dias nas condições da tabela | TODO — hardware/ensaio |
| RNF02 | Redesenho completo ≤ 30 s | TODO — firmware/hardware |
| RNF03 | Ciclo sem redesenho ≤ 10 s | TODO — firmware/hardware |
| RNF04 | Atualização ≤ 24 h ou ≤ 45 s pelo botão | TODO — firmware/hardware/ensaio |
| RNF05 | E-paper 2,9", 296 × 128, três cores | TODO — hardware |
| RNF06 | Dígitos do preço ≥ 10 mm, legíveis a 1,5 m | TODO — hardware/ensaio |
| RNF07 | EAN-13 preto, legível de 10 a 25 cm | TODO — hardware/ensaio |
| RNF08 | Deep sleep em todos os caminhos, ciclo ≤ 60 s | TODO — firmware/hardware |
| RNF09 | Broker exige usuário e senha | Concluído na configuração e nos testes; autenticação de ESP física observada |
| RNF10 | ACL limita cada etiqueta aos próprios tópicos | Concluído na configuração e nos testes; publicação de status da ESP física aceita após alinhar o formato de letras |
| RNF11 | Senhas de usuários somente como hash | Concluído para administrador e arquivo de senhas Mosquitto |
| RNF12 | Etiqueta descarta configuração falsa ou antiga | Parcial: app produz HMAC e sequência; rejeição no firmware TODO |
| RNF13 | Bateria Li-Po ≥ 1200 mAh protegida | TODO — hardware |

## Contrato implementado nesta entrega

- `publisher` serializa `produto` e `promocao`, deriva uma versão SHA-256 curta do conteúdo, incrementa `seq` quando ele muda e grava envelope `dados`/`hmac` no SQLite. Sem produto, ambos são `null`. A última configuração desejada fica disponível para republicação após falhas.
- `security` deriva a chave individual por HMAC-SHA256 da mestra e do MAC e trunca o HMAC da mensagem em 128 bits. A chave mestra vem de ambiente ou de arquivo local privado; o provisionamento grava chaves individuais em arquivos ignorados pelo Git.
- `broker_admin` cria configuração, contas com senha exclusiva, ACL e segredos locais fora do Git. A tela administrativa permite provisionar, alternar maiúsculas/minúsculas do usuário e dos tópicos, trocar senha, revogar acesso e ajustar o listener. Alterações na ACL ou no listener exigem reiniciar o broker.
- `mqtt` assina `spt/+/status`, publica com QoS 1 e `retain=true` no tópico da conta provisionada, grava versão publicada após confirmação do broker e republica na reconexão/inicialização. Usa sessão limpa, sem Last Will. Execute somente um processo web conectado ao broker.
- `monitor` aceita o MAC no tópico em maiúsculas ou minúsculas e valida esquema, tamanho, valores e instante. `versao` vazia e `instante` zero são aceitos como estado sem confirmação e sem relógio; o servidor registra o horário de recebimento. Estados com instante válido antigo não substituem o novo. A interface mostra “Estado recebido” após comunicação e “Aplicada” quando a ESP informa a versão atual; o status não inclui `seq` nem comprova o visor.
- As telas MQTT e Etiquetas atualizam estados a cada 5 segundos por rota autenticada. A aba Etiquetas apresenta um painel expansível por ESP com RSSI, bateria, firmware, versões e último recebimento. O último contato não é prova de conexão MQTT ativa.
- A migração SQLite adiciona colunas a `etiqueta` sem trocar os nomes das tabelas/colunas anteriores. Dados locais continuam fora do Git.

## Verificação

- [x] Monografia lida; IDs conferidos com os Quadros 1 e 2.
- [x] Testes de autenticação e catálogo anteriores continuam passando.
- [x] Testes de serialização, HMAC exato, versão, sequência e validação de estados passaram.
- [x] Teste de integração com Mosquitto 2.1.2 instalado localmente passou: autenticação, ACL de leitura/escrita, configuração retida, estado MQTT sintético, atualização depois de derrubar/reiniciar o broker e recusa de ACK para publicação não autorizada.
- [x] Na LAN, uma ESP física autenticou com usuário minúsculo, recebeu a configuração retida e publicou um estado inicial, entregue pelo broker ao backend. O estado informou `versao` vazia e `instante` zero; RSSI, firmware e horário de recebimento foram registrados.
- [ ] Verificar com a ESP física a versão aplicada, aceitação/rejeição HMAC e sequência no firmware, confirmação do visor, autonomia e limites de tempo.

Nesta revisão, `.\.venv\Scripts\python.exe -m pytest -q` terminou com **9 testes aprovados** e um aviso de depreciação da combinação Starlette/httpx usada pelo cliente de teste. A observação com ESP física foi manual e não comprova HMAC/seq no firmware nem aplicação no visor.
