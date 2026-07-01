param(
  [string]$Config = ".\configs\sources.local.json",
  [Nullable[int]]$Year = $null,
  [int]$FromYear = 2026,
  [int]$MaxPages = 5,
  [int]$IntervalMinutes = 120,
  [datetime]$StopAt = "2026-06-29T08:45:00+09:00",
  [switch]$DownloadAttachments
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path "logs")) {
  New-Item -ItemType Directory -Path "logs" | Out-Null
}

$LogPath = Join-Path $Root ("logs\harvest-loop-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))

function Write-LoopLog {
  param([string]$Message)
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss K"), $Message
  Add-Content -Path $LogPath -Value $line -Encoding UTF8
  Write-Host $line
}

Write-LoopLog "start config=$Config year=$Year fromYear=$FromYear maxPages=$MaxPages stopAt=$StopAt"

while ((Get-Date) -lt $StopAt) {
  try {
    $argsList = @(
      "-m", "govrag", "harvest",
      "--config", $Config,
      "--max-pages", "$MaxPages"
    )
    if ($null -ne $Year) {
      $argsList += @("--year", "$Year")
    } else {
      $argsList += @("--from-year", "$FromYear")
    }
    if ($DownloadAttachments) {
      $argsList += "--download-attachments"
    }

    Write-LoopLog "harvest cycle begin"
    & .\.venv\Scripts\python @argsList 2>&1 | Tee-Object -FilePath $LogPath -Append
    & .\.venv\Scripts\python -m govrag parse-pdfs 2>&1 | Tee-Object -FilePath $LogPath -Append
    & .\.venv\Scripts\python -m govrag index 2>&1 | Tee-Object -FilePath $LogPath -Append
    & .\.venv\Scripts\python -m govrag export-jsonl --out exports\ragflow-import.jsonl 2>&1 | Tee-Object -FilePath $LogPath -Append
    Write-LoopLog "harvest cycle complete"
  } catch {
    Write-LoopLog "ERROR $($_.Exception.Message)"
  }

  $next = (Get-Date).AddMinutes($IntervalMinutes)
  if ($next -ge $StopAt) {
    break
  }
  Write-LoopLog "sleep $IntervalMinutes minutes"
  Start-Sleep -Seconds ($IntervalMinutes * 60)
}

Write-LoopLog "stop"
