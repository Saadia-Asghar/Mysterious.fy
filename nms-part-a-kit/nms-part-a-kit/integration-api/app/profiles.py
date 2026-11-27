import json
from pathlib import Path

from pydantic import ValidationError

from app.schemas import DeviceProfile


class ProfileCatalog:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._profiles: dict[str, DeviceProfile] = {}

    def load(self) -> None:
        if not self.directory.is_dir():
            raise FileNotFoundError(f"Profile directory does not exist: {self.directory}")
        loaded: dict[str, DeviceProfile] = {}
        for path in sorted(self.directory.glob("*.json")):
            try:
                profile = DeviceProfile.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise ValueError(f"Invalid device profile {path.name}: {exc}") from exc
            if profile.profile_id in loaded:
                raise ValueError(f"Duplicate profile_id {profile.profile_id}")
            loaded[profile.profile_id] = profile
        if not loaded:
            raise ValueError(f"No device profiles found in {self.directory}")
        self._profiles = loaded

    def all(self) -> list[DeviceProfile]:
        return list(self._profiles.values())

    def get(self, profile_id: str) -> DeviceProfile | None:
        return self._profiles.get(profile_id)
