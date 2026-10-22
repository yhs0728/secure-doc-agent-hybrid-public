"""Publish an explicit, checksum-verified release to baseline ECR/S3.

No application .env, DB state, documents or whole source tree is uploaded.
Docker registry credentials live only in a temporary config directory.
"""

import argparse
import base64
import json
import subprocess
import tempfile
from pathlib import Path

from aws_finops import ROOT, Aws
from dotenv import dotenv_values
from release_cache import verify


def docker(*args, input_text=None):
    result = subprocess.run(
        ["docker", *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Docker release operation failed: " + args[0])
    return result.stdout.strip()


def verify_remote_image(local, remote):
    manifest = json.loads(remote["imageManifest"])
    descriptor = local.get("Descriptor") or {}
    if descriptor.get("digest") == local["Id"]:
        if remote["imageId"]["imageDigest"] != descriptor["digest"] or manifest.get(
            "mediaType"
        ) != descriptor.get("mediaType"):
            raise ValueError("ECR descriptor differs from local OCI image/index")
        return "oci_descriptor_digest"
    if manifest.get("config", {}).get("digest") != local["Id"]:
        raise ValueError("ECR configuration digest differs from local image")
    return "legacy_configuration_digest"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    release = args.release.resolve()
    release.relative_to((ROOT / ".releases").resolve())
    manifest = verify(release)
    archive = release / "images.tar"
    if archive.stat().st_size > 2 * 1024**3:
        raise ValueError(
            "Portfolio release upload limit is 2 GiB; review storage budget first"
        )
    services = {
        ("knowledge" if k == "knowledge-worker" else k): v
        for k, v in manifest["images"].items()
    }
    print(
        json.dumps(
            {
                "archive_bytes": archive.stat().st_size,
                "services": sorted(services),
                "tag": "release-" + manifest["archive_sha256"][:16],
                "apply": args.apply,
            }
        )
    )
    if not args.apply:
        return
    cfg = dotenv_values(ROOT / ".env.finops")
    region = cfg.get("AWS_REGION") or "ap-northeast-1"
    aws = Aws(cfg.get("AWS_PROFILE") or "secure-doc-hybrid", region)
    identity = aws.call("sts", "get-caller-identity")
    account = identity["Account"]
    registry = account + ".dkr.ecr." + region + ".amazonaws.com"
    auth = aws.call("ecr", "get-authorization-token")["authorizationData"][0]
    username, password = (
        base64.b64decode(auth["authorizationToken"]).decode().split(":", 1)
    )
    tag = "release-" + manifest["archive_sha256"][:16]
    published = {}
    with tempfile.TemporaryDirectory(prefix="securedoc-ecr-") as config:
        docker(
            "--config",
            config,
            "login",
            "--username",
            username,
            "--password-stdin",
            registry,
            input_text=password,
        )
        for service, image in sorted(services.items()):
            # verify() checked the manifest; inspect ensures the exact local image is present.
            actual = json.loads(docker("image", "inspect", image))[0]["Id"]
            if actual != image:
                raise ValueError("Local image differs from release manifest")
            repository = "secure-doc-hybrid/" + service
            reference = registry + "/" + repository + ":" + tag
            existing = aws.call(
                "ecr",
                "batch-get-image",
                "--repository-name",
                repository,
                "--image-ids",
                "imageTag=" + tag,
            ).get("images", [])
            if not existing:
                docker("image", "tag", image, reference)
                docker("--config", config, "push", reference)
            remote = aws.call(
                "ecr",
                "batch-get-image",
                "--repository-name",
                repository,
                "--image-ids",
                "imageTag=" + tag,
            )["images"][0]
            method = verify_remote_image(
                json.loads(docker("image", "inspect", image))[0], remote
            )
            published[service] = {
                "image_digest": remote["imageId"]["imageDigest"],
                "local_image_id": image,
                "verification_method": method,
                "tag": tag,
            }
    bucket = "secure-doc-hybrid-" + account + "-" + region + "-artifacts"
    prefix = "releases/" + manifest["archive_sha256"] + "/"
    checksum = base64.b64encode(bytes.fromhex(manifest["archive_sha256"])).decode()
    aws.call(
        "s3api",
        "put-object",
        "--bucket",
        bucket,
        "--key",
        prefix + "images.tar",
        "--body",
        str(archive),
        "--checksum-algorithm",
        "SHA256",
        "--checksum-sha256",
        checksum,
        "--metadata",
        "archive-sha256=" + manifest["archive_sha256"],
    )
    aws.call(
        "s3api",
        "put-object",
        "--bucket",
        bucket,
        "--key",
        prefix + "manifest.json",
        "--body",
        str(release / "manifest.json"),
        "--content-type",
        "application/json",
    )
    head = aws.call(
        "s3api",
        "head-object",
        "--bucket",
        bucket,
        "--key",
        prefix + "images.tar",
        "--checksum-mode",
        "ENABLED",
    )
    if (
        head["ContentLength"] != archive.stat().st_size
        or head.get("ChecksumSHA256") != checksum
    ):
        raise ValueError("S3 release checksum/length verification failed")
    report = {
        "passed": True,
        "ecr": published,
        "s3_archive_bytes": head["ContentLength"],
        "s3_sha256_verified": True,
        "archive_sha256": manifest["archive_sha256"],
    }
    out = ROOT / ".aws-local"
    out.mkdir(exist_ok=True)
    (out / "release-publication.json").write_text(
        json.dumps(report, indent=2), encoding="utf8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
