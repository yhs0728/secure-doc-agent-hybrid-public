import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "hybrid_release_cache", ROOT / "tools/release_cache.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
IMAGE = "sha256:" + "a" * 64


def test_tampered_archive_is_rejected_before_docker_load(tmp_path, monkeypatch):
    (tmp_path / "images.tar").write_bytes(b"original")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "images": {"conversation": IMAGE},
                "archive_sha256": module.sha256(tmp_path / "images.tar"),
            }
        )
    )
    (tmp_path / "images.tar").write_bytes(b"tampered")
    monkeypatch.setattr(
        module, "docker", lambda *args: pytest.fail("Must verify before Docker load")
    )
    with pytest.raises(ValueError, match="checksum"):
        module.restore(tmp_path, apply=True)


@pytest.mark.parametrize(
    "images",
    [
        {"postgres": IMAGE},
        {"conversation": "latest"},
        {"knowledge": IMAGE},
        {"knowledge": IMAGE, "knowledge-worker": "sha256:" + "b" * 64},
    ],
)
def test_invalid_patch_boundaries_are_rejected(images):
    with pytest.raises(ValueError):
        module.validate_images(images)


def test_dry_restore_is_non_mutating(tmp_path, monkeypatch):
    (tmp_path / "images.tar").write_bytes(b"archive")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "images": {"conversation": IMAGE},
                "archive_sha256": module.sha256(tmp_path / "images.tar"),
            }
        )
    )
    monkeypatch.setattr(
        module, "docker", lambda *args: pytest.fail("Dry-run must not use Docker")
    )
    result = module.restore(tmp_path)
    assert result["services"]["conversation"] == {
        "image": IMAGE,
        "pull_policy": "never",
    }
    assert not (tmp_path / "compose.images.json").exists()
