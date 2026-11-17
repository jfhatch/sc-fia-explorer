<#
.SYNOPSIS
  Check for, import, or roll back FIADB DataMart updates for the SC FIA plot explorer (same code as the app's Data panel).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -Check
  powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -Import
  powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -Import -AcceptRowDrops
  powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -Rollback
  powershell -ExecutionPolicy Bypass -File scripts\update.ps1            # status

  -Check     HEAD requests only: reports tables whose Last-Modified / Content-Length / ETag changed since the live build.
  -Import    downloads changed tables (resumable), builds data\builds\fia_sc_YYYYMMDD.sqlite from scratch, validates
             (row counts, key relationships, Plot 45-3-91-25 2000-2021 totals), runs the test suite against it and
             switches atomically. Reports new visits since the last build. The current build stays live on any failure.
  -Rollback  restores the previous build (the two previous builds are kept).
#>
param([switch]$Check, [switch]$Import, [switch]$Rollback, [switch]$AcceptRowDrops, [string]$BaseUrl)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) { $Py = 'python' }
$cli = Join-Path $Root 'scripts\update_cli.py'
$a = @()
if ($Check) { $a += 'check' } elseif ($Import) { $a += 'import' } elseif ($Rollback) { $a += 'rollback' } else { $a += 'status' }
if ($AcceptRowDrops) { $a += '--accept-row-drops' }
if ($BaseUrl) { $a += @('--base-url', $BaseUrl) }
& $Py -I $cli @a
$code = $LASTEXITCODE
if ($Check -and $code -eq 10) { exit 0 }      # 10 = changes found (not an error)
exit $code
