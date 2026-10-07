#!/usr/bin/env python3
"""Ferramenta de teste do contrato do Smart Price Tag (ver CONTRATO.md).

Faz o papel da aplicação de gerenciamento enquanto ela não está pronta:
publica configurações assinadas no broker, limpa a mensagem retida e
mostra os estados que a etiqueta publica. Também deriva a chave HMAC de
uma etiqueta para o include/secrets.h do firmware.

Requer Python 3.9+ e, para os comandos que falam com o broker:
    pip install paho-mqtt

Comandos (rode com -h em cada um para ver as opções):
    conferir   recalcula os vetores de teste do CONTRATO.md (não usa rede)
    chave      deriva a chave da etiqueta a partir da chave-mestra
    publicar   publica uma configuração (vetor do contrato ou produto próprio)
    limpar     apaga a configuração retida de uma etiqueta
    escutar    mostra os estados publicados pelas etiquetas

Exemplos:
    python tools/publicar_config.py conferir
    python tools/publicar_config.py chave --id a4cf12ab34cd
    python tools/publicar_config.py publicar --host 192.168.43.10 --senha app123 \\
        --id a4cf12ab34cd --nome "Dipirona 500 mg" --preco 1490 \\
        --descricao "caixa com 20 comprimidos" --ean13 7891234567895 \\
        --promo-preco 1190 --promo-minutos 5
    python tools/publicar_config.py publicar --host 192.168.43.10 --senha app123 \\
        --id a1b2c3d4e5f6 --vetor V4
    python tools/publicar_config.py escutar --host 192.168.43.10 --senha app123

A chave-mestra vem de --chave-mestra ou da variável de ambiente SPT_CHAVE_MESTRA
(64 caracteres hex). Sem nenhuma das duas, é usada a chave de TESTE do contrato,
que nunca deve ser usada na demonstração.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time

# Valores do CONTRATO.md (seções 5, 6 e 9).
TEST_MASTER_KEY_HEX = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
TEST_TAG_ID = "a1b2c3d4e5f6"
OTHER_TAG_ID = "ffffffffffff"
MAX_MESSAGE_BYTES = 512
MAX_NAME_CHARS = 20
MAX_DESCRIPTION_CHARS = 30
MAX_PRICE_CENTS = 99999
MAX_SEQ = 2**31 - 1

TEST_PRODUCT = {
    "nome": "Dipirona 500 mg",
    "preco": 1490,
    "descricao": "caixa com 20 comprimidos",
    "ean13": "7891234567895",
}
TEST_PROMOTION = {"preco": 1190, "expira_em": 1795680000}
TEST_PRODUCT_2 = {
    "nome": "Café Pilão 500 g",
    "preco": 2490,
    "descricao": "torrado e moído",
    "ean13": "7896089012453",
}

# Resultado esperado de cada vetor (seção 9 do contrato).
EXPECTED_TAG_KEY_HEX = "d4c08c076e44144313962c8344e2629ea372ae885e07f354e1bd0cd8523fe573"
EXPECTED_HMAC = {
    "V1": "9bb4c082b6209aa642ccf1652b2a5397",
    "V2": "4f8f7929e872ef07e6a85fba574771ef",
    "V3": "d9e4ebd4a9acd35286ddeef317dabc8a",
    "V4": "9bb4c082b6209aa642ccf1652b2a5397",
    "V5": "829fa9736b1d7049bbe52de46f0c6dc3",
    "V6": "2aa16b0291bb89d50167c2ab381e9421",
}
VECTOR_DESCRIPTION = {
    "V1": "produto com promoção, seq 42 (aceita)",
    "V2": "produto com acentos, sem promoção, seq 43 (aceita)",
    "V3": "etiqueta sem produto, seq 44 (aceita; visor limpo)",
    "V4": "V1 com preço adulterado e o mesmo hmac (rejeitada: hmac)",
    "V5": "V1 com seq 41 (rejeitada se a última aceita for >= 42)",
    "V6": "V1 assinada com a chave de outra etiqueta (rejeitada: hmac)",
}


# ---------------------------------------------------------------- contrato

def tag_key(master_key: bytes, tag_id: str) -> bytes:
    """chave_etiqueta = HMAC-SHA256(chave_mestra, id em ASCII)."""
    return hmac.new(master_key, tag_id.encode("ascii"), hashlib.sha256).digest()


def compute_version(product: dict | None, promotion: dict | None) -> str:
    """8 primeiros hex do SHA-256 da serialização canônica de produto + promoção."""
    canonical = json.dumps({"produto": product, "promocao": promotion}, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def build_data(product: dict | None, promotion: dict | None, seq: int) -> str:
    """Texto de `dados`, compacto e em UTF-8 (ordem de campos fixa)."""
    data = {"produto": product, "promocao": promotion,
            "versao": compute_version(product, promotion), "seq": seq}
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def compute_hmac(key: bytes, data: str) -> str:
    """HMAC-SHA256 sobre os bytes UTF-8 de `dados`, truncado em 32 hex."""
    return hmac.new(key, data.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def build_envelope(data: str, mac: str) -> str:
    return json.dumps({"dados": data, "hmac": mac}, separators=(",", ":"), ensure_ascii=False)


def ean13_valid(code: str) -> bool:
    if len(code) != 13 or not code.isdigit():
        return False
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(code[:12]))
    return (10 - total % 10) % 10 == int(code[12])


def validate(product: dict | None, promotion: dict | None, seq: int) -> list[str]:
    """Regras da seção 5 do contrato. Retorna a lista de violações."""
    errors = []
    if not 1 <= seq <= MAX_SEQ:
        errors.append(f"seq deve estar entre 1 e {MAX_SEQ}")
    if product is None:
        if promotion is not None:
            errors.append("promoção sem produto")
        return errors
    if not 1 <= len(product["nome"]) <= MAX_NAME_CHARS:
        errors.append(f"nome deve ter de 1 a {MAX_NAME_CHARS} caracteres")
    if len(product["descricao"]) > MAX_DESCRIPTION_CHARS:
        errors.append(f"descrição deve ter no máximo {MAX_DESCRIPTION_CHARS} caracteres")
    if not 1 <= product["preco"] <= MAX_PRICE_CENTS:
        errors.append(f"preço deve estar entre 1 e {MAX_PRICE_CENTS} centavos")
    if not ean13_valid(product["ean13"]):
        errors.append("ean13 inválido (13 dígitos com dígito verificador correto)")
    if promotion is not None:
        if not 0 < promotion["preco"] < product["preco"]:
            errors.append("preço promocional deve ser maior que 0 e menor que o preço")
        if promotion["expira_em"] <= 0:
            errors.append("expira_em deve ser um instante UTC em segundos")
    return errors


def vector(name: str, master_key: bytes) -> tuple[str, str, str]:
    """Monta um vetor do contrato. Retorna (id da etiqueta, dados, hmac)."""
    key = tag_key(master_key, TEST_TAG_ID)
    if name == "V1":
        data = build_data(TEST_PRODUCT, TEST_PROMOTION, 42)
        return TEST_TAG_ID, data, compute_hmac(key, data)
    if name == "V2":
        data = build_data(TEST_PRODUCT_2, None, 43)
        return TEST_TAG_ID, data, compute_hmac(key, data)
    if name == "V3":
        data = build_data(None, None, 44)
        return TEST_TAG_ID, data, compute_hmac(key, data)
    if name == "V4":
        _, v1, v1_mac = vector("V1", master_key)
        return TEST_TAG_ID, v1.replace('"preco":1490', '"preco":990', 1), v1_mac
    if name == "V5":
        data = build_data(TEST_PRODUCT, TEST_PROMOTION, 41)
        return TEST_TAG_ID, data, compute_hmac(key, data)
    if name == "V6":
        _, v1, _ = vector("V1", master_key)
        return TEST_TAG_ID, v1, compute_hmac(tag_key(master_key, OTHER_TAG_ID), v1)
    raise ValueError(f"vetor desconhecido: {name}")


# ---------------------------------------------------------------- comandos

def load_master_key(arg_value: str | None) -> tuple[bytes, bool]:
    """Retorna (chave, é_a_chave_de_teste)."""
    value = arg_value or os.environ.get("SPT_CHAVE_MESTRA")
    if not value:
        return bytes.fromhex(TEST_MASTER_KEY_HEX), True
    value = value.strip().lower()
    if len(value) != 64:
        sys.exit("erro: a chave-mestra deve ter 64 caracteres hex (32 bytes)")
    try:
        return bytes.fromhex(value), value == TEST_MASTER_KEY_HEX
    except ValueError:
        sys.exit("erro: a chave-mestra deve conter só caracteres hex")


def check_tag_id(tag_id: str) -> str:
    tag_id = tag_id.strip().lower().replace(":", "")
    if len(tag_id) != 12 or any(c not in "0123456789abcdef" for c in tag_id):
        sys.exit("erro: o id da etiqueta são 12 caracteres hex (o MAC sem ':'), ex.: a4cf12ab34cd")
    return tag_id


def cmd_conferir(_args) -> int:
    master = bytes.fromhex(TEST_MASTER_KEY_HEX)
    failures = 0
    key_hex = tag_key(master, TEST_TAG_ID).hex()
    ok = key_hex == EXPECTED_TAG_KEY_HEX
    failures += not ok
    print(f"{'OK ' if ok else 'ERRO'} chave da etiqueta {TEST_TAG_ID}: {key_hex}")
    for name in EXPECTED_HMAC:
        _, data, mac = vector(name, master)
        ok = mac == EXPECTED_HMAC[name]
        failures += not ok
        size = len(build_envelope(data, mac).encode("utf-8"))
        print(f"{'OK ' if ok else 'ERRO'} {name} hmac={mac} ({size} bytes) - {VECTOR_DESCRIPTION[name]}")
    print("todos os vetores conferem com o CONTRATO.md" if failures == 0
          else f"{failures} divergência(s) com o CONTRATO.md")
    return 1 if failures else 0


def cmd_chave(args) -> int:
    master, is_test = load_master_key(args.chave_mestra)
    tag_id = check_tag_id(args.id)
    if is_test:
        print("aviso: usando a chave-mestra de TESTE do contrato", file=sys.stderr)
    print(f'#define TAG_HMAC_KEY_HEX "{tag_key(master, tag_id).hex()}"')
    return 0


def mqtt_client(args, client_id: str):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        sys.exit("erro: instale o cliente MQTT com:  pip install paho-mqtt")
    if hasattr(mqtt, "CallbackAPIVersion"):  # paho-mqtt 2.x
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    else:  # paho-mqtt 1.x
        client = mqtt.Client(client_id=client_id)
    client.username_pw_set(args.usuario, args.senha)
    return client


def connect(client, args) -> None:
    try:
        client.connect(args.host, args.porta, keepalive=30)
    except OSError as exc:
        sys.exit(f"erro: não foi possível conectar a {args.host}:{args.porta} ({exc}). "
                 "Confira o IP do broker, o 'listener 1883' no mosquitto.conf e o firewall.")


def publish_retained(args, topic: str, payload: bytes) -> None:
    client = mqtt_client(args, f"spt-ferramenta-{os.getpid()}")
    connect(client, args)
    client.loop_start()
    info = client.publish(topic, payload, qos=1, retain=True)
    try:
        info.wait_for_publish(timeout=10)
    except (RuntimeError, ValueError) as exc:
        client.loop_stop()
        sys.exit(f"erro: publicação falhou ({exc}); confira usuário, senha e ACL do broker")
    client.disconnect()
    client.loop_stop()
    if not info.is_published():
        sys.exit("erro: o broker não confirmou a publicação; confira usuário, senha e ACL")


def cmd_publicar(args) -> int:
    master, is_test = load_master_key(args.chave_mestra)

    if args.vetor:
        if not is_test:
            sys.exit("erro: os vetores usam a chave-mestra de TESTE; não passe --chave-mestra com --vetor")
        tag_id, data, mac = vector(args.vetor, master)
        if args.id and check_tag_id(args.id) != TEST_TAG_ID:
            sys.exit(f"erro: os vetores são da etiqueta {TEST_TAG_ID}. Para testar na sua placa, "
                     f"grave no secrets.h a chave de teste ({EXPECTED_TAG_KEY_HEX}) e publique com --id {TEST_TAG_ID}, "
                     "ou monte um produto próprio sem --vetor")
        print(f"vetor {args.vetor}: {VECTOR_DESCRIPTION[args.vetor]}")
    else:
        if not args.id:
            sys.exit("erro: informe --id")
        tag_id = check_tag_id(args.id)
        if args.sem_produto:
            product, promotion = None, None
        else:
            missing = [n for n in ("nome", "preco", "ean13") if getattr(args, n) is None]
            if missing:
                sys.exit(f"erro: faltam {', '.join('--' + n for n in missing)} (ou use --sem-produto)")
            product = {"nome": args.nome, "preco": args.preco,
                       "descricao": args.descricao or "", "ean13": args.ean13}
            promotion = None
            if args.promo_preco is not None:
                if args.promo_expira is not None:
                    expires = args.promo_expira
                elif args.promo_minutos is not None:
                    expires = int(time.time()) + args.promo_minutos * 60
                else:
                    sys.exit("erro: com --promo-preco, informe --promo-minutos ou --promo-expira")
                promotion = {"preco": args.promo_preco, "expira_em": expires}
        # seq padrão: instante atual, que só cresce entre execuções (ver CONTRATO.md, seção 6)
        seq = args.seq if args.seq is not None else int(time.time())
        errors = validate(product, promotion, seq)
        if errors:
            sys.exit("erro: configuração fora do contrato:\n  - " + "\n  - ".join(errors))
        data = build_data(product, promotion, seq)
        mac = compute_hmac(tag_key(master, tag_id), data)
        if is_test:
            print("aviso: assinando com a chave-mestra de TESTE do contrato", file=sys.stderr)

    envelope = build_envelope(data, mac)
    size = len(envelope.encode("utf-8"))
    if size > MAX_MESSAGE_BYTES:
        sys.exit(f"erro: mensagem com {size} bytes, acima do limite de {MAX_MESSAGE_BYTES}")

    topic = f"spt/{tag_id}/config"
    print(f"tópico:  {topic} (retida, QoS 1)")
    print(f"dados:   {data}")
    print(f"hmac:    {mac}")
    print(f"tamanho: {size} bytes")
    if args.mostrar:
        print("(--mostrar: nada foi publicado)")
        return 0
    if not args.host or not args.senha:
        sys.exit("erro: para publicar, informe --host e --senha (ou use --mostrar)")
    publish_retained(args, topic, envelope.encode("utf-8"))
    print("publicado. A etiqueta aplica no próximo despertar (ou aperte o botão).")
    return 0


def cmd_limpar(args) -> int:
    tag_id = check_tag_id(args.id)
    topic = f"spt/{tag_id}/config"
    # Mensagem retida vazia = o broker apaga a retida do tópico.
    publish_retained(args, topic, b"")
    print(f"configuração retida de {topic} apagada")
    return 0


def cmd_escutar(args) -> int:
    client = mqtt_client(args, f"spt-escuta-{os.getpid()}")
    topic = f"spt/{check_tag_id(args.id)}/#" if args.id else "spt/#"

    def on_connect(cl, _userdata, _flags, reason_code, _properties=None):
        if reason_code != 0 and str(reason_code) != "Success":
            print(f"conexão recusada: {reason_code}")
            return
        cl.subscribe(topic, qos=0)
        print(f"escutando {topic} (Ctrl+C para sair)")

    def on_message(_cl, _userdata, msg):
        stamp = time.strftime("%H:%M:%S")
        retained = " [retida]" if msg.retain else ""
        try:
            body = json.loads(msg.payload.decode("utf-8")) if msg.payload else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            print(f"{stamp} {msg.topic}{retained}: (não é JSON) {msg.payload!r}")
            return
        if body is None:
            print(f"{stamp} {msg.topic}{retained}: (vazia)")
            return
        if msg.topic.endswith("/status") and isinstance(body, dict):
            instant = body.get("instante", 0)
            when = (time.strftime("%d/%m %H:%M:%S", time.localtime(instant))
                    if instant else "relógio não sincronizado")
            print(f"{stamp} {msg.topic}: versao={body.get('versao')!r} "
                  f"tensao={body.get('tensao_mv')} mV rssi={body.get('rssi')} dBm "
                  f"fw={body.get('firmware')} instante={when}")
        else:
            print(f"{stamp} {msg.topic}{retained}: {json.dumps(body, ensure_ascii=False)}")

    client.on_connect = on_connect
    client.on_message = on_message
    connect(client, args)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        client.disconnect()
    return 0


# ---------------------------------------------------------------- CLI

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="comando", required=True)

    def broker_args(p, required=True):
        p.add_argument("--host", required=required, help="IP do computador que roda o Mosquitto")
        p.add_argument("--porta", type=int, default=1883)
        p.add_argument("--usuario", default="aplicacao", help="usuário MQTT (padrão: aplicacao)")
        p.add_argument("--senha", required=required, help="senha MQTT desse usuário")

    sub.add_parser("conferir", help="recalcula os vetores do CONTRATO.md")

    p = sub.add_parser("chave", help="deriva a chave da etiqueta para o secrets.h")
    p.add_argument("--id", required=True, help="id da etiqueta (MAC sem ':')")
    p.add_argument("--chave-mestra", help="64 hex; padrão: SPT_CHAVE_MESTRA ou a de teste")

    p = sub.add_parser("publicar", help="publica uma configuração retida")
    broker_args(p, required=False)  # --mostrar dispensa o broker
    p.add_argument("--id", help="id da etiqueta (MAC sem ':')")
    p.add_argument("--chave-mestra", help="64 hex; padrão: SPT_CHAVE_MESTRA ou a de teste")
    p.add_argument("--vetor", choices=sorted(EXPECTED_HMAC), help="publica um vetor do contrato")
    p.add_argument("--nome")
    p.add_argument("--preco", type=int, help="em centavos (14,90 => 1490)")
    p.add_argument("--descricao", default="")
    p.add_argument("--ean13")
    p.add_argument("--promo-preco", type=int, help="em centavos")
    p.add_argument("--promo-minutos", type=int, help="a promoção termina daqui a N minutos")
    p.add_argument("--promo-expira", type=int, help="instante de término, UTC em segundos")
    p.add_argument("--sem-produto", action="store_true", help="publica produto nulo (limpa o visor)")
    p.add_argument("--seq", type=int, help="padrão: instante atual em segundos")
    p.add_argument("--mostrar", action="store_true", help="só mostra a mensagem, sem publicar")

    p = sub.add_parser("limpar", help="apaga a configuração retida de uma etiqueta")
    broker_args(p)
    p.add_argument("--id", required=True)

    p = sub.add_parser("escutar", help="mostra configurações e estados publicados")
    broker_args(p)
    p.add_argument("--id", help="só esta etiqueta (padrão: todas)")

    args = parser.parse_args()
    handlers = {"conferir": cmd_conferir, "chave": cmd_chave, "publicar": cmd_publicar,
                "limpar": cmd_limpar, "escutar": cmd_escutar}
    return handlers[args.comando](args)


if __name__ == "__main__":
    sys.exit(main())
