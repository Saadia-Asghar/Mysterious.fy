"""M11: policy engine, approved playbook catalog and safe executor.

Safety rules enforced here (CLAUDE.md):
- Only playbooks stored in remediation-playbooks/ can run; requests name a playbook_id, never a command.
- Only action types implemented below can run (currently `http_post`). Unknown types fail to load.
- The target is built from the registered device's management_address, never from request data.
- A playbook must be in the device profile's `allowed_playbooks`, match the device type, and the
  profile must declare the playbook's required capability.
- Policy decides: monitor_only / recommend -> rejected_by_policy, require_approval -> pending until a
  person approves, auto_remediate -> runs immediately.
- `completed` only means the action was accepted. Health is decided by monitoring (M12).
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.schemas import Device, DeviceProfile, Identifier


class HttpPostAction(BaseModel):
    type: Literal["http_post"]
    path: str = Field(pattern=r"^/[A-Za-z0-9/_\-.]*$")


class Playbook(BaseModel):
    playbook_id: Identifier
    description: str = Field(min_length=1)
    applies_to_device_types: list[str] = Field(min_length=1)
    required_capability: str = Field(min_length=1)
    action: HttpPostAction
    timeout_seconds: float = Field(default=10, gt=0, le=60)


class PlaybookCatalog:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._playbooks: dict[str, Playbook] = {}

    def load(self) -> None:
        loaded: dict[str, Playbook] = {}
        if self.directory.is_dir():
            for path in sorted(self.directory.glob("*.json")):
                try:
                    pb = Playbook.model_validate(json.loads(path.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, ValidationError) as exc:
                    raise ValueError(f"Invalid playbook {path.name}: {exc}") from exc
                if pb.playbook_id in loaded:
                    raise ValueError(f"Duplicate playbook_id {pb.playbook_id}")
                loaded[pb.playbook_id] = pb
        self._playbooks = loaded

    def get(self, playbook_id: str) -> Playbook | None:
        return self._playbooks.get(playbook_id)

    def all(self) -> list[Playbook]:
        return list(self._playbooks.values())


@dataclass(frozen=True)
class Decision:
    status: Literal["rejected_by_policy", "pending", "run"]
    reason: str


def eligibility_problem(device: Device, profile: DeviceProfile, playbook: Playbook) -> str | None:
    if not device.enabled:
        return f"device {device.device_id} is disabled"
    if playbook.playbook_id not in profile.allowed_playbooks:
        return f"playbook {playbook.playbook_id} is not allowed by profile {profile.profile_id}"
    if device.device_type not in playbook.applies_to_device_types:
        return f"playbook {playbook.playbook_id} does not apply to device type {device.device_type}"
    if playbook.required_capability not in profile.capabilities:
        return f"profile {profile.profile_id} lacks capability {playbook.required_capability}"
    if not device.management_address.startswith(("http://", "https://")):
        return f"device {device.device_id} has no HTTP management address"
    return None


def decide(device: Device, profile: DeviceProfile, playbook: Playbook) -> Decision:
    problem = eligibility_problem(device, profile, playbook)
    if problem:
        return Decision("rejected_by_policy", problem)
    policy = device.automation_policy
    if policy == "monitor_only":
        return Decision("rejected_by_policy", "policy monitor_only: no actions allowed; handled by humans")
    if policy == "recommend":
        return Decision("rejected_by_policy", f"policy recommend: suggested {playbook.playbook_id}, not executed")
    if policy == "require_approval":
        return Decision("pending", "policy require_approval: waiting for a person to approve")
    return Decision("run", "policy auto_remediate: approved playbook runs automatically")


def execute(playbook: Playbook, device: Device, transport: httpx.BaseTransport | None = None) -> tuple[bool, str]:
    """Run the playbook's single action. Returns (accepted, detail). Not a health check."""
    url = device.management_address.rstrip("/") + playbook.action.path
    try:
        with httpx.Client(transport=transport, timeout=playbook.timeout_seconds) as client:
            r = client.post(url)
    except httpx.HTTPError as exc:
        return False, f"action failed: {exc}"
    if 200 <= r.status_code < 300:
        return True, f"POST {playbook.action.path} returned {r.status_code}"
    return False, f"POST {playbook.action.path} returned {r.status_code}"
