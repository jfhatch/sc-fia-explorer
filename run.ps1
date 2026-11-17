<#
.SYNOPSIS
  Start the SC FIA plot explorer on http://127.0.0.1:<Port>/ (loopback only) and open it in the default browser.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File run.ps1
  powershell -ExecutionPolicy Bypass -File run.ps1 -Port 8800 -NoBrowser
#>
param([int]$Port = 8742, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Py = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) { throw "virtual environment missing: py -3.12 -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt" }
if (-not (Test-Path (Join-Path $Root 'data\current.json'))) { throw "no database yet: run  .venv\Scripts\python.exe -I scripts\build_db.py" }
$server = Start-Process -FilePath $Py -ArgumentList @('-I', (Join-Path $Root 'app\server.py'), $Port) -WorkingDirectory $Root -PassThru -NoNewWindow
$url = "http://127.0.0.1:$Port/"
for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-WebRequest -UseBasicParsing -Uri ($url + 'api/meta') -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Milliseconds 500 }
}
Write-Host "FIA SC explorer running at $url (server PID $($server.Id)); press Ctrl+C or close this window to stop."
if (-not $NoBrowser) { Start-Process $url }
Wait-Process -Id $server.Id
