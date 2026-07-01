param(
  [string]$Python = "python",
  [switch]$NoPdf
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv")) {
  & $Python -m venv .venv
}

if ($NoPdf) {
  & .\.venv\Scripts\python -m pip install .
} else {
  & .\.venv\Scripts\python -m pip install ".[pdf]"
}

if (-not (Test-Path ".\configs\sources.local.json")) {
  Copy-Item ".\configs\sources.example.json" ".\configs\sources.local.json"
}
if (-not (Test-Path ".\configs\runtime.local.env")) {
  Copy-Item ".\configs\runtime.example.env" ".\configs\runtime.local.env"
}

& .\.venv\Scripts\python -m govrag init-db
Write-Host "Ready. Edit configs\sources.local.json and configs\runtime.local.env next."
