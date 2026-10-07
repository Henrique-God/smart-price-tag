# Smart Price Tag — aplicação web e MQTT

Aplicação FastAPI/Jinja2/SQLite baseada em `../main (1).pdf`. Esta entrega implementa a parte web da comunicação: configuração MQTT retida, assinatura HMAC, fila persistente no SQLite, recebimento de estados e indicação de publicação/aplicação. Uma ESP física autenticou no broker, recebeu uma configuração retida e publicou um estado inicial; a aplicação da configuração no visor e a verificação de HMAC/seq no firmware ainda não foram comprovadas. O firmware não está neste repositório.

Os módulos seguem as responsabilidades da seção 3.3.2: `web` apresenta e controla sessão; `authentication` valida administrador; `catalog` aplica regras de produto, etiqueta e promoção; `db` persiste; `publisher` monta configurações; `security` deriva chaves e assina; `mqtt` mantém a conexão e republica; `monitor` valida e grava estados.

## Instalação da aplicação

Python 3.12 ou superior. Execute a partir de `web-app/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
New-Item -ItemType Directory -Force data,secrets | Out-Null
$env:SPT_DB_PATH = "data/smart_price_tag.db"
$env:SPT_SESSION_SECRET = python -c "import secrets; print(secrets.token_urlsafe(48))"
$env:SPT_SECURE_COOKIES = "false" # só para HTTP local
python -m smart_price_tag.authentication # cria o primeiro administrador, com senha interativa
```

O comando de administrador só funciona antes da primeira conta. Em uso de rede, sirva o web app por HTTPS e use `SPT_SECURE_COOKIES=true` (por exemplo, Uvicorn com `--ssl-certfile` e `--ssl-keyfile` apontando para arquivos privados locais).

## Provisionamento pela tela MQTT

Instale o Mosquitto e execute, a partir de `web-app/`, `python -m smart_price_tag.broker_admin` uma vez. Esse comando cria sem sobrescrever os arquivos privados `data/broker/mosquitto.conf`, `data/broker/acl`, `data/broker/passwords`, `data/broker/app.json`, `secrets/master.key`, `secrets/mqtt-app-password` e `secrets/session.key`. O listener local inicial usa `127.0.0.1:1884`; ajuste IP e porta na tela MQTT antes de conectar uma ESP física. O diretório `data/` e `secrets/` são ignorados pelo Git e devem permanecer acessíveis somente ao administrador e ao processo.

No Git Bash, inicie `bash run-broker.sh` em um terminal e `bash run-local.sh` em outro. O segundo script carrega os segredos locais, desativa cookies seguros **somente para HTTP local** e inicia o Uvicorn em `127.0.0.1:8000`. Entre como administrador e abra **MQTT**. A tela prepara os arquivos caso ainda não existam, salva IP/porta do listener, cadastra uma etiqueta pelo MAC, cria uma senha exclusiva e a ACL correspondente, mostra a senha e a chave individual uma única vez, permite trocar a senha ou revogar o acesso. O listener precisa usar um IPv4 atribuído ao próprio computador; a tela sugere os endereços locais e recusa um IP externo que não possa ser usado para escuta. Reinicie o broker após mudanças de senha/ACL; reinicie broker e backend após mudar IP/porta. A tela não inicia ou encerra o processo Mosquitto.

O MAC é normalizado para 12 hexadecimais maiúsculos no cadastro. O usuário MQTT e o ID nos tópicos podem usar maiúsculas ou minúsculas, conforme o firmware; a tela MQTT mostra o formato exato, que deve ser igual nos três lugares. O monitor converte o ID recebido para maiúsculas antes de procurar a etiqueta no catálogo. O MAC é um identificador, não prova de hardware: a senha exclusiva e a ACL protegem a conexão. O firmware da ESP precisa guardar sua senha e chave individual, verificar HMAC/seq nas configurações e usar o IP/porta do broker. A conexão, a entrega da configuração e o estado inicial foram observados com uma ESP física; a verificação de HMAC/seq no firmware ainda não foi examinada. O MQTT de exemplo não usa TLS; mantenha-o em rede local confiável ou configure TLS no broker e nos clientes antes de usar rede não confiável.

Se a ESP receber `CONNACK` com código 5, confira o **usuário MQTT** exatamente como aparece na tela MQTT e a senha MQTT mais recente; o Client ID exibido no log pode ter outro formato. Na linha da etiqueta, **Usar minúsculas** ou **Usar maiúsculas** troca o nome da conta MQTT e os tópicos permitidos: a senha atual, o cadastro e a chave HMAC são mantidos. Reinicie o broker após a troca. Para verificar uma senha sem mostrá-la no comando nem no histórico do shell, rode `python -m smart_price_tag.broker_admin check-tag ID_MAC` com o broker ligado. O comando pede a senha sem eco e informa apenas se o broker a aceitou. Caso tenha perdido a senha, use **Trocar senha** na tela MQTT, atualize a ESP e reinicie o broker.

## Instalação do Mosquitto e provisionamento manual alternativo

