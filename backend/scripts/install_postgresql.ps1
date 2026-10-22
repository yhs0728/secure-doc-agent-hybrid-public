[CmdletBinding()]
param(
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$BackendRoot = Join-Path $ProjectRoot "backend"

function New-RandomPassword {
    return ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code: $LASTEXITCODE)"
    }
}

function Reset-LocalPostgresPassword {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PsqlPath,
        [Parameter(Mandatory = $true)]
        [string]$ServiceName,
        [Parameter(Mandatory = $true)]
        [string]$NewPassword
    )

    $hbaPath = "C:\Program Files\PostgreSQL\17\data\pg_hba.conf"
    $backupPath = "$hbaPath.secure-doc-backup"
    $pgCtlPath = Join-Path (Split-Path -Parent $PsqlPath) "pg_ctl.exe"
    if (-not (Test-Path -LiteralPath $hbaPath)) {
        throw "pg_hba.conf was not found."
    }

    $original = [IO.File]::ReadAllText($hbaPath)
    $trusted = [regex]::Replace(
        $original,
        "(?m)^(\s*host\s+all\s+all\s+(?:127\.0\.0\.1/32|::1/128)\s+)\S+.*$",
        '${1}trust'
    )
    if ($trusted -eq $original) {
        throw "Local pg_hba.conf entries could not be identified safely."
    }

    [IO.File]::Copy($hbaPath, $backupPath, $true)
    try {
        $utf8WithoutBom = [Text.UTF8Encoding]::new($false)
        [IO.File]::WriteAllText($hbaPath, $trusted, $utf8WithoutBom)
        & $pgCtlPath reload -D "C:\Program Files\PostgreSQL\17\data"
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to reload temporary local authentication settings."
        }
        & $PsqlPath -v ON_ERROR_STOP=1 -h localhost -p 5432 -U postgres -d postgres -c "ALTER ROLE postgres WITH PASSWORD '$NewPassword'"
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to reset the local postgres password."
        }
    } finally {
        [IO.File]::Copy($backupPath, $hbaPath, $true)
        [IO.File]::Delete($backupPath)
        & $pgCtlPath reload -D "C:\Program Files\PostgreSQL\17\data"
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to restore local authentication settings."
        }
    }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "This installer must run from an elevated PowerShell process."
}

$transcriptPath = Join-Path $env:TEMP "secure-doc-postgresql-install.log"
Start-Transcript -Path $transcriptPath -Force | Out-Null

$postgresPassword = New-RandomPassword
$applicationPassword = New-RandomPassword

Write-Host "[1/6] Installing PostgreSQL 17..."
choco install postgresql17 --params "/Password:$postgresPassword /Port:5432" --yes --no-progress
if ($LASTEXITCODE -notin @(0, 1641, 3010)) {
    throw "Chocolatey installation failed (exit code: $LASTEXITCODE)"
}

$psql = "C:\Program Files\PostgreSQL\17\bin\psql.exe"
if (-not (Test-Path -LiteralPath $psql)) {
    throw "PostgreSQL psql executable was not installed."
}

Write-Host "[2/6] Starting and probing the PostgreSQL service..."
$service = Get-Service | Where-Object { $_.Name -like "postgresql*17*" } | Select-Object -First 1
if ($null -eq $service) {
    throw "PostgreSQL 17 Windows service was not found."
}
if ($service.Status -ne "Running") {
    Start-Service -Name $service.Name
}

