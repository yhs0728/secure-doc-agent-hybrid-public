param(
    [Parameter(Mandatory = $true)][string]$BackupDirectory,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$composeFile = Join-Path $repositoryRoot "compose.yaml"
if (-not $Force) {
    throw "복구는 현재 데이터를 덮어씁니다. 검토 후 -Force를 지정하세요."
}

$backupDir = (Resolve-Path -LiteralPath $BackupDirectory).Path
$manifestPath = Join-Path $backupDir "manifest.json"
$manifest = Get-Content -Raw -Encoding utf8 -LiteralPath $manifestPath | ConvertFrom-Json
foreach ($entry in $manifest.files) {
    $path = Join-Path $backupDir $entry.name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "백업 파일 누락: $($entry.name)" }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    if ($actual -ne $entry.sha256) { throw "백업 checksum 불일치: $($entry.name)" }
}

$postgresId = (& docker compose --project-directory $repositoryRoot -f $composeFile ps -q postgres).Trim()
$objectStoreId = (& docker compose --project-directory $repositoryRoot -f $composeFile ps -q minio).Trim()
if (-not $postgresId -or -not $objectStoreId) {
    throw "postgres와 minio 컨테이너가 실행 중이어야 합니다."
}

& docker compose --project-directory $repositoryRoot -f $composeFile stop api worker gateway
try {
    & docker cp (Join-Path $backupDir "postgres.dump") "${postgresId}:/tmp/secure-doc.dump"
    & docker compose --project-directory $repositoryRoot -f $composeFile exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner /tmp/secure-doc.dump'
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL 복구에 실패했습니다." }

    & docker cp (Join-Path $backupDir "object-storage.tgz") "${objectStoreId}:/tmp/secure-doc-objects.tgz"
    & docker compose --project-directory $repositoryRoot -f $composeFile exec -T minio sh -c 'find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar -xzf /tmp/secure-doc-objects.tgz -C /data'
    if ($LASTEXITCODE -ne 0) { throw "Object Storage 복구에 실패했습니다." }
}
finally {
    & docker compose --project-directory $repositoryRoot -f $composeFile exec -T postgres rm -f /tmp/secure-doc.dump 2>$null
    & docker compose --project-directory $repositoryRoot -f $composeFile exec -T minio rm -f /tmp/secure-doc-objects.tgz 2>$null
    & docker compose --project-directory $repositoryRoot -f $composeFile start api worker gateway
}

Write-Output "Restore completed from: $backupDir"
