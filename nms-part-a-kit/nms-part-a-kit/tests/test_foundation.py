"""M0 acceptance checks: repository layout, agent context, profiles and secret hygiene."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = [
    "README.md",
    "CLAUDE.md",
    ".gitignore",
    ".env.example",
    "docs/architecture.md",
    "docs/data-contracts.md",
    "docs/milestones.md",
    "docs/fyp-specification.md",
]

COMPONENT_DIRS = [
    "docker",
    "monitoring-zabbix",
    "visualization-grafana",
    "ticketing-osticket",
    "integration-api",
    "intelligence",
    "intelligence/anomaly",
    "intelligence/correlation",
    "intelligence/rca",
    "device-profiles",
    "remediation-playbooks",
    "test-environment",
    "test-environment/simulators",
    "test-environment/fault-scenarios",
    "scripts",
]

POLICIES = {"monitor_only", "recommend", "require_approval", "auto_remediate"}


@pytest.mark.parametrize("path", REQUIRED_FILES)
def test_required_file_exists(path):
    assert (ROOT / path).is_file(), f"missing {path}"


@pytest.mark.parametrize("path", COMPONENT_DIRS)
def test_component_dir_has_readme(path):
    assert (ROOT / path / "README.md").is_file(), f"{path}/README.md missing"


def test_claude_md_keeps_architecture_rules():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for phrase in ["Zabbix", "Grafana", "osTicket", "Policy", "verification", "main", "dev"]:
        assert phrase in text, f"CLAUDE.md lost '{phrase}'"


def profiles():
    return sorted((ROOT / "device-profiles").glob("*.json"))


def test_at_least_one_profile():
    assert profiles()


@pytest.mark.parametrize("path", profiles(), ids=lambda p: p.name)
def test_profile_is_valid_and_safe_by_default(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ["profile_id", "device_type", "connectors", "metrics", "triggers", "default_policy"]:
        assert key in data, f"{path.name} missing {key}"
    assert data["default_policy"] in POLICIES
    assert data["default_policy"] != "auto_remediate", "new profiles must not auto-remediate by default"


def test_env_ignored_but_example_tracked():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in lines
    assert "!.env.example" in lines


SECRET_KEY = re.compile(r"(PASSWORD|SECRET|TOKEN|API_KEY)\s*=\s*(\S+)", re.I)


def test_env_example_has_no_real_secrets():
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = SECRET_KEY.search(line)
        if m:
            value = m.group(2).lower()
            assert value.startswith("change") or value.startswith("<"), (
                f"possible real secret in .env.example: {line}"
            )
