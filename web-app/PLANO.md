# Plano do Smart Price Tag

Fonte: leitura integral de `../main (1).pdf` (36 páginas), especialmente os Quadros 1 e 2 do capítulo 2, a Figura 5 e o Quadro 6. Os IDs abaixo seguem **as tabelas do capítulo 2**; algumas remissões no texto posterior da monografia trocam os números dos RNF.

## Macrotarefas e critérios de conclusão

| Etapa | Macrotarefa | Critério de conclusão | Estado nesta entrega |
|---|---|---|---|
| E1 | Estrutura, banco e configuração da aplicação | FastAPI/Jinja2/Uvicorn e SQLModel/SQLite iniciam com configuração externa e dados persistentes | **Concluída** |
| E2 | Autenticação e proteção da interface | Primeiro administrador criado sem senha padrão; bcrypt, sessão e proteção das alterações verificadas | **Concluída** |
| E3 | Catálogo e interface web | Produtos, etiquetas, vínculos e promoções gerenciáveis em páginas acessíveis, com validação e testes da aplicação | **Concluída** |
| E4 | Comunicação e segurança entre aplicação e etiqueta | Mosquitto com credenciais/ACL; futuros módulos `mqtt`, `security` e `publisher` publicam configurações retidas autenticadas; HTTPS configurado | TODO — MQTT/broker |
| E5 | Monitoramento e confirmação | Módulo `monitor` recebe estados reais; mostra bateria, última comunicação e comparação entre versão publicada e confirmada | TODO — monitoramento/MQTT |
| E6 | Hardware e firmware da etiqueta | Circuito montado; firmware modular executa ciclo, layouts, código EAN-13, promoção, autenticação e economia de energia | TODO — firmware/hardware |
| E7 | Ensaios isolados e integração | Testes da comunicação, firmware e sistema real demonstram entrega, confirmação, prazos, legibilidade e autonomia estimada | TODO — testes de integração/hardware |

**Regra de estado:** nesta etapa, salvar uma alteração no SQLite significa apenas “salvo no catálogo”. Não existe publicação MQTT nem confirmação pelo visor. A interface não mostra “aplicada”, “pendente” ou telemetria inventada.

## Matriz de requisitos

| ID | Resumo do requisito (Quadros 1 e 2) | Etapa(s) | Estado nesta entrega |
|---|---|---|---|
| RF01 | CRUD de produtos com nome, preço, descrição curta e EAN-13 | E1, E3 | **Concluído** |
| RF02 | Cadastro de etiqueta e vínculo/desvínculo de um produto | E1, E3 | **Concluído** |
| RF03 | Configuração de promoção, preço e término | E1, E3 | **Concluído** |
| RF04 | Entrega de alterações no despertar seguinte | E4, E6, E7 | TODO |
| RF05 | Autenticação antes de alterações | E2 | **Concluído** |
| RF06 | Estado aplicado, bateria e última comunicação | E4, E5, E7 | TODO |
| RF07 | Ciclo completo da etiqueta a cada despertar | E6, E7 | TODO |
| RF08 | Despertar imediato pelo botão | E6, E7 | TODO |
| RF09 | Visor com produto, preço, descrição e EAN-13 | E6, E7 | TODO |
| RF10 | Layout promocional com preço anterior riscado e vermelho | E6, E7 | TODO |
| RF11 | Reversão local ao expirar promoção | E6, E7 | TODO |
| RF12 | Publicação de estado pela etiqueta | E4, E5, E6, E7 | TODO |
| RF13 | Manter última imagem válida em falha de rede/broker | E6, E7 | TODO |
| RNF01 | Autonomia estimada ≥ 180 dias nas condições da tabela | E6, E7 | TODO |
| RNF02 | Redesenho completo ≤ 30 s | E6, E7 | TODO |
| RNF03 | Ciclo sem redesenho ≤ 10 s | E6, E7 | TODO |
| RNF04 | Atualização no visor ≤ 24 h ou ≤ 45 s pelo botão | E4, E6, E7 | TODO |
| RNF05 | E-paper de 2,9", 296 × 128, três cores | E6, E7 | TODO |
| RNF06 | Dígitos do preço ≥ 10 mm, legíveis a 1,5 m | E6, E7 | TODO |
| RNF07 | EAN-13 preto, legível de 10 a 25 cm | E6, E7 | TODO |
| RNF08 | Deep sleep em todos os caminhos, ciclo ≤ 60 s | E6, E7 | TODO |
| RNF09 | Broker exige usuário e senha | E4, E7 | TODO |
| RNF10 | ACL por etiqueta para tópicos de configuração e estado | E4, E7 | TODO |
| RNF11 | Senhas armazenadas somente como hash | E1, E2 | **Concluído** |
| RNF12 | Etiqueta rejeita configuração falsa ou antiga | E4, E6, E7 | TODO |
| RNF13 | Bateria Li-Po ≥ 1200 mAh com proteção | E6, E7 | TODO |

## Decisões de implementação desta entrega

- A promoção fica nos campos de `produto`, como no Quadro 6. Seu instante de expiração é persistido em segundos Unix UTC; o formulário apresenta e recebe o horário explicitamente em UTC.
- Preços são números inteiros em centavos no SQLite; a interface recebe valores decimais com duas casas e vírgula ou ponto.
- O identificador da etiqueta é o MAC de 12 dígitos hexadecimais, normalizado em maiúsculas sem separadores, seguindo a seção 3.4.2.
- A exclusão de produto vinculado é recusada até o desvínculo, para evitar referência órfã.
- O primeiro administrador é criado por comando local interativo, que só funciona enquanto não houver usuário; não há conta nem senha embutida.
- A aplicação exige uma chave de sessão fornecida por variável de ambiente. Em produção, o navegador deve acessar o servidor por HTTPS e os cookies devem usar a opção `Secure`.
- Os identificadores do código e os nomes dos módulos (`web`, `authentication`, `catalog`, `db`) são em inglês. Os nomes das tabelas e colunas SQLite existentes foram preservados para manter os catálogos locais compatíveis.
- A interface Jinja2/CSS e os serviços Python estão separados por responsabilidade dentro da mesma aplicação FastAPI; não existe frontend independente.
- A aplicação web e sua documentação ficam em `web-app/`. O futuro firmware do ESP32 deve ficar em `firmware/`, como pasta irmã; segredos e dados locais nunca devem ser commitados no repositório público.

## Verificação desta entrega

- [x] PDF e diagramas lidos; IDs conferidos com as tabelas do capítulo 2.
- [x] Aplicação e testes de autenticação e catálogo implementados.
- [x] Testes automatizados executados com sucesso: `python -m pytest -q` — 4 testes passaram, inclusive leitura de banco com esquema anterior (1 aviso de depreciação na dependência de teste Starlette/httpx).
- [ ] MQTT, broker, publicador, monitor, segurança das mensagens, firmware, hardware e testes de integração permanecem para as etapas E4–E7.
