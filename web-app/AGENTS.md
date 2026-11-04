# Instruções para trabalhar no web-app

## Contexto

Este é um **repositório público**. A aplicação usa Python 3.12+, FastAPI, Jinja2, SQLite/SQLModel e MQTT com Mosquitto. O frontend é renderizado no servidor, com CSS e JavaScript nativos; não há etapa de build com Node. A interface é em português brasileiro. O firmware das etiquetas não está neste repositório.

## Iniciar a aplicação

Com dependências e provisionamento local preparados, execute da raiz de `smart-price-tag/`, no PowerShell:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./web-app/run-local.sh
```

No Git Bash:

```bash
bash web-app/run-local.sh
```

Dentro de `web-app/`, substitua o caminho do script por `./run-local.sh`. Use o Bash do Git for Windows explicitamente no PowerShell para evitar chamar o Bash do WSL. Ajuste o caminho do Git caso a instalação seja diferente.

A aplicação fica em **http://127.0.0.1:8000**. O script usa `.venv/Scripts/python.exe`, carrega `secrets/session.key`, usa `data/smart_price_tag.db` e a configuração MQTT local. Ele desativa cookies seguros somente para HTTP local. Não é necessário ativar a `.venv` manualmente. Mantenha o terminal aberto e encerre com Ctrl+C.

No macOS (pyenv ou Homebrew), execute a partir de `web-app/`:

```bash
./run-local-mac.sh                       # app em http://127.0.0.1:8000 (SPT_PORT muda a porta)
/opt/homebrew/opt/mosquitto/sbin/mosquitto -c data/broker/mosquitto.conf -v   # broker, em outro terminal
```

O script usa o venv `~/.venvs/spt` (fora do iCloud; `SPT_VENV` muda o caminho), reinstala dependências quando `requirements.txt` muda e não sobrescreve `data/` nem `secrets/`. Não use `brew services start mosquitto` (porta 1883 com configuração padrão); o broker do projeto usa a porta **1884**. Testes no Mac: `~/.venvs/spt/bin/python -m pytest -q`. Para conferências visuais, suba uma instância separada com banco temporário, `SPT_SESSION_SECRET` sintético e sem conexão ao broker real, em outra porta.

Para comunicar com as etiquetas no Windows, execute em outro terminal, também da raiz:

```powershell
& "C:\Program Files\Git\bin\bash.exe" ./web-app/run-broker.sh
```

No Git Bash, use `bash web-app/run-broker.sh`. Os scripts atuais são para Windows e esperam Mosquitto em `C:\Program Files\mosquitto`. Execute **uma única instância web conectada ao broker**. Confira se a porta 8000 está disponível; não encerre processos existentes sem identificar o que são. Consulte `README.md` para instalação, criação do administrador e provisionamento inicial. Não regenere chaves nem substitua banco ou credenciais existentes para iniciar o app.

## Organização e responsabilidades

| Caminho | Responsabilidade |
|---|---|
| `smart_price_tag/web.py` | Rotas FastAPI, sessão, CSRF, renderização e endpoint autenticado de status. |
| `smart_price_tag/templates/` | Páginas Jinja2; `base.html` contém a estrutura compartilhada e `tags.html` a página de Etiquetas. |
| `smart_price_tag/static/` | CSS compartilhado e JavaScript de atualização de status. |
| `smart_price_tag/catalog.py` | Regras de produtos, etiquetas, vínculos e promoções. |
| `smart_price_tag/db.py` | Modelos SQLModel, SQLite e migrações que preservam bancos existentes. |
| `smart_price_tag/publisher.py` | Conteúdo da configuração, versão por hash, sequência, envelope persistido e histórico `publicacao` (motivo, preparada/publicada/republicada). |
| `smart_price_tag/presentation.py` | Formatação para a interface: horários de Brasília e tempo relativo, mensagem legível, HMAC agrupado, diferenças entre versões e rótulos de sinal, bateria e atraso. |
| `smart_price_tag/mqtt.py` | Conexão, assinatura de status, publicação e republicação MQTT. |
| `smart_price_tag/monitor.py` | Validação e persistência do último status recebido da etiqueta. |
| `smart_price_tag/security.py` | Derivação de chaves individuais e assinatura HMAC. |
| `smart_price_tag/authentication.py` | Administrador, autenticação e hashes de senha. |
| `smart_price_tag/config.py` | Configuração por ambiente e carregamento dos arquivos locais provisionados. |
| `smart_price_tag/broker_admin.py` | Provisionamento, contas, ACL e arquivos privados do Mosquitto. |
| `broker/` | Exemplos públicos de configuração e ACL; não colocar credenciais reais. |
| `tests/` | Testes automatizados com dados sintéticos e broker temporário. |
| `data/`, `secrets/` | Banco, configuração real do broker e segredos locais; ignorados pelo Git. |
| `.venv/` | Ambiente Python local; ignorado pelo Git. |
| `README.md` | Instalação, execução, contrato e operação. |
| `PLANO.md` | Etapas, requisitos, implementações, validações e pendências. |

## Comportamento e validação

- Preserve autenticação, CSRF e compatibilidade com bancos existentes. Não altere o contrato MQTT sem atualizar documentação e testes relevantes.
- Na página de Etiquetas, sincronização compara a versão do **último status recebido** com o hash da configuração **atual do catálogo**, mesmo antes da preparação ou publicação MQTT. Status ausente ou sem versão não confirma sincronização.
- Mantenha separado o estado de entrega MQTT, que acompanha publicação e confirmação. Um ACK do broker não comprova aplicação na etiqueta; um status não comprova o conteúdo físico do visor nem uma conexão ativa agora. A linha do tempo (Preparada → Publicada no broker → Status recebido → Aplicada pela etiqueta) é a referência da entrega; o selo do card responde só se a versão informada pela etiqueta é a do catálogo atual.
- Cada `seq` novo gera uma linha em `publicacao`; a republicação nunca muda o `seq` nem cria linha, só atualiza `republicada_em`. Ao causar uma mudança no catálogo, passe o motivo para `catalog_changed()`. Não altere o envelope MQTT nem o cálculo de HMAC, versão e `seq`.
- Exiba horários em America/Sao_Paulo (filtro `local_time` e `presentation.local_with_relative`). A interface pode mostrar `dados` e `hmac`, que já trafegam no broker, mas nunca a chave individual, a mestra ou senhas.
- Preserve o layout responsivo, navegação por teclado, foco visível e header persistente. Evite porcentagem de bateria sem uma relação validada entre tensão e carga.
- Execute testes apropriados às alterações. A partir de `web-app/`, use:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

- Para mudanças no JavaScript de status, valide a sintaxe com `node --check smart_price_tag/static/tag_status.js`. Para mudanças visuais, confira desktop e celular, expansão por teclado, rolagem e atualização dos indicadores.
- Faça testes e capturas com dados sintéticos em ambiente separado. Não use credenciais ou banco reais como fixtures. Não declare validação no hardware quando houve apenas teste de software.

## Atualização obrigatória do plano

**Ao final de toda sessão de trabalho, atualize `web-app/PLANO.md` antes de concluir ou fazer commit.** Registre o que foi implementado, as verificações realmente realizadas, os resultados e as pendências. Atualize as etapas e requisitos afetados sem marcar como concluído algo ainda não comprovado. Use `PLANO.md`, respeitando o nome existente do arquivo. Quando comandos de execução ou operação mudarem, atualize também o `README.md`.

## Cuidados com o repositório público

- Nunca versione senhas, tokens, chaves mestras ou individuais, credenciais MQTT/Wi-Fi, certificados privados, cookies de sessão, arquivos `.env`, bancos reais, dumps ou capturas que exponham esses dados.
- Mantenha dados privados em `data/`, `secrets/` ou variáveis de ambiente. Não imprima o conteúdo desses arquivos, variáveis sensíveis ou payloads de autenticação em logs, documentação, mensagens ou comandos de revisão.
- Use apenas valores claramente sintéticos nos testes e exemplos. Documente como carregar ou gerar segredos sem inserir seus valores reais.
- Confira o `.gitignore`, mas lembre que ele não protege arquivos já rastreados. Não use `git add -f` para arquivos privados e não faça staging indiscriminado.
- Antes de commit e push, revise `git status`, a lista de arquivos preparados e **todo o `git diff --cached`**, procurando dados sensíveis, artefatos locais e alterações fora do escopo. Faça staging explícito dos arquivos revisados.
- Se um segredo tiver sido exposto, não publique nem repita seu valor. Remova-o das alterações e informe a necessidade de revogação/rotação; apagar apenas o arquivo não remove um segredo já publicado do histórico Git.
