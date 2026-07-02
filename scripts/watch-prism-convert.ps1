param(
  [string]$Db = "data\prism.sqlite",
  [string]$DataDir = "data",
  [int]$LimitPerBatch = 200,
  [int]$MaxBatches = 20,
  [int]$MinFreeGb = 8,
  [int]$PollSeconds = 60,
  [string]$ArchiveRoot = "C:\gov-rag-portable-archive\$(Get-Date -Format yyyyMMdd)",
  [switch]$SkipFinalBuildKg
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ResolvedRoot = (Resolve-Path -LiteralPath $Root).Path
New-Item -ItemType Directory -Force -Path $ArchiveRoot | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogPath = Join-Path $ArchiveRoot "prism-convert-watch-$Stamp.log"
$StatusPath = Join-Path $ArchiveRoot "prism-convert-watch-$Stamp.status.json"

function Write-WatchLog {
  param([string]$Message)
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss K"), $Message
  Add-Content -Path $LogPath -Value $line -Encoding UTF8
  Write-Host $line
}

function Get-PrismWorker {
  $workers = Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
    Where-Object {
      $_.CommandLine -match "govrag\.prism_cli" -and
      ($_.CommandLine -match "\sconvert\s" -or $_.CommandLine -match "\sbuild-kg(\s|$)")
    } |
    Select-Object ProcessId, ParentProcessId, CommandLine
  return @($workers)
}

function Get-FreeGb {
  $drive = (Get-Item -LiteralPath $ResolvedRoot).PSDrive.Name
  $info = Get-PSDrive -Name $drive
  return [math]::Round(($info.Free / 1GB), 2)
}

function Get-Counts {
  $script = @"
import json
import sqlite3
conn = sqlite3.connect(r"$Db")
cur = conn.cursor()
counts = {}
for table in ["prism_files", "documents", "chunks", "kg_nodes", "kg_edges"]:
    cur.execute(f"select count(*) from {table}")
    counts[table] = cur.fetchone()[0]
for status in ["downloaded", "converted", "failed", "metadata_only"]:
    cur.execute("select count(*) from prism_files where status=?", (status,))
    counts[f"files_{status}"] = cur.fetchone()[0]
print(json.dumps(counts, ensure_ascii=False))
"@
  $tmp = Join-Path $ArchiveRoot "counts-$Stamp.py"
  Set-Content -Encoding UTF8 -Path $tmp -Value $script
  try {
    $json = python $tmp
    return $json | ConvertFrom-Json
  } finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
  }
}

function Invoke-PrismStep {
  param([string]$Name, [string[]]$ArgsList)
  Write-WatchLog "begin $Name $($ArgsList -join ' ')"
  & python @ArgsList 2>&1 | ForEach-Object {
    Add-Content -Path $LogPath -Value $_ -Encoding UTF8
  }
  $exit = $LASTEXITCODE
  Write-WatchLog "complete $Name exit=$exit"
  if ($exit -ne 0) {
    throw "$Name failed with exit code $exit"
  }
}

function Save-Status {
  param([string]$State, [int]$BatchesRun, [object]$Counts, [string]$Message = "")
  [pscustomobject]@{
    state = $State
    message = $Message
    batches_run = $BatchesRun
    max_batches = $MaxBatches
    limit_per_batch = $LimitPerBatch
    min_free_gb = $MinFreeGb
    free_gb = Get-FreeGb
    counts = $Counts
    updated_at = Get-Date -Format o
  } | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -Path $StatusPath
}

Set-Location $ResolvedRoot
$env:PYTHONPATH = "src"
$batchesRun = 0

try {
  Write-WatchLog "watch started root=$ResolvedRoot db=$Db dataDir=$DataDir limitPerBatch=$LimitPerBatch maxBatches=$MaxBatches minFreeGb=$MinFreeGb"

  while ($true) {
    $workers = Get-PrismWorker
    if ($workers.Count -eq 0) {
      break
    }
    $workerList = ($workers | ForEach-Object { "$($_.ProcessId)" }) -join ","
    Write-WatchLog "waiting for existing prism worker pid=$workerList"
    Start-Sleep -Seconds $PollSeconds
  }

  while ($batchesRun -lt $MaxBatches) {
    $freeGb = Get-FreeGb
    $counts = Get-Counts
    Save-Status -State "running" -BatchesRun $batchesRun -Counts $counts -Message "free_gb=$freeGb"

    if ($freeGb -lt $MinFreeGb) {
      Write-WatchLog "stop low disk free_gb=$freeGb min_free_gb=$MinFreeGb"
      Save-Status -State "stopped_low_disk" -BatchesRun $batchesRun -Counts $counts -Message "free_gb=$freeGb"
      exit 2
    }

    if ([int]$counts.files_downloaded -le 0) {
      Write-WatchLog "no downloaded files waiting for conversion"
      break
    }

    $batchesRun += 1
    Invoke-PrismStep "convert" @("-m", "govrag.prism_cli", "convert", "--db", $Db, "--data-dir", $DataDir, "--limit", "$LimitPerBatch")
  }

  $finalCounts = Get-Counts
  if (-not $SkipFinalBuildKg) {
    Invoke-PrismStep "build-kg" @("-m", "govrag.prism_cli", "build-kg", "--db", $Db)
    $finalCounts = Get-Counts
  }
  Save-Status -State "finished" -BatchesRun $batchesRun -Counts $finalCounts
  Write-WatchLog "watch finished batches=$batchesRun"
} catch {
  $counts = $null
  try { $counts = Get-Counts } catch {}
  Save-Status -State "failed" -BatchesRun $batchesRun -Counts $counts -Message $_.Exception.Message
  Write-WatchLog "ERROR $($_.Exception.Message)"
  exit 1
}
