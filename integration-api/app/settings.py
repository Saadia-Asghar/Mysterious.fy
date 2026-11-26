from dataclasses import dataclass
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDERS = {"", "change_me"}


def _dotenv(path: Path) -> dict[str, str]:
    """Read KEY=VALUE lines from the repo's .env (if any). Real environment variables win."""
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


@dataclass(frozen=True)
class Settings:
    database_path: Path
    profiles_dir: Path
    host: str = "127.0.0.1"
    port: int = 8000
    playbooks_dir: Path = REPO_ROOT / "remediation-playbooks"
    zabbix_webhook_token: str | None = None
    osticket_url: str | None = None
    osticket_api_key: str | None = None
    osticket_reporter_email: str | None = None
    ticket_min_severity: str = "warning"
    zabbix_api_url: str | None = None
    zabbix_api_token: str | None = None
    verify_timeout_seconds: int = 300
    portal_secret: str | None = None  # signs portal login tokens; random per start if unset
    auto_sync_seconds: int = 0  # >0: background incident sync, verification and recovery check

    @classmethod
    def from_env(cls, env_file: Path | None = REPO_ROOT / ".env") -> "Settings":
        env = {**(_dotenv(env_file) if env_file else {}), **os.environ}

        def get(key: str, default: str | None = None) -> str | None:
            value = env.get(key)
            return default if value is None or value.strip() in PLACEHOLDERS else value

        return cls(
            database_path=Path(get("NMS_DATABASE_PATH", str(REPO_ROOT / "data" / "nms.sqlite"))),
            profiles_dir=Path(get("NMS_PROFILES_DIR", str(REPO_ROOT / "device-profiles"))),
            host=get("NMS_HOST", "127.0.0.1"),
            port=int(get("NMS_PORT", "8000")),
            playbooks_dir=Path(get("NMS_PLAYBOOKS_DIR", str(REPO_ROOT / "remediation-playbooks"))),
            zabbix_webhook_token=get("NMS_ZABBIX_WEBHOOK_TOKEN"),
            osticket_url=get("NMS_OSTICKET_URL"),
            osticket_api_key=get("NMS_OSTICKET_API_KEY"),
            osticket_reporter_email=get("NMS_OSTICKET_REPORTER_EMAIL"),
            ticket_min_severity=get("NMS_TICKET_MIN_SEVERITY", "warning"),
            zabbix_api_url=get("NMS_ZABBIX_API_URL"),
            zabbix_api_token=get("NMS_ZABBIX_API_TOKEN"),
            verify_timeout_seconds=int(get("NMS_VERIFY_TIMEOUT_SECONDS", "300")),
            portal_secret=get("NMS_PORTAL_SECRET"),
            auto_sync_seconds=int(get("NMS_AUTO_SYNC_SECONDS", "0")),
        )
