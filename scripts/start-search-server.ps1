param(
  [string]$HostName = "127.0.0.1",
  [int]$Port = 8765,
  [switch]$Ollama
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$argsList = @("-m", "govrag", "serve", "--host", $HostName, "--port", "$Port")
if ($Ollama) {
  $argsList += "--ollama"
}

& .\.venv\Scripts\python @argsList
