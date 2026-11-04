#!/usr/bin/env bash
# Equivalente de run-local.sh para macOS (e Linux).
# Sobe o web app em http://127.0.0.1:8000 (ou na porta de SPT_PORT).
#
# Na primeira execução, o script:
#   - cria um venv em ~/.venvs/spt (ou em SPT_VENV) e instala requirements.txt;
#   - gera os segredos locais em secrets/ (via broker_admin, se o Mosquitto
#     estiver instalado; senão, só a chave de sessão);
#   - pede login e senha do primeiro administrador.
# O venv fica fora do repositório para não ser sincronizado pelo iCloud/Drive.
set -euo pipefail
cd "$(dirname "$0")"

VENV="${SPT_VENV:-$HOME/.venvs/spt}"
PY="$VENV/bin/python"
PORT="${SPT_PORT:-8000}"

# 1. Ambiente virtual (Python 3.12+)
is_py312() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; }

find_python() {
  local candidate
  if [[ -n "${SPT_PYTHON:-}" ]]; then echo "$SPT_PYTHON"; return; fi
  for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && is_py312 "$candidate"; then
      command -v "$candidate"; return
    fi
  done
  if command -v pyenv >/dev/null 2>&1; then
    for candidate in $(pyenv versions --bare 2>/dev/null | grep -E '^3\.(1[2-9]|[2-9][0-9])' | sort -t. -k1,1n -k2,2n -k3,3n -r); do
      if is_py312 "$(pyenv root)/versions/$candidate/bin/python"; then
        echo "$(pyenv root)/versions/$candidate/bin/python"; return
      fi
    done
  fi
  return 1
}

if [[ -x "$PY" ]] && ! is_py312 "$PY"; then
  echo "O venv em $VENV usa Python < 3.12. Apague-o (rm -rf \"$VENV\") e rode de novo." >&2
  exit 1
fi

if [[ ! -x "$PY" ]]; then
  if ! BASE_PY="$(find_python)"; then
    echo "Python 3.12 ou superior não encontrado." >&2
    echo "Instale com: pyenv install 3.12   (ou: brew install python@3.12)" >&2
    exit 1
  fi
  echo "Criando ambiente virtual em $VENV com $("$BASE_PY" --version) ..."
  "$BASE_PY" -m venv "$VENV"
fi

# Reinstala as dependências quando requirements.txt muda.
STAMP="$VENV/.spt-requirements"
if [[ ! -f "$STAMP" || requirements.txt -nt "$STAMP" ]]; then
  echo "Instalando dependências ..."
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r requirements.txt
  touch "$STAMP"
fi

# 2. Segredos locais (data/ e secrets/ estão no .gitignore)
# O broker_admin não sobrescreve arquivos existentes; roda sempre que o
# Mosquitto está instalado e o broker ainda não foi provisionado.
if command -v mosquitto_passwd >/dev/null 2>&1; then
  if [[ ! -f data/broker/mosquitto.conf || ! -f secrets/session.key ]]; then
    "$PY" -m smart_price_tag.broker_admin
  fi
elif [[ ! -f secrets/session.key ]]; then
  echo "Mosquitto não encontrado: gerando só a chave de sessão (o MQTT fica desativado)."
  echo "Para usar o broker depois: brew install mosquitto e rode este script de novo."
  (umask 077; mkdir -p data secrets)
  (umask 077; "$PY" -c 'import secrets; print(secrets.token_urlsafe(48))' > secrets/session.key)
fi

export SPT_SESSION_SECRET="$(tr -d '\r\n' < secrets/session.key)"
export SPT_SECURE_COOKIES=false
export SPT_DB_PATH=data/smart_price_tag.db
unset SPT_MQTT_HOST SPT_MQTT_PORT SPT_MQTT_USERNAME SPT_MQTT_PASSWORD SPT_MQTT_MASTER_KEY

# 3. Primeiro administrador
if ! "$PY" - <<'PYEOF'
import os, sys
from pathlib import Path
from sqlmodel import Session, select
from smart_price_tag.db import create_tables, make_engine
from smart_price_tag.authentication import AdminUser

engine = make_engine(Path(os.environ["SPT_DB_PATH"]))
create_tables(engine)
with Session(engine) as session:
    sys.exit(0 if session.exec(select(AdminUser.id)).first() is not None else 1)
PYEOF
then
  echo "Nenhum administrador cadastrado. Crie o primeiro agora:"
  "$PY" -m smart_price_tag.authentication
fi

# 4. Aviso sobre o broker
if [[ -f data/broker/mosquitto.conf ]]; then
  echo "Broker provisionado. Para falar com as etiquetas, rode em outro terminal:"
  echo "  \"\$(brew --prefix)/sbin/mosquitto\" -c data/broker/mosquitto.conf -v"
fi

echo "Abrindo em http://127.0.0.1:$PORT (Ctrl+C encerra)"
exec "$PY" -m uvicorn smart_price_tag.web:create_app --factory --host 127.0.0.1 --port "$PORT"