Instale o [Mosquitto](https://mosquitto.org/download/) 2.1 ou superior. No Windows, o instalador oficial coloca `mosquitto.exe` e `mosquitto_passwd.exe` em `C:\Program Files\mosquitto\`. Em Debian/Ubuntu, instale os pacotes `mosquitto` e `mosquitto-clients` do sistema. Os exemplos abaixo são PowerShell e devem ser executados em `web-app/`. Use esta seção apenas se optar pelo provisionamento manual; os arquivos gerados pela tela já incluem senha e chave mestra.

1. Crie `data/broker/` (ignorado pelo Git), copie [`broker/mosquitto.conf.example`](broker/mosquitto.conf.example) para `data/broker/mosquitto.conf` e [`broker/acl.example`](broker/acl.example) para `data/broker/acl`. O exemplo escuta apenas em `127.0.0.1`; antes de conectar etiquetas reais, altere o `listener` para o IP da interface da LAN confiável e restrinja a porta no firewall. Não exponha a porta MQTT à internet. O arquivo de ACL contém um ID ilustrativo: substitua por etiquetas provisionadas.

2. Crie senhas únicas e longas, digitadas interativamente; a primeira opção `-c` cria o arquivo, e as próximas acrescentam usuários. O arquivo contém hashes, mas permanece privado. O usuário da aplicação é `spt-app`; o de cada etiqueta é seu identificador MAC em 12 hexadecimais, com o mesmo formato de letras configurado na ESP.

```powershell
New-Item -ItemType Directory -Force data/broker,secrets | Out-Null
if (!(Test-Path data/broker/mosquitto.conf)) { Copy-Item broker/mosquitto.conf.example data/broker/mosquitto.conf }
if (!(Test-Path data/broker/acl)) { Copy-Item broker/acl.example data/broker/acl }
if (Test-Path data/broker/passwords) { throw "Arquivo de senhas já existe; não use -c novamente." }
& "C:\Program Files\mosquitto\mosquitto_passwd.exe" -c data/broker/passwords spt-app
& "C:\Program Files\mosquitto\mosquitto_passwd.exe" data/broker/passwords A1B2C3D4E5F6
```

3. Para **cada** etiqueta, acrescente ao `data/broker/acl` um bloco `user ID`, `topic read spt/ID/config`, `topic write spt/ID/status`, usando o mesmo ID nos três lugares. A aplicação possui apenas `topic write spt/+/config` e `topic read spt/+/status`. Reinicie o broker após editar as ACLs; remova a credencial e o bloco de uma etiqueta desativada. O exemplo de ACL já inclui o ID ilustrativo acima.

4. Gere uma única chave mestra aleatória de 32 bytes e guarde-a em `secrets/master.key`, fora do Git. A derivação HMAC-SHA256 por MAC produz a chave individual; o comando abaixo grava somente a chave da etiqueta indicada em `secrets/ID.key`. Entregue essa chave e a senha MQTT correspondente ao processo privado de compilação/provisionamento daquela etiqueta. Nunca coloque a mestra no firmware nem inclua esses valores em logs, imagens públicas ou commits.

```powershell
if (Test-Path secrets/master.key) { throw "Chave mestra já existe; não a substitua." }
python -c "import secrets; print(secrets.token_hex(32))" | Set-Content secrets/master.key
$env:SPT_MQTT_MASTER_KEY = (Get-Content secrets/master.key -Raw).Trim()
python -m smart_price_tag.security A1B2C3D4E5F6
```

**Guarde e faça backup privado de `secrets/master.key`, do banco e dos arquivos do broker.** Se a chave mestra mudar, as etiquetas existentes precisarão ser reprovisionadas; configurações antigas não poderão ser verificadas com a nova chave. Proteja `data/` e `secrets/` com permissões do sistema operacional somente para o serviço e o administrador. A monografia usa MQTT sem TLS na LAN WPA2: a senha MQTT trafega em texto claro nessa rede. Use uma rede isolada e confiável; para rede não confiável, configure TLS no Mosquitto e nos clientes antes de operar. O HMAC autentica a configuração, mas não cifra o tráfego.

5. Inicie o broker em outro terminal. No primeiro terminal, configure a aplicação com a senha `spt-app` digitada sem eco e execute um único processo Uvicorn (o publicador usa um único processo dono da conexão MQTT):

O instalador Windows pode iniciar um serviço Mosquitto padrão. Se a porta 1883 já estiver em uso, pare esse serviço com privilégios de administrador antes de iniciar a instância com `data/broker/mosquitto.conf`, ou configure outra porta no broker e em `SPT_MQTT_PORT`.

```powershell
& "C:\Program Files\mosquitto\mosquitto.exe" -c data/broker/mosquitto.conf -v
```

```powershell
$env:SPT_MQTT_HOST = "127.0.0.1"
$env:SPT_MQTT_PORT = "1883"
$env:SPT_MQTT_USERNAME = "spt-app"
$secure = Read-Host "Senha MQTT da aplicação" -AsSecureString
$env:SPT_MQTT_PASSWORD = [System.Net.NetworkCredential]::new('', $secure).Password
$env:SPT_MQTT_MASTER_KEY = (Get-Content secrets/master.key -Raw).Trim()
python -m uvicorn smart_price_tag.web:create_app --factory --host 127.0.0.1 --port 8000
```

Se qualquer variável MQTT estiver definida, as quatro `SPT_MQTT_HOST`, `SPT_MQTT_USERNAME`, `SPT_MQTT_PASSWORD` e `SPT_MQTT_MASTER_KEY` são obrigatórias; `SPT_MQTT_PORT` é opcional (padrão 1883). Sem variáveis MQTT, o backend carrega os arquivos locais preparados pela tela quando eles existem; sem os dois, o catálogo continua utilizável e a interface indica MQTT não configurado. `SPT_DB_PATH`, `SPT_SESSION_SECRET` e `SPT_SECURE_COOKIES` seguem a configuração web anterior.

Após entrar como administrador, abra **MQTT** no menu para ver a conexão com o broker, as publicações pendentes e o último estado recebido de cada etiqueta. Depois do primeiro status, a situação muda para **Estado recebido · aguardando confirmação**; só muda para **Aplicada** quando a versão informada pela ESP corresponde à configuração atual. A aba **Etiquetas** apresenta um painel expansível por ESP com último contato, sinal, bateria, firmware e versões. As duas telas atualizam esses dados a cada 5 segundos enquanto estão abertas. **Republicar todas** solicita o reenvio das configurações retidas sem alterar versões ou sequências; se o broker estiver desconectado, o envio ocorre após a reconexão. Host, porta e usuário são exibidos para diagnóstico, enquanto senha e chave mestra permanecem nos arquivos privados ou nas variáveis de ambiente do processo.

## Contrato e situação exibida

- O servidor publica `spt/{id}/config` com QoS 1 e `retain=true`; `{id}` usa o mesmo formato de letras do usuário MQTT provisionado. `dados` é uma **string JSON exata**, em UTF-8; `hmac` são os primeiros 16 bytes de HMAC-SHA256 sobre essa string, em hexadecimal. A chave da etiqueta é `HMAC-SHA256(chave_mestra, ID_ASCII)` usando o ID do cadastro em maiúsculas.
- `dados` contém `produto` (ou `null`), `promocao` (ou `null`), `versao` e `seq`. Preços são inteiros em centavos; `expira_em` é Unix UTC. A versão são os 8 primeiros hexadecimais de SHA-256 do conteúdo `produto`/`promocao` serializado de forma estável. A sequência cresce a cada configuração diferente da etiqueta. Conteúdo igual mantém a versão e evita novo redesenho.
- O servidor assina `spt/+/status` e aceita JSON com `versao`, `tensao_mv`, `rssi`, `firmware` e `instante` de uma etiqueta cadastrada, usando `{id}` no formato permitido pela ACL. Uma `versao` vazia registra a comunicação sem confirmar a configuração. `instante: 0` indica relógio indisponível, e a interface usa o horário de recebimento do servidor; nesse caso não há ordenação pelo relógio da ESP. Quando o firmware dispõe de relógio, deve enviar segundos Unix válidos e crescentes; estados inválidos, muito grandes ou com instante antigo são ignorados. **“Estado recebido” indica comunicação; “Aplicada” indica que a ESP informou a versão atual.** O status ainda não inclui `seq`, e essa indicação não comprova o conteúdo exibido no visor.
- A publicação confirmada pelo broker é diferente da aplicação no visor. Enquanto o broker está fora, a nova configuração fica gravada no SQLite como publicação pendente. Na reconexão, o servidor publica a configuração mais recente como retida; na inicialização também a republica para recuperar eventual perda dos dados retidos pelo broker. Mantenha `persistence true` no broker.

Os IDs seguem os Quadros 1 e 2 da monografia, inclusive RNF09 (login obrigatório no broker), RNF10 (ACL por etiqueta) e RNF12 (rejeição de configuração falsa/antiga pelo **futuro firmware**). Remissões posteriores da monografia trocam alguns números.

## Testes e sigilo

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Os testes de integração usam Mosquitto local quando os executáveis estão no `PATH` ou em `C:\Program Files\mosquitto\`; caso contrário, esse teste é pulado. Eles sobem um broker temporário, verificam senha/ACL, mensagem retida, estado de teste, publicação após queda/reconexão e recusa de publicação no ACK MQTT 5. Além dos testes sintéticos, observou-se com uma ESP física a autenticação, a entrega da configuração retida e a chegada de um status inicial com `versao` vazia e `instante` zero. RF04/RF06 ainda precisam de confirmação da aplicação no visor; RNF12 ainda precisa de validação no firmware.

O repositório é público. O [`.gitignore`](../.gitignore) protege `.env*`, `data/`, `secrets/`, certificados e bancos locais; não faça commit de senhas, chaves, Wi-Fi, certificados privados ou bancos reais. Revise `git diff --cached` antes de qualquer commit. Veja [PLANO.md](PLANO.md) para a matriz de requisitos.
