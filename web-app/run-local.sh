#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f secrets/session.key ]]; then
  .venv/Scripts/python.exe -m smart_price_tag.broker_admin
fi

export SPT_SESSION_SECRET="$(tr -d '\r\n' < secrets/session.key)"
export SPT_SECURE_COOKIES=false
export SPT_DB_PATH=data/smart_price_tag.db
unset SPT_MQTT_HOST SPT_MQTT_PORT SPT_MQTT_USERNAME SPT_MQTT_PASSWORD SPT_MQTT_MASTER_KEY
exec .venv/Scripts/python.exe -m uvicorn smart_price_tag.web:create_app --factory --host 127.0.0.1 --port 8000
