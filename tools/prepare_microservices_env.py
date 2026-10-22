"""Generate an isolated local configuration without overwriting existing credentials."""

import argparse
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env.microservices"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--upgrade",
    action="store_true",
    help="Append missing keys without changing existing values",
)
args = parser.parse_args()
if target.exists() and not args.upgrade:
    raise SystemExit(".env.microservices already exists; nothing was overwritten.")
template = (root / ".env.microservices.example").read_text(encoding="utf-8")
secret_keys = {
    "POSTGRES_PASSWORD",
    "IDENTITY_DB_PASSWORD",
    "KNOWLEDGE_DB_PASSWORD",
    "CONVERSATION_DB_PASSWORD",
    "AUTH_JWT_SECRET",
    "KNOWLEDGE_SERVICE_TOKEN",
    "BOOTSTRAP_ADMIN_PASSWORD",
    "MINIO_ROOT_PASSWORD",
    "REDIS_PASSWORD",
}
lines = []
for line in template.splitlines():
    key, sep, value = line.partition("=")
    lines.append(
        key + "=" + secrets.token_urlsafe(36) if sep and key in secret_keys else line
    )
if target.exists():
    existing = target.read_text(encoding="utf-8")
    keys = {
        line.partition("=")[0]
        for line in existing.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    additions = [
        line
        for line in lines
        if "=" in line
        and not line.lstrip().startswith("#")
        and line.partition("=")[0] not in keys
    ]
    with target.open("a", encoding="utf-8") as file:
        file.write("\n" + "\n".join(additions) + "\n")
else:
    with target.open("x", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
print(
    "Prepared .env.microservices without replacing existing values. Secrets were not printed."
)
