param(
  [string]$Repo = "SEOUL-raphael/prism-kg-rag-online",
  [string]$ProjectRef = "ltmrtmavgjlflvcbahpy",
  [string]$SupabaseUrl = $env:SUPABASE_URL
)

$ErrorActionPreference = "Continue"

function Add-Check {
  param(
    [System.Collections.ArrayList]$Checks,
    [string]$Name,
    [bool]$Ok,
    [string]$Message
  )
  [void]$Checks.Add([pscustomobject]@{
    name = $Name
    ok = $Ok
    message = $Message
  })
}

function Invoke-Capture {
  param([scriptblock]$Block)
  try {
    $output = & $Block 2>&1
    return [pscustomobject]@{ exit = $LASTEXITCODE; output = ($output -join "`n") }
  } catch {
    return [pscustomobject]@{ exit = 1; output = $_.Exception.Message }
  }
}

$checks = [System.Collections.ArrayList]::new()

$gh = Invoke-Capture { gh auth status }
Add-Check $checks "github_auth" ($gh.exit -eq 0) ($(if ($gh.exit -eq 0) { "gh is authenticated" } else { "gh auth status failed" }))

$repoInfo = Invoke-Capture { gh repo view $Repo --json nameWithOwner,visibility,defaultBranchRef,url }
Add-Check $checks "github_repo" ($repoInfo.exit -eq 0) ($(if ($repoInfo.exit -eq 0) { "repository is reachable" } else { "repository is not reachable" }))

$pages = Invoke-Capture { gh api "repos/$Repo/pages" }
if ($pages.exit -eq 0) {
  Add-Check $checks "github_pages" $true "GitHub Pages is enabled"
} elseif ($pages.output -match "Not Found") {
  $enable = Invoke-Capture { gh api "repos/$Repo/pages" --method POST -f build_type=workflow }
  if ($enable.exit -eq 0) {
    Add-Check $checks "github_pages" $true "GitHub Pages was enabled with workflow build type"
  } elseif ($enable.output -match "current plan does not support") {
    Add-Check $checks "github_pages" $false "current GitHub plan does not support Pages for this private repository"
  } else {
    Add-Check $checks "github_pages" $false "GitHub Pages is not enabled and automatic enable failed"
  }
} else {
  Add-Check $checks "github_pages" $false "GitHub Pages status check failed"
}

$secrets = Invoke-Capture { gh api "repos/$Repo/actions/secrets" --jq ".secrets[].name" }
$hasFrontendSecrets = ($secrets.exit -eq 0 -and $secrets.output -match "VITE_SUPABASE_URL" -and $secrets.output -match "VITE_SUPABASE_PUBLISHABLE_KEY")
Add-Check $checks "github_frontend_secrets" $hasFrontendSecrets ($(if ($hasFrontendSecrets) { "frontend secrets are configured" } else { "frontend secrets are missing" }))

$supabaseCli = Invoke-Capture { npx supabase --version }
Add-Check $checks "supabase_cli" ($supabaseCli.exit -eq 0) ($(if ($supabaseCli.exit -eq 0) { "supabase CLI is available via npx" } else { "supabase CLI is not available" }))

$projects = Invoke-Capture { npx supabase projects list --output json }
Add-Check $checks "supabase_management_auth" ($projects.exit -eq 0) ($(if ($projects.exit -eq 0) { "Supabase management API is authenticated" } else { "Supabase access token is missing or unauthorized" }))

$adminKeys = @()
if ($env:SUPABASE_SECRET_KEY) {
  $adminKeys += [pscustomobject]@{ name = "SUPABASE_SECRET_KEY"; value = $env:SUPABASE_SECRET_KEY }
}
if ($env:SUPABASE_SERVICE_ROLE_KEY) {
  $adminKeys += [pscustomobject]@{ name = "SUPABASE_SERVICE_ROLE_KEY"; value = $env:SUPABASE_SERVICE_ROLE_KEY }
}
Add-Check $checks "supabase_admin_key" ($adminKeys.Count -gt 0) ($(if ($adminKeys.Count -gt 0) { (($adminKeys | ForEach-Object { $_.name }) -join ", ") + " present in environment" } else { "SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY is missing" }))

if ($SupabaseUrl -and $adminKeys.Count -gt 0) {
  $schemaChecked = $false
  foreach ($entry in $adminKeys) {
    try {
      $headers = @{
        "apikey" = $entry.value
        "Authorization" = "Bearer $($entry.value)"
        "Prefer" = "count=exact"
      }
      $response = Invoke-WebRequest `
        -Method Get `
        -Uri "$($SupabaseUrl.TrimEnd('/'))/rest/v1/projects?select=research_id&limit=1" `
        -Headers $headers `
        -UserAgent "codex-prism-readiness/1.0" `
        -UseBasicParsing `
        -TimeoutSec 30
      Add-Check $checks "supabase_schema" ($response.StatusCode -lt 400) "projects table is reachable with $($entry.name)"
      $schemaChecked = $true
      break
    } catch {
      $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
      if ($status -eq 404) {
        Add-Check $checks "supabase_schema" $false "projects table is missing; apply supabase/migrations/001_prism_kg_rag.sql first"
        $schemaChecked = $true
        break
      }
      if (($status -eq 401 -or $status -eq 403) -and $entry -ne $adminKeys[-1]) {
        continue
      }
      if ($status -eq 401 -or $status -eq 403) {
        Add-Check $checks "supabase_schema" $false "admin key was rejected by Supabase REST"
      } else {
        Add-Check $checks "supabase_schema" $false "Supabase REST schema check failed"
      }
      $schemaChecked = $true
      break
    }
  }
  if (-not $schemaChecked) {
    Add-Check $checks "supabase_schema" $false "Supabase REST schema check did not complete"
  }
} else {
  Add-Check $checks "supabase_schema" $false "Supabase URL or admin key is missing"
}

[pscustomobject]@{
  repo = $Repo
  project_ref = $ProjectRef
  supabase_url_configured = [bool]$SupabaseUrl
  checks = $checks
} | ConvertTo-Json -Depth 4
