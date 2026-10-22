param(
    [string]$HostUrl = "http://localhost:8000",
    [ValidateRange(1, 10000)][int]$Users = 100,
    [ValidateRange(1, 1000)][int]$SpawnRate = 10,
    [string]$RunTime = "10m",
    [ValidateSet("read", "rag")][string]$Scenario = "read",
    [string]$Python = "",
    [switch]$SkipWarmup
)

$ErrorActionPreference = "Stop"
$backendRoot = Split-Path -Parent $PSScriptRoot
$repositoryRoot = Split-Path -Parent $backendRoot
if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = Join-Path $backendRoot ".venv-load\Scripts\python.exe"
}
if (-not $env:LOAD_TEST_TOKEN -and (-not $env:LOAD_TEST_EMAIL -or -not $env:LOAD_TEST_PASSWORD)) {
    throw "LOAD_TEST_TOKEN 또는 LOAD_TEST_EMAIL/LOAD_TEST_PASSWORD를 설정하세요."
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "부하 테스트 Python을 찾을 수 없습니다: $Python"
}

if ($Scenario -eq "rag" -and -not $SkipWarmup -and $env:LOAD_TEST_TOKEN) {
    $headers = @{ Authorization = "Bearer $($env:LOAD_TEST_TOKEN)" }
    $body = @{ question = "원격 접속 보안 정책을 요약해 주세요." } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri "$HostUrl/api/v1/questions" `
        -Headers $headers -ContentType "application/json" -Body $body -TimeoutSec 300 | Out-Null
    Write-Output "RAG warm-up completed."
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$reportDir = Join-Path (Join-Path $repositoryRoot "load-results") "$stamp-$Scenario"
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
$prefix = Join-Path $reportDir "results"

& $Python -m locust -f (Join-Path $backendRoot "tests/load/locustfile.py") --host $HostUrl `
    --users $Users --spawn-rate $SpawnRate --run-time $RunTime `
    --tags $Scenario --headless --csv $prefix --html "$prefix.html"
if ($LASTEXITCODE -ne 0) { throw "Locust 부하 테스트가 실패했습니다." }

Write-Output "Load test report: $reportDir"
