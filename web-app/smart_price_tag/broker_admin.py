"""Local Mosquitto provisioning for the authenticated administration UI."""

import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
from pathlib import Path

from .catalog import validate_identifier
from .security import derive_tag_key


class BrokerError(ValueError):
    pass


class BrokerManager:
    def __init__(self, root: Path | None = None):
        self.root = (root or Path(__file__).resolve().parent.parent).resolve()
        self.broker_dir = self.root / "data" / "broker"
        self.secrets_dir = self.root / "secrets"
        self.config_path = self.broker_dir / "mosquitto.conf"
        self.acl_path = self.broker_dir / "acl"
        self.password_path = self.broker_dir / "passwords"
        self.runtime_path = self.broker_dir / "app.json"
        self.master_path = self.secrets_dir / "master.key"
        self.app_password_path = self.secrets_dir / "mqtt-app-password"
        self.session_path = self.secrets_dir / "session.key"
        self.lock = threading.RLock()

    def _passwd_executable(self) -> str:
        found = shutil.which("mosquitto_passwd")
        if found:
            return found
        windows = Path("C:/Program Files/mosquitto/mosquitto_passwd.exe")
        if windows.is_file():
            return str(windows)
        raise BrokerError("mosquitto_passwd não encontrado. Instale o Mosquitto antes de provisionar etiquetas.")

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                file.write(content)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _create_secret(self, path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="ascii") as file:
                file.write(value + "\n")
        except FileExistsError:
            return
        os.chmod(path, 0o600)

    @staticmethod
    def _protect_directory(path: Path) -> None:
        if os.name != "nt":
            os.chmod(path, 0o700)
            return
        try:
            identity = subprocess.run(
                ["whoami", "/user", "/fo", "csv", "/nh"],
                capture_output=True, text=True, check=True,
            ).stdout
            match = re.search(r"S-1-5-(?:\d+-)*\d+", identity)
            if match is None:
                raise BrokerError("Não foi possível identificar o usuário do Windows.")
            permissions = [
                f"*{match.group()}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
                "*S-1-5-32-544:(OI)(CI)F",
            ]
            subprocess.run(["icacls", str(path), "/grant:r", *permissions], capture_output=True, check=True)
            subprocess.run(["icacls", str(path), "/inheritance:r"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError) as error:
            raise BrokerError("Não foi possível restringir o acesso aos arquivos locais.") from error

    def _hash_password(self, username: str, password: str) -> str:
        self.broker_dir.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".password-input-", dir=self.broker_dir)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                file.write(f"{username}:{password}\n")
            os.chmod(temporary, 0o600)
            result = subprocess.run(
                [self._passwd_executable(), "-U", temporary],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if result.returncode != 0:
                raise BrokerError("Mosquitto não conseguiu gerar o hash da senha.")
            line = Path(temporary).read_text(encoding="utf-8").strip()
            name, separator, hashed = line.partition(":")
            if not separator or name != username or not hashed or hashed == password:
                raise BrokerError("O arquivo de senha gerado pelo Mosquitto é inválido.")
            return hashed
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BrokerError("Falha ao executar mosquitto_passwd.") from error
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _users(self) -> dict[str, str]:
        if not self.password_path.exists():
            return {}
        users = {}
        for line in self.password_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            username, separator, hashed = line.partition(":")
            if not separator or not username or not hashed or username in users:
                raise BrokerError("Arquivo de senhas MQTT inválido; revise-o antes de continuar.")
            users[username] = hashed
        return users

    def _write_users(self, users: dict[str, str]) -> None:
        ordered = ["spt-app"] + sorted(username for username in users if username != "spt-app")
        self._atomic_write(self.password_path, "".join(f"{username}:{users[username]}\n" for username in ordered if username in users))

    def _write_acl(self, users: dict[str, str]) -> None:
        lines = [
            "# Gerado pela tela MQTT. Edite o acesso das etiquetas pela aplicação.\n",
            "user spt-app\n",
            "topic write spt/+/config\n",
            "topic read spt/+/status\n",
        ]
        for username in sorted(users):
            if re.fullmatch(r"[0-9A-Fa-f]{12}", username):
                lines.extend((
                    f"\nuser {username}\n",
                    f"topic read spt/{username}/config\n",
                    f"topic write spt/{username}/status\n",
                ))
        self._atomic_write(self.acl_path, "".join(lines))

    def _write_listener(self, host: str, port: int) -> None:
        config = (
            "# Gerado pela tela MQTT. Execute o broker a partir de web-app/.\n"
            f"listener {port} {host}\n"
            "allow_anonymous false\n"
            "password_file data/broker/passwords\n"
            "acl_file data/broker/acl\n"
            "persistence true\n"
            "persistence_location data/broker/\n"
            "autosave_interval 30\n"
        )
        self._atomic_write(self.config_path, config)
        self._atomic_write(self.runtime_path, json.dumps({"host": host, "port": port}) + "\n")

    @staticmethod
    def validate_listener(host: str, port: str | int) -> tuple[str, int]:
        try:
            address = ipaddress.IPv4Address(host.strip())
            number = int(port)
        except (ipaddress.AddressValueError, ValueError, AttributeError) as error:
            raise BrokerError("Informe um endereço IPv4 e uma porta válidos.") from error
        if address.is_unspecified or address.is_multicast or address == ipaddress.IPv4Address("255.255.255.255") or not 1 <= number <= 65535:
            raise BrokerError("Use um IP específico do computador e uma porta entre 1 e 65535.")
        return str(address), number

    @staticmethod
    def local_ipv4_addresses() -> list[str]:
        addresses = {"127.0.0.1"}
        try:
            addresses.update(item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
        except OSError:
            pass
        return sorted(addresses, key=lambda value: value == "127.0.0.1")

    @staticmethod
    def _require_local_address(host: str) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind((host, 0))
        except OSError as error:
            raise BrokerError("Esse IP não está atribuído a este computador. Use um endereço IPv4 local exibido abaixo.") from error

    def bootstrap(self, *, host: str = "127.0.0.1", port: int = 1884) -> None:
        host, port = self.validate_listener(host, port)
        self._require_local_address(host)
        with self.lock:
            self.broker_dir.mkdir(parents=True, exist_ok=True)
            self.secrets_dir.mkdir(parents=True, exist_ok=True)
            for directory in (self.root / "data", self.broker_dir, self.secrets_dir):
                self._protect_directory(directory)
            self._create_secret(self.master_path, secrets.token_hex(32))
            self._create_secret(self.app_password_path, secrets.token_urlsafe(36))
            self._create_secret(self.session_path, secrets.token_urlsafe(48))
            users = self._users()
            if "spt-app" not in users:
                users["spt-app"] = self._hash_password("spt-app", self.app_password_path.read_text(encoding="ascii").strip())
                self._write_users(users)
            if not self.acl_path.exists():
                self._write_acl(users)
            if not self.config_path.exists() or not self.runtime_path.exists():
                self._write_listener(host, port)

    def listener(self) -> tuple[str, int]:
        try:
            value = json.loads(self.runtime_path.read_text(encoding="utf-8"))
            return self.validate_listener(value["host"], value["port"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise BrokerError("Configuração local do broker não encontrada ou inválida.") from error

    def save_listener(self, host: str, port: str) -> None:
        host, port = self.validate_listener(host, port)
        self._require_local_address(host)
        with self.lock:
            if not self.ready():
                raise BrokerError("Prepare os arquivos do broker antes de alterar o listener.")
            self._write_listener(host, port)

    def ready(self) -> bool:
        return all(path.is_file() for path in (
            self.config_path, self.acl_path, self.password_path,
            self.runtime_path, self.master_path, self.app_password_path,
        ))

    @staticmethod
    def _tag_username(users: dict[str, str], identifier: str) -> str | None:
        matches = [username for username in users if username.upper() == identifier and re.fullmatch(r"[0-9A-Fa-f]{12}", username)]
        if len(matches) > 1:
            raise BrokerError("Esta etiqueta possui usuários MQTT duplicados; revise o arquivo de senhas.")
        return matches[0] if matches else None

    def provisioned_accounts(self) -> dict[str, str]:
        with self.lock:
            accounts = {}
            for username in self._users():
                if re.fullmatch(r"[0-9A-Fa-f]{12}", username):
                    identifier = username.upper()
                    if identifier in accounts:
                        raise BrokerError("Esta etiqueta possui usuários MQTT duplicados; revise o arquivo de senhas.")
                    accounts[identifier] = username
            return accounts

    def provisioned_ids(self) -> set[str]:
        return set(self.provisioned_accounts())

    def tag_username(self, identifier: str) -> str | None:
        identifier = validate_identifier(identifier)
        with self.lock:
            return self._tag_username(self._users(), identifier)

    def provision_tag(self, identifier: str, *, rotate: bool = False, username_case: str = "upper") -> tuple[str, str]:
        identifier = validate_identifier(identifier)
        if username_case not in ("upper", "lower"):
            raise BrokerError("Formato do usuário MQTT inválido.")
        with self.lock:
            if not self.ready():
                raise BrokerError("Prepare os arquivos do broker antes de provisionar etiquetas.")
            users = self._users()
            existing_username = self._tag_username(users, identifier)
            if existing_username and not rotate:
                raise BrokerError("Esta etiqueta já está provisionada. Use a ação de trocar senha.")
            if not existing_username and rotate:
                raise BrokerError("Esta etiqueta ainda não está provisionada.")
            password = secrets.token_urlsafe(32)
            username = existing_username if rotate else (identifier.lower() if username_case == "lower" else identifier)
            try:
                key = derive_tag_key(bytes.fromhex(self.master_path.read_text(encoding="ascii").strip()), identifier).hex()
            except (OSError, ValueError) as error:
                raise BrokerError("Chave mestra inválida; nenhuma credencial foi alterada.") from error
            key_path = self.secrets_dir / f"{identifier}.key"
            if key_path.exists() and key_path.read_text(encoding="ascii").strip() != key:
                raise BrokerError("A chave individual existente não corresponde à chave mestra atual.")
            users[username] = self._hash_password(username, password)
            self._create_secret(key_path, key)
            self._write_users(users)
            self._write_acl(users)
            return password, key

    def revoke_tag(self, identifier: str) -> None:
        identifier = validate_identifier(identifier)
        with self.lock:
            users = self._users()
            username = self._tag_username(users, identifier)
            if username is None:
                raise BrokerError("Esta etiqueta não possui acesso MQTT ativo.")
            del users[username]
            self._write_users(users)
            self._write_acl(users)
            (self.secrets_dir / f"{identifier}.key").unlink(missing_ok=True)

    def set_tag_username_case(self, identifier: str, username_case: str) -> str:
        identifier = validate_identifier(identifier)
        if username_case not in ("upper", "lower"):
            raise BrokerError("Formato do usuário MQTT inválido.")
        with self.lock:
            users = self._users()
            current = self._tag_username(users, identifier)
            if current is None:
                raise BrokerError("Esta etiqueta não possui acesso MQTT ativo.")
            desired = identifier.lower() if username_case == "lower" else identifier
            if current != desired:
                users[desired] = users.pop(current)
                self._write_users(users)
            self._write_acl(users)
            return desired

    def check_tag_credentials(self, identifier: str, password: str) -> bool:
        """Check a supplied tag password without logging or storing it."""
        import paho.mqtt.client as mqtt

        identifier = validate_identifier(identifier)
        username = self.tag_username(identifier)
        if username is None:
            raise BrokerError("Esta etiqueta não está provisionada no broker.")
        host, port = self.listener()
        answered = threading.Event()
        accepted = False

        def on_connect(_client, _userdata, _flags, reason_code, _properties):
            nonlocal accepted
            accepted = not reason_code.is_failure
            answered.set()

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"spt-credential-check-{secrets.token_hex(4)}",
            protocol=mqtt.MQTTv311,
        )
        client.username_pw_set(username, password)
        client.on_connect = on_connect
        try:
            client.connect(host, port, keepalive=10)
            client.loop_start()
            if not answered.wait(timeout=5):
                raise BrokerError("O broker não respondeu à tentativa de autenticação.")
            return accepted
        except OSError as error:
            raise BrokerError("Não foi possível conectar ao broker configurado.") from error
        finally:
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    import getpass
    import sys

    manager = BrokerManager()
    if len(sys.argv) == 1:
        manager.bootstrap()
        print("Arquivos locais do broker preparados em data/broker/ e secrets/.")
    elif len(sys.argv) == 3 and sys.argv[1] == "check-tag":
        try:
            candidate = getpass.getpass("Senha MQTT da etiqueta: ")
            if manager.check_tag_credentials(sys.argv[2], candidate):
                print("Credenciais aceitas pelo broker.")
            else:
                raise SystemExit("Credenciais recusadas pelo broker. Confira usuário e senha ou gere uma nova senha na tela MQTT.")
        except (BrokerError, ValueError) as error:
            raise SystemExit(str(error)) from error
    else:
        raise SystemExit("Uso: python -m smart_price_tag.broker_admin [check-tag ID_MAC]")
