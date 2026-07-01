param(
  [string]$Db = "data\prism.sqlite",
  [string]$Out = "exports\supabase"
)

$ErrorActionPreference = "Stop"
python scripts\export_prism_supabase.py --db $Db --out $Out
