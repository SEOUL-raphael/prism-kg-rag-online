param(
  [string]$Db = "data\prism.sqlite",
  [string]$DataDir = "data",
  [int]$DailyLimit = 900,
  [int]$EnrichLimit = 900,
  [switch]$SkipApi
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path "logs")) {
  New-Item -ItemType Directory -Path "logs" | Out-Null
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogPath = Join-Path $Root ("logs\prism-continuation-{0}.log" -f $Stamp)
$StatusPath = Join-Path $Root ("logs\prism-continuation-{0}.status.json" -f $Stamp)

function Write-RunLog {
  param([string]$Message)
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss K"), $Message
  Add-Content -Path $LogPath -Value $line -Encoding UTF8
  Write-Host $line
}

function Invoke-Step {
  param(
    [string]$Name,
    [string[]]$ArgsList
  )
  Write-RunLog "begin $Name"
  & $Python @ArgsList 2>&1 | Tee-Object -FilePath $LogPath -Append
  if ($LASTEXITCODE -ne 0) {
    throw "$Name failed with exit code $LASTEXITCODE"
  }
  Write-RunLog "complete $Name"
}

$Python = "python"
if (Test-Path ".\.venv\Scripts\python.exe") {
  $Python = ".\.venv\Scripts\python.exe"
}

$env:PYTHONPATH = "src"

Write-RunLog "start db=$Db dataDir=$DataDir dailyLimit=$DailyLimit enrichLimit=$EnrichLimit skipApi=$SkipApi"

try {
  Invoke-Step "status-before" @("-m", "govrag.prism_cli", "status", "--db", $Db)

  if (-not $SkipApi) {
    if (-not $env:PRISM_API_KEY) {
      throw "PRISM_API_KEY is not configured in the execution environment."
    }
    Invoke-Step "enrich" @(
      "-m", "govrag.prism_cli", "enrich",
      "--db", $Db,
      "--limit", "$EnrichLimit",
      "--daily-limit", "$DailyLimit"
    )
  }

  Invoke-Step "download" @(
    "-m", "govrag.prism_cli", "download",
    "--db", $Db,
    "--data-dir", $DataDir
  )
  Invoke-Step "convert" @(
    "-m", "govrag.prism_cli", "convert",
    "--db", $Db,
    "--data-dir", $DataDir
  )
  Invoke-Step "build-kg" @(
    "-m", "govrag.prism_cli", "build-kg",
    "--db", $Db
  )

  & $Python -m govrag.prism_cli status --db $Db | Set-Content -Encoding UTF8 $StatusPath
  Write-RunLog "status saved $StatusPath"
  Write-RunLog "stop ok"
} catch {
  Write-RunLog "ERROR $($_.Exception.Message)"
  try {
    & $Python -m govrag.prism_cli status --db $Db | Set-Content -Encoding UTF8 $StatusPath
    Write-RunLog "status saved $StatusPath"
  } catch {
    Write-RunLog "status save failed $($_.Exception.Message)"
  }
  exit 1
}
