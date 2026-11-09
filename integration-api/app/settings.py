from dataclasses import dataclass
from pathlib import Path
import os

REPO_ROOT = Path(__file__).resolve().parents[2]


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

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=Path(os.environ.get("NMS_DATABASE_PATH", REPO_ROOT / "data" / "nms.sqlite")),
            profiles_dir=Path(os.environ.get("NMS_PROFILES_DIR", REPO_ROOT / "device-profiles")),
            host=os.environ.get("NMS_HOST", "127.0.0.1"),
            port=int(os.environ.get("NMS_PORT", "8000")),
            playbooks_dir=Path(os.environ.get("NMS_PLAYBOOKS_DIR", REPO_ROOT / "remediation-playbooks")),
            zabbix_webhook_token=os.environ.get("NMS_ZABBIX_WEBHOOK_TOKEN") or None,
            osticket_url=os.environ.get("NMS_OSTICKET_URL") or None,
            osticket_api_key=os.environ.get("NMS_OSTICKET_API_KEY") or None,
            osticket_reporter_email=os.environ.get("NMS_OSTICKET_REPORTER_EMAIL") or None,
            ticket_min_severity=os.environ.get("NMS_TICKET_MIN_SEVERITY", "warning"),
        )
