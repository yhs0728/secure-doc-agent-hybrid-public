"""Cache exact local images for disconnected service patching and rollback.

This bundles images, not DB state, secrets, model weights or operating-system packages.
SHA-256 detects corruption; use a trusted artifact signature for publisher authenticity.
"""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = {"identity", "knowledge", "knowledge-worker", "conversation", "gateway"}
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


def docker(*arguments):
    result = subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Docker operation failed: " + arguments[0])
    return result.stdout.strip()


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_images(images):
    if not images or set(images) - SERVICES:
        raise ValueError("Select only application services")
    if any(not IMAGE_ID.fullmatch(value) for value in images.values()):
        raise ValueError("Manifest must pin sha256 image IDs")
    if ("knowledge" in images or "knowledge-worker" in images) and images.get(
        "knowledge"
    ) != images.get("knowledge-worker"):
        raise ValueError("knowledge and knowledge-worker must be patched together")


def package(target, image_specs):
    if target.exists():
        raise ValueError(
            "Choose a new release directory; existing releases are immutable"
        )
    images = {}
    for spec in image_specs:
        service, sep, reference = spec.partition("=")
        if not sep or service not in SERVICES or service in images:
            raise ValueError("Use unique --image service=local-image-reference")
        image = json.loads(docker("image", "inspect", reference))[0]
        images[service] = image["Id"]
    validate_images(images)
    target.mkdir(parents=True)
    archive = target / "images.tar"
    docker("image", "save", "--output", str(archive), *sorted(set(images.values())))
    manifest = {"version": 1, "images": images, "archive_sha256": sha256(archive)}
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf8"
    )
    return manifest


def verify(target):
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf8"))
    if manifest.get("version") != 1:
        raise ValueError("Unsupported release format")
    validate_images(manifest["images"])
    if sha256(target / "images.tar") != manifest.get("archive_sha256"):
        raise ValueError("Release archive checksum mismatch")
    return manifest


def restore(target, apply=False):
    manifest = verify(target)
    if apply:
        docker("image", "load", "--input", str(target / "images.tar"))
        for image in manifest["images"].values():
            actual = json.loads(docker("image", "inspect", image))[0]["Id"]
            if actual != image:
                raise ValueError("Restored image identity mismatch")
    # Pin content and forbid registry pulls. The operator retains the local env/config.
    override = {
        "services": {
            service: {"image": image, "pull_policy": "never"}
            for service, image in manifest["images"].items()
        }
    }
    if apply:
        (target / "compose.images.json").write_text(
            json.dumps(override, indent=2), encoding="utf8"
        )
    return override


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("package")
    capture.add_argument("directory", type=Path)
    capture.add_argument("--image", action="append", required=True)
    for command in ("verify", "restore"):
        p = sub.add_parser(command)
        p.add_argument("directory", type=Path)
        if command == "restore":
            p.add_argument(
                "--apply",
                action="store_true",
                help="Import verified images and write override; does not deploy",
            )
    args = parser.parse_args()
    try:
        if args.command == "package":
            result = package(args.directory, args.image)
        elif args.command == "verify":
            result = verify(args.directory)
        else:
            result = restore(args.directory, args.apply)
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
