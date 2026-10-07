#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f data/broker/mosquitto.conf ]]; then
  .venv/Scripts/python.exe -m smart_price_tag.broker_admin
fi

exec "/c/Program Files/mosquitto/mosquitto.exe" -c data/broker/mosquitto.conf -v
