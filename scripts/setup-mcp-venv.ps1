param(
  [string]$Venv = ".venv-mcp"
)

$ErrorActionPreference = "Stop"

$python = $null
foreach ($candidate in @("py -3.10", "python")) {
  try {
    $version = Invoke-Expression "$candidate -c `"import sys; print(sys.version_info[:2])`""
    if ($version -match "\(3,\s*(1[0-9]|[2-9][0-9])\)") {
      $python = $candidate
      break
    }
  } catch {
  }
}

if (-not $python) {
  throw "Python 3.10+ 실행기를 찾지 못했습니다. Python 3.10 이상을 설치한 뒤 다시 실행하세요."
}

Invoke-Expression "$python -m venv `"$Venv`""
& "$Venv\Scripts\python.exe" -m pip install --upgrade pip
& "$Venv\Scripts\python.exe" -m pip install -e ".[mcp]"

Write-Host "MCP venv ready: $Venv"
Write-Host "$Venv\Scripts\python.exe -m govrag.prism_cli mcp --db data\prism.sqlite --transport stdio"
Write-Host "$Venv\Scripts\python.exe -m govrag.prism_cli mcp --db data\prism.sqlite --transport http --host 127.0.0.1 --port 8877"
