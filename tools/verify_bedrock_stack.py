"""Start isolated hybrid stack and run synthetic-only real AWS acceptance checks."""

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--no-build", action="store_true", help="Use already built images")
args = parser.parse_args()
OUT = ROOT / ".microservice-tests"
OUT.mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location(
    "hybrid_compose", ROOT / "tools/compose.py"
)
compose = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compose)
metadata_path = OUT / "bedrock-stack-metadata.json"
if metadata_path.exists():
    metadata = json.loads(metadata_path.read_text(encoding="utf8"))
else:
    metadata = {
        "project": "secure-doc-agent-hybrid-cloudcheck-20261019",
        "workspace_id": str(uuid4()),
        "gateway": "http://127.0.0.1:18182",
        "input_scope": "synthetic documents only",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf8")
overlay = OUT / "bedrock-stack.yaml"
overlay.write_text(
    '''services:
  identity:
    environment:
      DEFAULT_WORKSPACE_ID: "'''
    + metadata["workspace_id"]
    + '''"
  conversation:
    environment:
      HYBRID_EXTERNAL_WORKSPACES: "'''
    + metadata["workspace_id"]
    + """"
  knowledge-worker:
    deploy:
      replicas: 1
""",
    encoding="utf8",
)

secret_values = []
for name in [".env.microservices", ".env.bedrock"]:
    for key, value in dotenv_values(ROOT / name).items():
        if (
            value
            and len(value) > 8
            and any(part in key for part in ("PASSWORD", "SECRET", "TOKEN", "API_KEY"))
        ):
            secret_values.append(value)


def sanitized(text):
    for value in secret_values:
        text = text.replace(value, "[REDACTED]")
    return text


command = compose.compose_command(
    (["up", "-d"] if args.no_build else ["up", "-d", "--build"]),
    validation=True,
    extra_files=[str(overlay)],
)
command[command.index("--project-name") + 1] = metadata["project"]
print("Building and starting isolated hybrid verification stack.", flush=True)
result = subprocess.run(
    command,
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf8",
    errors="replace",
    check=False,
)
(OUT / "bedrock-stack-up.log").write_text(
    sanitized(result.stdout + "\n" + result.stderr), encoding="utf8"
)
if result.returncode:
    print(sanitized(result.stderr[-5000:]))
    raise SystemExit(result.returncode)
print(
    "Stack started; verifying real storage, embeddings, search and Bedrock.", flush=True
)
verify_spec = importlib.util.spec_from_file_location(
    "bedrock_full_stack", ROOT / "tools/verify_full_stack.py"
)
verify = importlib.util.module_from_spec(verify_spec)
verify_spec.loader.exec_module(verify)
try:
    report = verify.verify(
        metadata["gateway"],
        ROOT / ".env.microservices",
        timeout=300,
        report=OUT / "bedrock-full-stack.json",
    )
except Exception as error:  # noqa: BLE001 - redact credentials and provider response details
    print(
        json.dumps(
            {
                "passed": False,
                "error_type": type(error).__name__,
                "report": "bedrock-full-stack.json",
            }
        )
    )
    raise SystemExit(1) from None
print(json.dumps(report, ensure_ascii=False))
print("Hybrid verification UI: " + metadata["gateway"])
