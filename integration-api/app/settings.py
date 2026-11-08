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
    zabbix_webhook_token: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_path=Path(os.environ.get("NMS_DATABASE_PATH", REPO_ROOT / "data" / "nms.sqlite")),
            profiles_dir=Path(os.environ.get("NMS_PROFILES_DIR", REPO_ROOT / "device-profiles")),
            host=os.environ.get("NMS_HOST", "127.0.0.1"),
            port=int(os.environ.get("NMS_PORT", "8000")),
            zabbix_webhook_token=os.environ.get("NMS_ZABBIX_WEBHOOK_TOKEN") or None,
        )
