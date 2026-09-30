# Smart Price Tag — primeira etapa

Aplicação web de gerenciamento baseada na arquitetura de `../main (1).pdf`: Python, FastAPI, páginas Jinja2, Uvicorn, SQLModel e SQLite. Esta entrega cobre login, produtos, etiquetas, vínculos e promoções. Alterações são persistidas **somente no catálogo local**; ainda não há MQTT, confirmação do visor ou telemetria.

Os nomes internos do código, inclusive os módulos `authentication` e `catalog`, estão em inglês. O esquema SQLite existente é preservado. Textos da interface e mensagens de validação permanecem em português.

## Organização do repositório e arquitetura

```text
smart-price-tag/
├── .gitignore                 # proteção para todo o repositório
├── main (1).pdf              # referência da monografia
├── web-app/                  # aplicação web, documentação e testes desta etapa
│   ├── README.md
│   ├── PLANO.md
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── smart_price_tag/      # código Python, templates e CSS
│   ├── tests/
│   ├── data/                 # banco local, ignorado pelo Git
│   └── .venv/                # ambiente local, ignorado pelo Git
└── firmware/                 # futuro código executado no ESP32; ainda não existe
```

Todo código, dependência, teste e documentação da aplicação web deve permanecer em `web-app/`. O futuro código do ESP32 deve ficar em `firmware/`, como pasta irmã. Não recrie a antiga pasta `frontend/`.

A interface e o servidor estão separados por responsabilidade dentro de **uma única aplicação**, conforme a monografia. A interface usa `smart_price_tag/templates/` (HTML/Jinja2) e `smart_price_tag/static/` (CSS). No servidor, `web.py` cuida das rotas, sessões e renderização; `authentication.py` cuida das credenciais; `catalog.py` aplica as regras do catálogo; e `db.py` define a persistência SQLite. O Uvicorn executa a aplicação FastAPI. Não há frontend separado nem serviço React.

## Instalação local (PowerShell)

Requer Python 3.12 ou superior. A partir da raiz `smart-price-tag`, entre em `web-app` antes de instalar ou executar:

```powershell
cd .\web-app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Defina um caminho para o banco e uma chave aleatória de sessão. A chave deve ter pelo menos 32 caracteres e permanecer fora do repositório. O comando abaixo gera uma chave nova para este terminal:

```powershell
$env:SPT_DB_PATH = "data/smart_price_tag.db"
$env:SPT_SESSION_SECRET = python -c "import secrets; print(secrets.token_urlsafe(48))"
$env:SPT_SECURE_COOKIES = "false"  # somente para HTTP local
```

Crie o primeiro administrador **uma única vez**, digitando a senha interativamente. A senha deve ter no mínimo 12 caracteres e no máximo 72 bytes UTF-8. Não há senha padrão nem endpoint web de cadastro administrativo:

```powershell
python -m smart_price_tag.authentication
```

Inicie a aplicação:

```powershell
python -m uvicorn smart_price_tag.web:create_app --factory --host 127.0.0.1 --port 8000
```

Acesse `http://127.0.0.1:8000/login`. O banco é criado automaticamente no caminho de `SPT_DB_PATH` e permanece entre execuções. Se o caminho não for definido, usa `data/smart_price_tag.db`.

## Configuração e segurança

| Variável | Função | Padrão |
|---|---|---|
| `SPT_DB_PATH` | Caminho do arquivo SQLite | `data/smart_price_tag.db` |
| `SPT_SESSION_SECRET` | Assina o cookie de sessão; mínimo 32 caracteres | Obrigatória para o servidor |
| `SPT_SECURE_COOKIES` | `true` exige HTTPS no cookie; `false` permite HTTP local | `true` |

Em rede ou produção, sirva a aplicação por HTTPS, mantenha `SPT_SECURE_COOKIES=true`, proteja a chave de sessão e o arquivo SQLite e use um certificado confiável para os clientes. O acesso local via HTTP acima é apenas para desenvolvimento. O navegador recebe um cookie de sessão assinado, `HttpOnly` e `SameSite=Strict`; os formulários de alteração e de login têm token CSRF. O comando inicial se recusa a criar outra conta após a primeira.

Para executar o Uvicorn com um certificado e uma chave TLS já gerados (por exemplo, com `mkcert` para uma demonstração local), use:

```powershell
$env:SPT_SECURE_COOKIES = "true"
python -m uvicorn smart_price_tag.web:create_app --factory --host 127.0.0.1 --port 8000 --ssl-certfile certs/localhost.pem --ssl-keyfile certs/localhost-key.pem
```

O certificado e a chave privada devem ficar fora do controle de versão. Configure o nome/host do certificado de acordo com o endereço usado no navegador.

### Regra para agentes e colaboradores: repositório público

**Nunca adicione nem faça commit de arquivos ou valores sigilosos.** Isso inclui senhas, tokens, chaves de sessão/MQTT, certificados privados, credenciais Wi-Fi, arquivos `.env*`, bancos SQLite e dados reais de clientes. Use variáveis de ambiente e arquivos locais ignorados pelo `.gitignore` da raiz. A regra vale para `web-app/` e para a futura pasta `firmware/`; antes de qualquer commit, confira os arquivos preparados com `git diff --cached --name-only` e revise seu conteúdo com `git diff --cached`.

O `.gitignore` cobre `.venv/`, `data/`, bancos SQLite, `.env*`, `certs/` e formatos comuns de chaves e credenciais. Ele não substitui a revisão do que será versionado.

As datas de promoção são inseridas e exibidas **em UTC**. Preços são armazenados em centavos inteiros. O identificador da etiqueta é um MAC de 12 dígitos hexadecimais, normalizado sem separadores. A exclusão de produto vinculado requer desvincular antes.

## Testes

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Os testes usam bancos SQLite temporários e verificam autenticação, proteção de rotas e formulários, validação e operações de catálogo. Eles não exigem broker nem hardware. Consulte [PLANO.md](PLANO.md) para a matriz completa de requisitos e os TODOs.
