import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from aws_release import verify_remote_image


def test_oci_index_image_identity_is_verified_by_descriptor():
    # Modern containerd-backed Docker exposes index digest as image.Id.
    local = {
        "Id": "sha256:index",
        "Descriptor": {
            "digest": "sha256:index",
            "mediaType": "application/vnd.oci.image.index.v1+json",
        },
    }
    remote = {
        "imageId": {"imageDigest": "sha256:index"},
        "imageManifest": json.dumps(
            {"mediaType": local["Descriptor"]["mediaType"], "manifests": []}
        ),
    }
    assert verify_remote_image(local, remote) == "oci_descriptor_digest"
    remote["imageId"]["imageDigest"] = "sha256:other"
    with pytest.raises(ValueError, match="descriptor"):
        verify_remote_image(local, remote)


def test_legacy_docker_identity_is_verified_by_config():
    local = {"Id": "sha256:config"}
    remote = {
        "imageId": {"imageDigest": "sha256:manifest"},
        "imageManifest": json.dumps({"config": {"digest": "sha256:config"}}),
    }
    assert verify_remote_image(local, remote) == "legacy_configuration_digest"
    remote["imageManifest"] = json.dumps({"config": {"digest": "sha256:other"}})
    with pytest.raises(ValueError, match="configuration"):
        verify_remote_image(local, remote)


def test_oci_media_type_mismatch_is_rejected():
    local = {
        "Id": "sha256:index",
        "Descriptor": {"digest": "sha256:index", "mediaType": "index"},
    }
    remote = {
        "imageId": {"imageDigest": "sha256:index"},
        "imageManifest": json.dumps({"mediaType": "manifest"}),
    }
    with pytest.raises(ValueError, match="descriptor"):
        verify_remote_image(local, remote)
