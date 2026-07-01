param(
  [string]$Dir = "exports\supabase",
  [int]$BatchSize = 1000,
  [switch]$Verify
)

$ErrorActionPreference = "Stop"

$argsList = @("scripts\load_supabase_snapshot.py", "--dir", $Dir, "--batch-size", "$BatchSize")
if ($Verify) {
  $argsList += "--verify"
}
python @argsList
