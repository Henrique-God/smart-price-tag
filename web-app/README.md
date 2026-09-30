# Smart Price Tag — aplicação web e MQTT

Aplicação FastAPI/Jinja2/SQLite baseada em `../main (1).pdf`. Esta entrega implementa a parte web da comunicação: configuração MQTT retida, autenticação HMAC, fila persistente no SQLite, recebimento de estados e indicação de publicação/aplicação. **Nenhum firmware ou visor real foi validado.** A futura pasta `firmware/` fica ao lado de `web-app/`.

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

## Instalação do Mosquitto e provisionamento

Instale o [Mosquitto](https://mosquitto.org/download/) 2.1 ou superior. No Windows, o instalador oficial coloca `mosquitto.exe` e `mosquitto_passwd.exe` em `C:\Program Files\mosquitto\`. Em Debian/Ubuntu, instale os pacotes `mosquitto` e `mosquitto-clients` do sistema. Os exemplos abaixo são PowerShell e devem ser executados em `web-app/`.

1. Crie `data/broker/` (ignorado pelo Git), copie [`broker/mosquitto.conf.example`](broker/mosquitto.conf.example) para `data/broker/mosquitto.conf` e [`broker/acl.example`](broker/acl.example) para `data/broker/acl`. O exemplo escuta apenas em `127.0.0.1`; antes de conectar etiquetas reais, altere o `listener` para o IP da interface da LAN confiável e restrinja a porta no firewall. Não exponha a porta MQTT à internet. O arquivo de ACL contém um ID ilustrativo: substitua por etiquetas provisionadas.

2. Crie senhas únicas e longas, digitadas interativamente; a primeira opção `-c` cria o arquivo, e as próximas acrescentam usuários. O arquivo contém hashes, mas permanece privado. O usuário da aplicação é `spt-app`; o de cada etiqueta é exatamente seu identificador MAC em 12 hexadecimais maiúsculos.

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

Se qualquer variável MQTT estiver definida, as quatro `SPT_MQTT_HOST`, `SPT_MQTT_USERNAME`, `SPT_MQTT_PASSWORD` e `SPT_MQTT_MASTER_KEY` são obrigatórias; `SPT_MQTT_PORT` é opcional (padrão 1883). Sem elas, o catálogo continua utilizável e a interface indica MQTT não configurado. `SPT_DB_PATH`, `SPT_SESSION_SECRET` e `SPT_SECURE_COOKIES` seguem a configuração web anterior.

## Contrato e situação exibida

- O servidor publica `spt/{id}/config` com QoS 1 e `retain=true`. `dados` é uma **string JSON exata**, em UTF-8; `hmac` são os primeiros 16 bytes de HMAC-SHA256 sobre essa string, em hexadecimal. A chave da etiqueta é `HMAC-SHA256(chave_mestra, ID_ASCII)`.
- `dados` contém `produto` (ou `null`), `promocao` (ou `null`), `versao` e `seq`. Preços são inteiros em centavos; `expira_em` é Unix UTC. A versão são os 8 primeiros hexadecimais de SHA-256 do conteúdo `produto`/`promocao` serializado de forma estável. A sequência cresce a cada configuração diferente da etiqueta. Conteúdo igual mantém a versão e evita novo redesenho.
- O servidor assina `spt/+/status` e aceita JSON com `versao`, `tensao_mv`, `rssi`, `firmware` e `instante` de uma etiqueta cadastrada. Estados inválidos, muito grandes ou com instante antigo são ignorados. A interface preserva a última versão informada; **“Aplicada” só aparece após um estado recebido para a sequência atual, com versão igual à configuração publicada mais recente**.
- A publicação confirmada pelo broker é diferente da aplicação no visor. Enquanto o broker está fora, a nova configuração fica gravada no SQLite como publicação pendente. Na reconexão, o servidor publica a configuração mais recente como retida; na inicialização também a republica para recuperar eventual perda dos dados retidos pelo broker. Mantenha `persistence true` no broker.

Os IDs seguem os Quadros 1 e 2 da monografia, inclusive RNF09 (login obrigatório no broker), RNF10 (ACL por etiqueta) e RNF12 (rejeição de configuração falsa/antiga pelo **futuro firmware**). Remissões posteriores da monografia trocam alguns números.

## Testes e sigilo

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Os testes de integração usam Mosquitto local quando os executáveis estão no `PATH` ou em `C:\Program Files\mosquitto\`; caso contrário, esse teste é pulado. Eles sobem um broker temporário, verificam senha/ACL, mensagem retida, estado de teste, publicação após queda/reconexão e recusa de publicação no ACK MQTT 5. O estado de teste é uma **mensagem sintética isolada**, não uma confirmação de hardware. A validação RF04/RF06 com etiqueta física e a RNF12 continuam pendentes.

O repositório é público. O [`.gitignore`](../.gitignore) protege `.env*`, `data/`, `secrets/`, certificados e bancos locais; não faça commit de senhas, chaves, Wi-Fi, certificados privados ou bancos reais. Revise `git diff --cached` antes de qualquer commit. Veja [PLANO.md](PLANO.md) para a matriz de requisitos.
