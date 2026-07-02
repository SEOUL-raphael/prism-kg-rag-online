param(
  [string]$Db = "data\prism.sqlite",
  [string]$DataDir = "data",
  [int]$Limit = 200,
  [string]$ArchiveRoot = "C:\gov-rag-portable-archive\$(Get-Date -Format yyyyMMdd)",
  [switch]$SkipBuildKg
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ResolvedRoot = (Resolve-Path -LiteralPath $Root).Path

New-Item -ItemType Directory -Force -Path $ArchiveRoot | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutLog = Join-Path $ArchiveRoot "prism-convert-resume-$Stamp.out.log"
$ErrLog = Join-Path $ArchiveRoot "prism-convert-resume-$Stamp.err.log"
$StatusPath = Join-Path $ArchiveRoot "prism-convert-resume-$Stamp.exit.json"
$ScriptPath = Join-Path $ArchiveRoot "run-convert-resume-$Stamp.ps1"

$buildBlock = @"
`$buildExit = `$null
if (`$convertExit -eq 0) {
  python -m govrag.prism_cli build-kg --db "$Db"
  `$buildExit = `$LASTEXITCODE
}
"@
if ($SkipBuildKg) {
  $buildBlock = "`$buildExit = `$null"
}

$script = @"
`$ErrorActionPreference = 'Continue'
Set-Location '$ResolvedRoot'
`$env:PYTHONPATH = 'src'
`$started = Get-Date -Format o
python -m govrag.prism_cli convert --db "$Db" --data-dir "$DataDir" --limit $Limit
`$convertExit = `$LASTEXITCODE
$buildBlock
[pscustomobject]@{
  started_at = `$started
  finished_at = (Get-Date -Format o)
  convert_exit = `$convertExit
  build_kg_exit = `$buildExit
  limit = $Limit
} | ConvertTo-Json | Set-Content -Encoding UTF8 -Path '$StatusPath'
"@

Set-Content -Encoding UTF8 -Path $ScriptPath -Value $script
$proc = Start-Process -FilePath powershell -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ScriptPath) -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru -WindowStyle Hidden

[pscustomobject]@{
  pid = $proc.Id
  script = $ScriptPath
  stdout = $OutLog
  stderr = $ErrLog
  status = $StatusPath
} | ConvertTo-Json -Depth 3
