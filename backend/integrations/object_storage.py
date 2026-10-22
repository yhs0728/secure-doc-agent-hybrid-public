from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from config.settings import Settings


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    etag: str | None
    version_id: str
    size_bytes: int


class S3ObjectStore:
    def __init__(self, client: BaseClient, bucket: str) -> None:
        self._client = client
        self.bucket = bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> S3ObjectStore:
        if settings.object_storage_access_key is None:
            raise ValueError("Object Storage access key가 없습니다.")
        if settings.object_storage_secret_key is None:
            raise ValueError("Object Storage secret key가 없습니다.")
        client = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint_url,
            region_name=settings.object_storage_region,
            aws_access_key_id=settings.object_storage_access_key.get_secret_value(),
            aws_secret_access_key=(
                settings.object_storage_secret_key.get_secret_value()
            ),
            use_ssl=settings.object_storage_secure,
        )
        return cls(client, settings.object_storage_bucket)

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            self._client.create_bucket(Bucket=self.bucket)

    def healthcheck(self) -> bool:
        """Check bucket access without creating or modifying objects."""
        try:
            self._client.head_bucket(Bucket=self.bucket)
            return True
        except ClientError:
            return False

    def upload(self, source: Path, key: str, checksum_sha256: str) -> StoredObject:
        self.ensure_bucket()
        with source.open("rb") as stream:
            response = self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=stream,
                Metadata={"sha256": checksum_sha256},
            )
        head = self._client.head_object(Bucket=self.bucket, Key=key)
        if head.get("Metadata", {}).get("sha256") != checksum_sha256:
            raise RuntimeError("Object Storage checksum 검증에 실패했습니다.")
        return StoredObject(
            bucket=self.bucket,
            key=key,
            etag=_strip_quotes(response.get("ETag")),
            version_id=str(response.get("VersionId") or ""),
            size_bytes=int(head["ContentLength"]),
        )

    def delete(self, key: str, version_id: str = "") -> None:
        arguments = {"Bucket": self.bucket, "Key": key}
        if version_id:
            arguments["VersionId"] = version_id
        self._client.delete_object(**arguments)

    def exists(self, key: str, checksum_sha256: str | None = None) -> bool:
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return checksum_sha256 is None or (
            response.get("Metadata", {}).get("sha256") == checksum_sha256
        )


def _strip_quotes(value: object) -> str | None:
    return str(value).strip('"') if value else None
