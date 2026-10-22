"""Validate this repository profile without contacting any cloud API."""

import json
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
profile = json.loads((root / "variant.json").read_text(encoding="utf-8"))["variant"]
assert profile in ("local", "hybrid", "multicloud")
if profile == "multicloud":
    assert (
        json.loads((root / "variant.json").read_text(encoding="utf-8"))["deployment"]
        == "oci-aws"
    )
assert (root / "DEPLOYMENT.md").is_file()
if profile != "local":
    doc = yaml.safe_load((root / "compose.bedrock.yaml").read_text(encoding="utf-8"))
    env = doc["services"]["conversation"]["environment"]
    assert env["LLM_PROVIDER"] == "bedrock"
    assert env["CAPACITY_BACKEND"] == "redis"
    assert "BEDROCK_API_KEY:-" in env["LLM_API_KEY"]
    assert env["HYBRID_EXTERNAL_WORKSPACES"] == "${HYBRID_EXTERNAL_WORKSPACES:-}"
    example = (root / ".env.bedrock.example").read_text(encoding="utf-8")
    assert "BEDROCK_API_KEY=\n" in example
if profile == "multicloud":
    overlay = root / "deploy/oci-aws"
    config = [
        yaml.safe_load((overlay / name).read_text(encoding="utf-8"))
        for name in (
            "identity-config.yaml",
            "knowledge-config.yaml",
            "conversation-config.yaml",
        )
    ]
    assert len(config) == 3
    assert all(item["data"]["PGSSLMODE"] == "require" for item in config)
    assert config[2]["data"]["LLM_PROVIDER"] == "bedrock"

metadata = json.loads((root / "variant.json").read_text(encoding="utf-8"))
compose = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
assert compose["name"] == metadata["compose_project"]
assert compose["services"]["gateway"]["ports"] == ["127.0.0.1:" + str(metadata["development_ports"]["gateway"]) + ":8000"]
print("PASS: repository deployment profile:", profile)
