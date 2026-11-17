<#
.SYNOPSIS
  Fallback publisher: build the site on this PC and deploy it to GitHub Pages (use if the DataMart blocks GitHub's runners).

.DESCRIPTION
  1. scripts\build_db.py   download + build + validation + tests (skip with -SkipBuild to export the current live build)
  2. scripts\export_static.py -> site\   (fails above 900 MB / 50 MB per file or if the Plot 91-25 totals differ)
  3. zips site\ and uploads it as asset site.zip of the rolling pre-release "local-site"
  4. commits ci\datamart_manifest.json so the monthly workflow knows what was published
  5. runs the build-deploy workflow with source=local-release, which deploys that zip with actions/deploy-pages
     (Pages stays configured for GitHub Actions, so automatic monthly runs keep working)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\publish_local.ps1
  powershell -ExecutionPolicy Bypass -File scripts\publish_local.ps1 -SkipBuild
#>
param([switch]$SkipBuild, [string]$Repo = '')
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$Gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $Gh) { $Gh = 'C:\Program Files\GitHub CLI\gh.exe' }
Set-Location $Root
function Run($exe, [string[]]$a) { & $exe @a; if ($LASTEXITCODE -ne 0) { throw "$exe $($a -join ' ') failed ($LASTEXITCODE)" } }
if (-not $Repo) { $Repo = (& $Gh repo view --json nameWithOwner --jq .nameWithOwner) }

if (-not $SkipBuild) { Run $Py @('-I', 'scripts\build_db.py') }
Run $Py @('-I', 'scripts\export_static.py', '--out', 'site')
Run $Py @('-I', 'scripts\ci_manifest.py', 'write')

$zip = Join-Path $env:TEMP 'site.zip'
if (Test-Path $zip) { Remove-Item $zip -Force }
Run $Py @('-I', '-c', "import shutil; shutil.make_archive(r'$($zip -replace '\.zip$','')', 'zip', r'$Root\site')")
Write-Host ("site.zip: {0:N1} MB" -f ((Get-Item $zip).Length / 1MB))

& $Gh release view local-site --repo $Repo *> $null
if ($LASTEXITCODE -ne 0) {
    Run $Gh @('release', 'create', 'local-site', '--repo', $Repo, '--prerelease', '--title', 'Locally built site',
              '--notes', 'Static site built on a PC by scripts/publish_local.ps1; deployed by the build-deploy workflow (source=local-release).')
}
Run $Gh @('release', 'upload', 'local-site', $zip, '--repo', $Repo, '--clobber')

git add ci/datamart_manifest.json
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { Run git @('commit', '-m', 'Update DataMart manifest (local publish)'); Run git @('push') }

Run $Gh @('workflow', 'run', 'build-deploy.yml', '--repo', $Repo, '-f', 'source=local-release')
Start-Sleep 5
$id = & $Gh run list --repo $Repo --workflow build-deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId'
Write-Host "Deploying via workflow run $id ..."
Run $Gh @('run', 'watch', $id, '--repo', $Repo, '--exit-status')
Write-Host "Published: $(& $Gh api "repos/$Repo/pages" --jq .html_url)"
