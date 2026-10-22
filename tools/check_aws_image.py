"""Read basic ECR OS scan and gate production promotion; never suppress findings."""

import argparse
import json

from aws_finops import ROOT, Aws
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--service",
        choices=["identity", "knowledge", "conversation", "gateway"],
        default="conversation",
    )
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    cfg = dotenv_values(ROOT / ".env.finops")
    aws = Aws(
        cfg.get("AWS_PROFILE") or "secure-doc-hybrid",
        cfg.get("AWS_REGION") or "ap-northeast-1",
    )
    repository = "secure-doc-hybrid/" + args.service
    image = aws.call(
        "ecr",
        "batch-get-image",
        "--repository-name",
        repository,
        "--image-ids",
        "imageTag=" + args.tag,
    )["images"][0]
    manifest = json.loads(image["imageManifest"])
    digests = [
        m["digest"]
        for m in manifest.get("manifests", [])
        if m.get("platform", {}).get("os") == "linux"
    ]
    if not digests:
        digests = [image["imageId"]["imageDigest"]]
    scans = []
    for digest in digests:
        result = aws.call(
            "ecr",
            "describe-image-scan-findings",
            "--repository-name",
            repository,
            "--image-id",
            "imageDigest=" + digest,
        )
        counts = result.get("imageScanFindings", {}).get("findingSeverityCounts", {})
        findings = result.get("imageScanFindings", {}).get("findings", [])
        scans.append(
            {
                "image_digest": digest,
                "status": result["imageScanStatus"]["status"],
                "severity_counts": counts,
                "high_or_critical_cves": sorted(
                    {
                        f["name"]
                        for f in findings
                        if f["severity"] in ("HIGH", "CRITICAL")
                    }
                ),
            }
        )
    allowed = all(
        s["status"] == "COMPLETE"
        and not s["severity_counts"].get("HIGH", 0)
        and not s["severity_counts"].get("CRITICAL", 0)
        for s in scans
    )
    report = {
        "service": args.service,
        "tag": args.tag,
        "scope": "ECR basic OS packages only",
        "production_promotion_allowed": allowed,
        "scans": scans,
    }
    out = ROOT / ".aws-local"
    out.mkdir(exist_ok=True)
    (out / "image-promotion-check.json").write_text(
        json.dumps(report, indent=2), encoding="utf8"
    )
    print(json.dumps(report, indent=2))
    if not allowed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
