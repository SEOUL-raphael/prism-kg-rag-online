param(
  [string]$Python = "python",
  [switch]$NoPdf,
  [switch]$Prism
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path "wheelhouse")) {
  New-Item -ItemType Directory -Path "wheelhouse" | Out-Null
}

function Invoke-Native {
  param(
    [string]$Exe,
    [string[]]$ArgsList
  )
  & $Exe @ArgsList
  if ($LASTEXITCODE -ne 0) {
    throw "$Exe $($ArgsList -join ' ') failed with exit code $LASTEXITCODE"
  }
}

Invoke-Native $Python @("-m", "pip", "install", "--upgrade", "build", "pip")
Invoke-Native $Python @("-m", "build", "--wheel")

if ($Prism) {
  Invoke-Native $Python @("-m", "pip", "download", "--dest", "wheelhouse", ".[pdf,prism]")
} elseif ($NoPdf) {
  Invoke-Native $Python @("-m", "pip", "download", "--dest", "wheelhouse", ".")
} else {
  Invoke-Native $Python @("-m", "pip", "download", "--dest", "wheelhouse", ".[pdf]")
}

Copy-Item dist\*.whl wheelhouse\ -Force
Write-Host "Offline package ready in wheelhouse\"
