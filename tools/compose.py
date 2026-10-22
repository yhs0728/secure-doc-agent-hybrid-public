"""Run this repository's Compose profile independently of the current directory."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compose_command(
    arguments, validation=False, root=ROOT, environ=None, extra_files=()
):
    environ = os.environ if environ is None else environ
    metadata = json.loads((root / "variant.json").read_text(encoding="utf-8"))
    project = metadata["validation_project" if validation else "compose_project"]
    result = [
        "docker",
        "compose",
        "--project-directory",
        str(root),
        "--project-name",
        project,
        "--env-file",
        str(root / ".env.microservices"),
    ]
    cloud = metadata["variant"] != "local"
    if cloud:
        secret_file = root / ".env.bedrock"
        if secret_file.is_file():
            result.extend(["--env-file", str(secret_file)])
    result.extend(["-f", str(root / "compose.yaml")])
    if cloud:
        result.extend(["-f", str(root / "compose.bedrock.yaml")])
    if validation:
        result.extend(["-f", str(root / "compose.validation.yaml")])
    for file in extra_files:
        result.extend(["-f", str((root / file).resolve())])
    return result + (arguments or ["ps"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", action="store_true")
    parser.add_argument("-f", "--file", action="append", default=[])
    # Parse only wrapper options before the first Compose argument. Once a
    # Compose option/command begins, preserve its order and values verbatim.
    tokens = sys.argv[1:]
    boundary = 0
    while boundary < len(tokens):
        token = tokens[boundary]
        if token == "--validation":
            boundary += 1
        elif token in ("-f", "--file"):
            if boundary + 1 >= len(tokens):
                parser.error(f"{token} requires a file")
            boundary += 2
        elif token.startswith("--file="):
            boundary += 1
        elif token in ("-h", "--help"):
            parser.print_help()
            return 0
        else:
            break
    args = parser.parse_args(tokens[:boundary])
    args.arguments = tokens[boundary:]
    if args.arguments[:1] == ["--"]:
        args.arguments = args.arguments[1:]
    if not (ROOT / ".env.microservices").is_file():
        parser.error("Run tools/prepare_microservices_env.py in this repository first")
    try:
        cmd = compose_command(args.arguments, validation=args.validation, extra_files=args.file)
    except ValueError as exc:
        parser.error(str(exc))
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
