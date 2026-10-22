"""Repository boundaries and Compose isolation are independent of the shell cwd."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("profile_compose", ROOT / "tools/compose.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("validation", [False, True])
def test_compose_uses_repository_paths_and_selected_profile(tmp_path, monkeypatch, validation):
    monkeypatch.chdir(tmp_path)
    metadata = json.loads((ROOT / "variant.json").read_text(encoding="utf-8"))
    command = module.compose_command(["config", "--quiet"], validation, environ={"BEDROCK_API_KEY": "test"})
    assert command[command.index("--project-directory") + 1] == str(ROOT)
    assert command[command.index("--project-name") + 1] == metadata["validation_project" if validation else "compose_project"]
    files = [command[n + 1] for n, arg in enumerate(command) if arg == "-f"]
    assert all(Path(file).is_absolute() and Path(file).parent == ROOT for file in files)
    assert (str(ROOT / "compose.validation.yaml") in files) == validation
    assert (str(ROOT / "compose.bedrock.yaml") in files) == (metadata["variant"] != "local")
    assert command[-2:] == ["config", "--quiet"]


def test_compose_names_and_images_remain_stable_after_relocation():
    metadata = json.loads((ROOT / "variant.json").read_text(encoding="utf-8"))
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert compose["name"] == metadata["compose_project"]
    for service in ("identity", "knowledge", "conversation", "knowledge-worker", "gateway"):
        assert compose["services"][service]["image"].startswith(metadata["compose_project"] + "/")
    gateway_port = metadata["development_ports"]["gateway"]
    assert compose["services"]["gateway"]["ports"] == [f"127.0.0.1:{gateway_port}:8000"]


def test_extra_overrides_are_absolute_and_applied_after_validation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    command = module.compose_command(["config"], True, environ={"BEDROCK_API_KEY": "test"}, extra_files=["compose.validation.offline.yaml"])
    assert command[-3:] == ["-f", str(ROOT / "compose.validation.offline.yaml"), "config"]
    assert command.index(str(ROOT / "compose.validation.yaml")) < command.index(str(ROOT / "compose.validation.offline.yaml"))
