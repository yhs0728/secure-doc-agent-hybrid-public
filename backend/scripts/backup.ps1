param(
    [string]$Destination = "backups",
    [ValidateRange(1, 3650)][int]$RetentionDays = 14
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$composeFile = Join-Path $repositoryRoot "compose.yaml"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$destinationPath = if ([System.IO.Path]::IsPathRooted($Destination)) { $Destination } else { Join-Path $repositoryRoot $Destination }
$backupRoot = [System.IO.Path]::GetFullPath($destinationPath)
$backupDir = Join-Path $backupRoot $stamp
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

$postgresId = (& docker compose --project-directory $repositoryRoot -f $composeFile ps -q postgres).Trim()
$objectStoreId = (& docker compose --project-directory $repositoryRoot -f $composeFile ps -q minio).Trim()
if (-not $postgresId -or -not $objectStoreId) {
    throw "postgres와 minio 컨테이너가 실행 중이어야 합니다."
}

try {
    & docker compose --project-directory $repositoryRoot -f $composeFile exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/secure-doc.dump'
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL 백업에 실패했습니다." }
    & docker cp "${postgresId}:/tmp/secure-doc.dump" (Join-Path $backupDir "postgres.dump")
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL 백업 복사에 실패했습니다." }

    & docker compose --project-directory $repositoryRoot -f $composeFile exec -T minio sh -c 'tar -czf /tmp/secure-doc-objects.tgz -C /data .'
    if ($LASTEXITCODE -ne 0) { throw "Object Storage 백업에 실패했습니다." }
    & docker cp "${objectStoreId}:/tmp/secure-doc-objects.tgz" (Join-Path $backupDir "object-storage.tgz")
    if ($LASTEXITCODE -ne 0) { throw "Object Storage 백업 복사에 실패했습니다." }

    $files = Get-ChildItem -LiteralPath $backupDir -File | ForEach-Object {
        [ordered]@{
            name = $_.Name
            bytes = $_.Length
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
        }
    }
    $manifest = [ordered]@{
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        git_commit = (& git -C $repositoryRoot rev-parse HEAD).Trim()
        files = @($files)
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $backupDir "manifest.json")
}
finally {
    & docker compose --project-directory $repositoryRoot -f $composeFile exec -T postgres rm -f /tmp/secure-doc.dump 2>$null
    & docker compose --project-directory $repositoryRoot -f $composeFile exec -T minio rm -f /tmp/secure-doc-objects.tgz 2>$null
}

$cutoff = (Get-Date).AddDays(-$RetentionDays)
Get-ChildItem -LiteralPath $backupRoot -Directory | Where-Object {
    $_.LastWriteTime -lt $cutoff -and $_.Name -match '^\d{8}-\d{6}$'
} | Remove-Item -Recurse -Force

Write-Output "Backup completed: $backupDir"
