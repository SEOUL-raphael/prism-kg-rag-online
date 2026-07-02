param(
  [string]$ProjectRef = "ltmrtmavgjlflvcbahpy",
  [string]$SnapshotDir = "exports\supabase",
  [int]$BatchSize = 1000,
  [string]$MinimaxModel = $(if ($env:MINIMAX_MODEL) { $env:MINIMAX_MODEL } else { "MiniMax-Text-01" }),
  [switch]$SkipDbPush,
  [switch]$SkipFunction,
  [switch]$SkipLoad,
  [switch]$VerifyLoad
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step {
  param([string]$Message)
  Write-Host ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss K"), $Message)
}

function Require-Env {
  param([string]$Name)
  if (-not [Environment]::GetEnvironmentVariable($Name, "Process")) {
    throw "$Name is required in the current process environment."
  }
}

function Test-SupabaseManagementAuth {
  $oldPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & npx supabase projects list --output json 1>$null 2>$null
    return $LASTEXITCODE -eq 0
  } finally {
    $ErrorActionPreference = $oldPreference
  }
}

Write-Step "checking Supabase CLI"
& npx supabase --version | Out-Null

if (-not (Test-SupabaseManagementAuth)) {
  if (-not $env:SUPABASE_ACCESS_TOKEN) {
    throw "Supabase management auth is missing. Set SUPABASE_ACCESS_TOKEN, then rerun this script."
  }
  Write-Step "logging in to Supabase CLI with SUPABASE_ACCESS_TOKEN"
  & npx supabase login --token $env:SUPABASE_ACCESS_TOKEN | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "supabase login failed."
  }
}

$linkArgs = @("supabase", "link", "--project-ref", $ProjectRef, "--yes")
if ($env:SUPABASE_DB_PASSWORD) {
  $linkArgs += @("--password", $env:SUPABASE_DB_PASSWORD)
}
Write-Step "linking Supabase project $ProjectRef"
& npx @linkArgs | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "supabase link failed. If this prompts for a DB password, set SUPABASE_DB_PASSWORD."
}

if (-not $SkipDbPush) {
  $pushArgs = @("supabase", "db", "push", "--linked", "--yes")
  if ($env:SUPABASE_DB_PASSWORD) {
    $pushArgs += @("--password", $env:SUPABASE_DB_PASSWORD)
  }
  Write-Step "pushing Supabase migrations"
  & npx @pushArgs
  if ($LASTEXITCODE -ne 0) {
    throw "supabase db push failed."
  }
}

if (-not $SkipFunction) {
  Require-Env "MINIMAX_API_KEY"
  if (-not $env:SUPABASE_PUBLISHABLE_KEY -and $env:VITE_SUPABASE_PUBLISHABLE_KEY) {
    $env:SUPABASE_PUBLISHABLE_KEY = $env:VITE_SUPABASE_PUBLISHABLE_KEY
  }
  Require-Env "SUPABASE_PUBLISHABLE_KEY"

  Write-Step "setting Edge Function secrets"
  & npx supabase secrets set --project-ref $ProjectRef `
    "MINIMAX_API_KEY=$env:MINIMAX_API_KEY" `
    "SUPABASE_PUBLISHABLE_KEY=$env:SUPABASE_PUBLISHABLE_KEY" `
    "MINIMAX_MODEL=$MinimaxModel" | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "supabase secrets set failed."
  }

  Write-Step "deploying rag-query Edge Function"
  & npx supabase functions deploy rag-query --project-ref $ProjectRef --use-api
  if ($LASTEXITCODE -ne 0) {
    throw "supabase functions deploy failed."
  }
}

if (-not $SkipLoad) {
  Require-Env "SUPABASE_URL"
  if (-not $env:SUPABASE_SECRET_KEY -and -not $env:SUPABASE_SERVICE_ROLE_KEY) {
    throw "SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY is required for snapshot loading."
  }
  if (-not (Test-Path -LiteralPath $SnapshotDir)) {
    throw "Snapshot directory not found: $SnapshotDir"
  }
  Write-Step "loading JSONL snapshot into Supabase"
  $loadArgs = @("scripts\load_supabase_snapshot.py", "--dir", $SnapshotDir, "--batch-size", "$BatchSize")
  if ($VerifyLoad) {
    $loadArgs += "--verify"
  }
  & python @loadArgs
  if ($LASTEXITCODE -ne 0) {
    throw "snapshot load failed."
  }
}

Write-Step "Supabase online deployment finished"
