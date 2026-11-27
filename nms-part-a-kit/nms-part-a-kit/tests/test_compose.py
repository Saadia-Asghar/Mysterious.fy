"""M1 static checks for docker/docker-compose.yml (runtime checks need Docker)."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker" / "docker-compose.yml"
EXPECTED = {"zabbix-db", "zabbix-server", "zabbix-web", "grafana", "osticket-db", "osticket", "nms-db"}


def env_example_keys():
    keys = set()
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            keys.add(line.split("=", 1)[0].strip())
    return keys


def test_compose_has_core_services():
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert EXPECTED <= set(data["services"])


def test_every_variable_is_in_env_example():
    used = set(re.findall(r"\$\{(\w+)\}", COMPOSE.read_text(encoding="utf-8")))
    missing = used - env_example_keys()
    assert not missing, f"add to .env.example: {sorted(missing)}"


def test_no_hardcoded_passwords():
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    for name, svc in data["services"].items():
        env = svc.get("environment") or {}
        for key, value in env.items():
            if re.search(r"PASS|TOKEN|SECRET", key):
                assert str(value).startswith("${"), f"{name}.{key} must come from .env"


def test_zabbix_server_can_reach_the_integration_api_on_the_host():
    # The NMS webhook runs in this container and posts to host.docker.internal:8000.
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert "host.docker.internal:host-gateway" in data["services"]["zabbix-server"]["extra_hosts"]