$env:PGPASSWORD = $postgresPassword
$ready = $false
for ($attempt = 0; $attempt -lt 5; $attempt++) {
    $savedErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $probe = & $psql -h localhost -p 5432 -U postgres -d postgres -tAc "SELECT 1" 2>$null
    $probeExitCode = $LASTEXITCODE
    $ErrorActionPreference = $savedErrorActionPreference
    if ($probeExitCode -eq 0 -and ([string]$probe).Trim() -eq "1") {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $ready) {
    Write-Host "Existing administrator credential is unavailable; resetting it through temporary local trust authentication..."
    Reset-LocalPostgresPassword -PsqlPath $psql -ServiceName $service.Name -NewPassword $postgresPassword
    $env:PGPASSWORD = $postgresPassword
    $probe = & $psql -h localhost -p 5432 -U postgres -d postgres -tAc "SELECT 1"
    if ($LASTEXITCODE -ne 0 -or $probe.Trim() -ne "1") {
        throw "PostgreSQL did not accept the reset administrator credential."
    }
}

Write-Host "[3/6] Creating the least-privilege application role and database..."
[string]$roleExists = & $psql -h localhost -p 5432 -U postgres -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname = 'secure_doc'"
if ($roleExists.Trim() -eq "1") {
    Invoke-Checked -FailureMessage "Failed to update application role" -Command {
        & $psql -v ON_ERROR_STOP=1 -h localhost -p 5432 -U postgres -d postgres -c "ALTER ROLE secure_doc WITH LOGIN PASSWORD '$applicationPassword' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
    }
} else {
    Invoke-Checked -FailureMessage "Failed to create application role" -Command {
        & $psql -v ON_ERROR_STOP=1 -h localhost -p 5432 -U postgres -d postgres -c "CREATE ROLE secure_doc LOGIN PASSWORD '$applicationPassword' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
    }
}

[string]$databaseExists = & $psql -h localhost -p 5432 -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = 'secure_doc_agent'"
if ($databaseExists.Trim() -eq "1") {
    Invoke-Checked -FailureMessage "Failed to update database ownership" -Command {
        & $psql -v ON_ERROR_STOP=1 -h localhost -p 5432 -U postgres -d postgres -c "ALTER DATABASE secure_doc_agent OWNER TO secure_doc"
    }
} else {
    Invoke-Checked -FailureMessage "Failed to create application database" -Command {
        & $psql -v ON_ERROR_STOP=1 -h localhost -p 5432 -U postgres -d postgres -c "CREATE DATABASE secure_doc_agent OWNER secure_doc ENCODING 'UTF8' TEMPLATE template0"
    }
}

$listenAddresses = (& $psql -h localhost -p 5432 -U postgres -d postgres -tAc "SHOW listen_addresses").Trim()
if ($listenAddresses -ne "localhost") {
    Invoke-Checked -FailureMessage "Failed to restrict PostgreSQL network binding" -Command {
        & $psql -v ON_ERROR_STOP=1 -h localhost -p 5432 -U postgres -d postgres -c "ALTER SYSTEM SET listen_addresses TO 'localhost'"
    }
    Stop-Service -Name $service.Name
    $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Stopped, [TimeSpan]::FromSeconds(30))
    Start-Service -Name $service.Name
    $service.WaitForStatus([System.ServiceProcess.ServiceControllerStatus]::Running, [TimeSpan]::FromSeconds(30))
}

Write-Host "[4/6] Storing local credentials and database settings..."
$pgpassDirectory = Join-Path $env:APPDATA "postgresql"
[void][IO.Directory]::CreateDirectory($pgpassDirectory)
$pgpassPath = Join-Path $pgpassDirectory "pgpass.conf"
$pgpassContent = @(
    "localhost:5432:secure_doc_agent:secure_doc:$applicationPassword"
    "localhost:5432:postgres:postgres:$postgresPassword"
) -join "`r`n"
[IO.File]::WriteAllText($pgpassPath, "$pgpassContent`r`n", [Text.Encoding]::ASCII)
$account = "$env:USERDOMAIN\$env:USERNAME"
& icacls.exe $pgpassPath /inheritance:r /grant:r "${account}:(F)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to protect pgpass.conf."
}

$databaseUrl = "postgresql+psycopg://secure_doc@localhost:5432/secure_doc_agent"
[Environment]::SetEnvironmentVariable("DATABASE_ENABLED", "true", "User")
[Environment]::SetEnvironmentVariable("DATABASE_URL", $databaseUrl, "User")
$env:DATABASE_ENABLED = "true"
$env:DATABASE_URL = $databaseUrl
Remove-Item Env:PGPASSWORD

Write-Host "[5/6] Applying schema and importing existing document metadata..."
Set-Location -LiteralPath $BackendRoot
$python = Join-Path $BackendRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment was not found: $python"
}
Invoke-Checked -FailureMessage "Alembic migration failed" -Command {
    & $python -m alembic upgrade head
}
Invoke-Checked -FailureMessage "Database bootstrap failed" -Command {
    & $python -m database.bootstrap
}
Invoke-Checked -FailureMessage "Legacy metadata import failed" -Command {
    & $python -m database.import_legacy
}

Write-Host "[6/6] Verifying the installed database..."
Invoke-Checked -FailureMessage "Database verification failed" -Command {
    & $python -m database.verify
}

$service = Get-Service -Name $service.Name
Write-Host "POSTGRES_SERVICE=$($service.Name)"
Write-Host "POSTGRES_STATUS=$($service.Status)"
Write-Host "DATABASE=secure_doc_agent"
Write-Host "ROLE=secure_doc"
Write-Host "CREDENTIALS=stored-in-user-pgpass"
Write-Host "INSTALL_AND_BOOTSTRAP=OK"
Stop-Transcript | Out-Null
