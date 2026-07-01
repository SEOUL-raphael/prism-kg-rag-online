param(
  [string]$Config = ".\configs\sources.local.json",
  [Nullable[int]]$Year = $null,
  [int]$FromYear = 2026,
  [int]$MaxPages = 2,
  [switch]$DownloadAttachments
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

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

& .\.venv\Scripts\python @argsList
& .\.venv\Scripts\python -m govrag parse-pdfs
& .\.venv\Scripts\python -m govrag index
