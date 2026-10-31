# Python smoke test - contract conformance for the FastAPI backend.
# Mirrors scripts/smoke-elixir.ps1 so the two stacks are checked identically.
# MUST point at a throwaway database (the live one holds the real library):
#   docker exec db psql -U spotify -d spotify -c "CREATE DATABASE spotify_smoke;"
#   docker run -d --name spotify-api-smoke --network spotify-dash-board-python-latest_default \
#     --env-file .env -e DATABASE_URL=postgresql://spotify:spotify@db:5432/spotify_smoke \
#     -e MIGRATIONS_DIR=/app/migrations -p 8001:8000 spotify-api
#
# The library endpoints are unauthenticated here (Spotify-OAuth only), so there
# is no register step; the first CSV import creates the schema.
#
# Usage: powershell -File smoke-python.ps1 [-Server url] [-Keep]
param(
  [string]$Server = 'http://127.0.0.1:8001',
  [switch]$Keep,
  [switch]$Reset,
  [switch]$SeedToken
)

$ErrorActionPreference = 'Stop'
$failures = @()

# curl.exe on Windows, curl elsewhere — the CI runs these under pwsh on ubuntu.
$curlExe = if ($env:OS -eq 'Windows_NT') { 'curl.exe' } else { 'curl' }

function Step($name, $ok, $detail = '') {
  $d = if ($detail) { ' -- ' + $detail } else { '' }
  if ($ok) { Write-Host "PASS  $name$d" }
  else { Write-Host "FAIL  $name$d"; $script:failures += $name }
}

function InvokeApi($method, $path, $body) {
  $params = @{ Uri = "$Server$path"; Method = $method; TimeoutSec = 30 }
  if ($body) {
    $params['ContentType'] = 'application/json'
    $params['Body'] = ($body | ConvertTo-Json -Compress -Depth 4)
  }
  return (Invoke-RestMethod @params)
}

function AssertEnvelope($path, $expectCode, $expectErrorCode) {
  $r = Invoke-Status 'GET' $path
  $parsed = $null
  try { $parsed = $r.Body | ConvertFrom-Json } catch { $parsed = $null }
  $actual = if ($parsed -and $parsed.error) { $parsed.error.code } else { '<none>' }
  Step "envelope $path" ($r.Code -eq $expectCode -and $actual -eq $expectErrorCode) "$($r.Code) error.code=$actual"
}

# Status + body without throwing, for both 2xx and error responses.
function Invoke-Status($method, $path, $body) {
  $params = @{ Uri = "$Server$path"; Method = $method; TimeoutSec = 30; UseBasicParsing = $true }
  if ($body) {
    $params['ContentType'] = 'application/json'
    $params['Body'] = ($body | ConvertTo-Json -Compress -Depth 4)
  }
  try {
    $r = Invoke-WebRequest @params
    return @{ Code = [int]$r.StatusCode; Body = $r.Content }
  } catch {
    $code = 0
    $text = ''
    try { $code = [int]$_.Exception.Response.StatusCode } catch { }
    try { $text = $_.ErrorDetails.Message } catch { }
    return @{ Code = $code; Body = $text }
  }
}

$stamp = Get-Date -Format 'HHmmss'

# The python library is GLOBAL (no per-user scoping, unlike elixir), so the
# assertions below need exact totals. -Reset wipes it first -- only ever point
# this at a throwaway database, never the live one.
if ($Reset) {
  Write-Host "RESET: deleting the entire library at $Server (throwaway DB only!)"
  InvokeApi 'DELETE' '/api/v1/albums' | Out-Null
  $pre = InvokeApi 'GET' '/api/v1/albums?limit=1'
  Step 'library empty before import' ($pre.total -eq 0) "total=$($pre.total)"
}

# 0. health probe on the contract path (no auth)
$health = $null
try { $health = Invoke-RestMethod -Uri "$Server/api/v1/health" -TimeoutSec 15 } catch { }
Step 'health probe on /api/v1/health' ($null -ne $health -and $health.status -eq 'ok') "status=$($health.status)"

# 0b. CORS preflight. A browser frontend on another origin can only use this
# backend in remote mode if the preflight is answered; all three backends must
# allow any origin, and elixir answered none at all before this check existed.
$preflight = @{ code = 0; allowOrigin = $null; allowHeaders = $null }
try {
  $optReq = [System.Net.HttpWebRequest]::Create("$Server/api/v1/albums")
  $optReq.Method = 'OPTIONS'
  $optReq.Headers.Add('Origin', 'http://example.test')
  $optReq.Headers.Add('Access-Control-Request-Method', 'GET')
  $optReq.Headers.Add('Access-Control-Request-Headers', 'authorization')
  $optReq.Timeout = 15000
  try { $optResp = $optReq.GetResponse() } catch [System.Net.WebException] { $optResp = $_.Exception.Response }
  if ($optResp) {
    $preflight.code          = [int]$optResp.StatusCode
    $preflight.allowOrigin   = $optResp.Headers['Access-Control-Allow-Origin']
    $preflight.allowHeaders  = $optResp.Headers['Access-Control-Allow-Headers']
    $optResp.Close()
  }
} catch { }
Step 'CORS preflight allows another origin' `
  ($preflight.code -in 200, 204 -and $preflight.allowOrigin -eq '*') `
  "code=$($preflight.code) allow-origin=$($preflight.allowOrigin) allow-headers=$($preflight.allowHeaders)"

# 1. auth status (no account system here - Spotify OAuth only)
$auth = InvokeApi 'GET' '/api/v1/auth/status'
$authOk = $null -ne $auth -and ($auth.PSObject.Properties.Name -contains 'authenticated')
Step 'auth status responds' $authOk "authenticated=$($auth.authenticated)"

# 2. CSV import (also runs migrations, so it must come first)
$csv = @(
  'id,title,artist,year,genre,image_url,added_at'
  "smoke-$stamp-1,Smoke Alpha,Smoke Artist,2001,rock,http://img/smoke1,2024-01-01"
  "smoke-$stamp-2,Smoke Bravo,Smoke Artist,2002,jazz,http://img/smoke2,2024-01-02"
  "smoke-$stamp-3,Smoke Charlie,Other Band,2003,metal,http://img/smoke3,2024-01-03"
) -join "`n"
$imp = InvokeApi 'POST' '/api/v1/import/csv' (@{ csv_content = $csv })
Step 'csv import (3 imported)' ($imp.imported -eq 3 -and $imp.existing -eq 0 -and @($imp.errors).Count -eq 0) "imported=$($imp.imported) existing=$($imp.existing) errors=$(@($imp.errors).Count)"

$imp2 = InvokeApi 'POST' '/api/v1/import/csv' (@{ csv_content = $csv })
Step 'csv re-import dedup (3 existing)' ($imp2.existing -ge 3 -and $imp2.imported -eq 0) "existing=$($imp2.existing) imported=$($imp2.imported)"

# 3. list envelope + filters + sort + pagination
# The contract path is /api/v1/albums (no trailing slash) and must serve data
# directly -- a 307 redirect would break clients that don't follow redirects.
$noSlashOut = [System.IO.Path]::GetTempFileName()
$noSlash = & $curlExe -s -o $noSlashOut -w '%{http_code}' --max-time 20 "$Server/api/v1/albums?limit=1"
Step 'GET /api/v1/albums serves without redirect' ($noSlash -eq '200') "code=$noSlash"
Remove-Item $noSlashOut -Force -ErrorAction SilentlyContinue

$all = InvokeApi 'GET' '/api/v1/albums?limit=48&page=1&sort=title&order=asc'
Step 'list envelope {items,total,page,limit}' ($all.total -eq 3 -and $all.page -eq 1 -and $all.limit -eq 48 -and @($all.items).Count -eq 3) "total=$($all.total) items=$(@($all.items).Count)"
$keys = @($all.items[0].PSObject.Properties.Name)
Step 'flat item keys' (($keys -contains 'title') -and ($keys -contains 'artist') -and ($keys -contains 'image_url') -and ($keys -notcontains 'album')) "keys=$($keys -join ',')"
Step 'title sort asc' ($all.items[0].title -eq 'Smoke Alpha' -and $all.items[1].title -eq 'Smoke Bravo' -and $all.items[2].title -eq 'Smoke Charlie') "$($all.items[0].title) | $($all.items[1].title) | $($all.items[2].title)"

$rock = InvokeApi 'GET' '/api/v1/albums?genre=rock&limit=48'
Step 'genre filter (1 album)' ($rock.total -eq 1) "total=$($rock.total)"

$search = InvokeApi 'GET' '/api/v1/albums?search=bravo'
Step 'search (1 album)' ($search.total -eq 1 -and $search.items[0].title -eq 'Smoke Bravo') "total=$($search.total)"

$years = InvokeApi 'GET' '/api/v1/albums?year_from=2002&year_to=2003'
Step 'year range (2 albums)' ($years.total -eq 2) "total=$($years.total)"

$page1 = InvokeApi 'GET' '/api/v1/albums?limit=2&page=1&sort=title&order=asc'
$page2 = InvokeApi 'GET' '/api/v1/albums?limit=2&page=2&sort=title&order=asc'
Step 'pagination (2+1)' ($page1.total -eq 3 -and @($page1.items).Count -eq 2 -and @($page2.items).Count -eq 1 -and $page1.items[0].id -ne $page2.items[0].id)

# 4. stats
$stats = InvokeApi 'GET' '/api/v1/albums/stats'
$statsOk = $stats.totalAlbums -eq 3 -and $stats.totalArtists -eq 2 -and $stats.totalGenres -eq 3 -and $stats.oldestYear -eq 2001 -and $stats.newestYear -eq 2003
Step 'stats totals + year span' $statsOk "albums=$($stats.totalAlbums) artists=$($stats.totalArtists) genres=$($stats.totalGenres) span=$($stats.oldestYear)-$($stats.newestYear)"
Step 'stats topGenres/topArtists/albumsByYear' (@($stats.topGenres).Count -eq 3 -and @($stats.topArtists).Count -eq 2 -and @($stats.albumsByYear).Count -eq 3) "genres=$(@($stats.topGenres).Count) artists=$(@($stats.topArtists).Count) years=$(@($stats.albumsByYear).Count)"

# 5. jobs. Without a linked Spotify account the canonical start calls must fail
# fast with 422 not_connected (now aligned with elixir + csharp). Pass
# -SeedToken to insert a synthetic, non-working token so the 202 -> poll ->
# terminal-error path is exercised too (it fails against Spotify with 401).
$fakeToken = $false
if ($SeedToken) {
  Write-Host 'SEED: inserting a synthetic (invalid) Spotify token into the smoke DB'
  & docker exec db psql -U spotify -d spotify_smoke -c "DELETE FROM spotify_tokens; INSERT INTO spotify_tokens (access_token, refresh_token, expires_at) VALUES ('smoke-invalid-token','smoke-invalid-refresh', now() + interval '1 hour');" | Out-Null
  $fakeToken = $true
} else {
  # This backend keeps a SINGLE token row, so a previous -SeedToken run would
  # make the fail-fast assertions below see a "connected" account. Remove only
  # our own marker value -- never a token a real login created.
  & docker exec db psql -U spotify -d spotify_smoke -c "DELETE FROM spotify_tokens WHERE access_token = 'smoke-invalid-token';" | Out-Null
}

$syncResult = Invoke-Status 'POST' '/api/v1/sync/albums' (@{ clean = $false })
$syncBody = $null
try { $syncBody = $syncResult.Body | ConvertFrom-Json } catch { $syncBody = $null }
if ($fakeToken) {
  Step 'sync start returns job_id (seeded token)' ($syncResult.Code -eq 202 -and $syncBody -and $syncBody.job_id) "$($syncResult.Code) $($syncResult.Body)"
  $job = $null
  for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 2
    $job = InvokeApi 'GET' "/api/v1/jobs/$($syncBody.job_id)"
    if ($job.status -in @('done', 'error', 'cancelled')) { break }
  }
  Step 'sync job reaches terminal state' ($job.status -in @('done', 'error', 'cancelled')) "status=$($job.status) stage=$($job.stage)"
} else {
  $syncCode = if ($syncBody -and $syncBody.error) { $syncBody.error.code } else { '<none>' }
  Step 'sync without Spotify -> 422 not_connected' ($syncResult.Code -eq 422 -and $syncCode -eq 'not_connected') "$($syncResult.Code) error.code=$syncCode"
}
AssertEnvelope '/api/v1/jobs/00000000-0000-0000-0000-000000000000' 404 'not_found'

# 5b. sync history. Same endpoint, wrapper ({data: [job envelope]}), default
# limit and 50-cap as elixir + csharp. Unlike theirs this backend's history is
# in-memory and survives between smoke runs (the process does), so the unseeded
# branch only asserts the shape -- a fresh process is what makes it empty, not
# a code path this script can rely on. 9b below proves the contents in both
# modes by checking a job this run actually started.
$histResult = Invoke-Status 'GET' '/api/v1/sync/history'
$histBody = $null
try { $histBody = $histResult.Body | ConvertFrom-Json } catch { $histBody = $null }
if ($fakeToken) {
  $histFirst = @($histBody.data)[0]
  Step 'sync history lists the run that just finished' `
    ($histResult.Code -eq 200 -and @($histBody.data).Count -ge 1 -and
     $histFirst.job_id -eq $syncBody.job_id -and $null -ne $histFirst.result) `
    "code=$($histResult.Code) items=$(@($histBody.data).Count) first=$($histFirst.job_id) result=$($null -ne $histFirst.result)"
} else {
  Step 'sync history answers {data: [...]}' `
    ($histResult.Code -eq 200 -and $histBody.data -is [array]) `
    "code=$($histResult.Code) items=$(@($histBody.data).Count)"
}
$hist0Result = Invoke-Status 'GET' '/api/v1/sync/history?limit=0'
$hist0Body = $null
try { $hist0Body = $hist0Result.Body | ConvertFrom-Json } catch { $hist0Body = $null }
Step 'sync history clamps limit=0 to empty, like elixir + csharp' `
  ($hist0Result.Code -eq 200 -and @($hist0Body.data).Count -eq 0) `
  "code=$($hist0Result.Code) items=$(@($hist0Body.data).Count)"

# 6. queue. Empty selection is rejected before a job is created (422 no_albums,
# now aligned with elixir + csharp); without a linked account it fails fast with
# 422 not_connected.
$emptyResult = Invoke-Status 'POST' '/api/v1/queue' (@{ album_ids = @() })
$emptyBody = $null
try { $emptyBody = $emptyResult.Body | ConvertFrom-Json } catch { $emptyBody = $null }
$emptyCode = if ($emptyBody -and $emptyBody.error) { $emptyBody.error.code } else { '<none>' }
Step 'queue empty selection -> 422 no_albums' ($emptyResult.Code -eq 422 -and $emptyCode -eq 'no_albums') "$($emptyResult.Code) error.code=$emptyCode"

$qResult = Invoke-Status 'POST' '/api/v1/queue' (@{ album_ids = @("smoke-$stamp-1") })
$qBody = $null
try { $qBody = $qResult.Body | ConvertFrom-Json } catch { $qBody = $null }
if ($fakeToken) {
  Step 'queue start returns job_id (seeded token)' ($qResult.Code -eq 202 -and $qBody -and $qBody.job_id) "$($qResult.Code) $($qResult.Body)"
  $qJob = $null
  for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 2
    $qJob = InvokeApi 'GET' "/api/v1/jobs/$($qBody.job_id)"
    if ($qJob.status -in @('done', 'error', 'cancelled')) { break }
  }
  Step 'queue job reaches terminal state' ($qJob.status -in @('done', 'error', 'cancelled')) "status=$($qJob.status) stage=$($qJob.stage)"
} else {
  $qCode = if ($qBody -and $qBody.error) { $qBody.error.code } else { '<none>' }
  Step 'queue without Spotify -> 422 not_connected' ($qResult.Code -eq 422 -and $qCode -eq 'not_connected') "$($qResult.Code) error.code=$qCode"
}
# Unknown /api/v1 path must also use the nested envelope (contract: ALL errors).
AssertEnvelope '/api/v1/nope-does-not-exist' 404 'not_found'

# 7. export (frozen contract columns)
$csvOut = & $curlExe -sS --max-time 20 "$Server/api/v1/albums/export"
$lines = @($csvOut -split "`r?`n" | Where-Object { $_ })
Step 'export header is frozen set' ($lines[0] -eq 'id,title,artist,year,genre,image_url,added_at') "$($lines[0])"
Step 'export has 3 rows' ($lines.Count -eq 4) "rows=$($lines.Count - 1)"

# 8. meta lists
$genres = InvokeApi 'GET' '/api/v1/meta/genres'
$artists = InvokeApi 'GET' '/api/v1/meta/artists'
$yearsMeta = InvokeApi 'GET' '/api/v1/meta/years'
Step 'meta lists {data}' (@($genres.data).Count -eq 3 -and @($artists.data).Count -eq 2 -and @($yearsMeta.data).Count -eq 3) "genres=$(@($genres.data).Count) artists=$(@($artists.data).Count) years=$(@($yearsMeta.data).Count)"

# 9. export history (present on elixir; asserted here for parity)
$history = $null
try { $history = InvokeApi 'GET' '/api/v1/exports/history' } catch { $historyErr = $_ }
Step 'export history {data}' ($null -ne $history -and $null -ne $history.data) $(if ($historyErr) { "$([int]$historyErr.Exception.Response.StatusCode) $($historyErr.ErrorDetails.Message)" } else { "count=$(@($history.data).Count)" })

# 9b. python-only job extensions. Images is the contract's optional extension at
# its frozen path; both it and the DB reload start like any job and are read back
# through the generic job API. Safe to run here: this instance's /data is its own
# docker volume, never the live library's CSV or images.
$imgResult = Invoke-Status 'POST' '/api/v1/images/sync'
$imgBody = $null
try { $imgBody = $imgResult.Body | ConvertFrom-Json } catch { $imgBody = $null }
Step 'images extension starts a job (/api/v1/images/sync)' ($imgResult.Code -eq 202 -and $imgBody -and $imgBody.job_id) "$($imgResult.Code)"

$imgJob = $null
for ($i = 0; $i -lt 10; $i++) {
  if ($null -eq $imgBody -or -not $imgBody.job_id) { break }
  Start-Sleep -Seconds 2
  try { $imgJob = InvokeApi 'GET' "/api/v1/jobs/$($imgBody.job_id)" } catch { }
  if ($imgJob -and $imgJob.status -in @('done', 'error', 'cancelled')) { break }
}
Step 'images job is tracked by the generic job API' ($imgJob -and $imgJob.job_id -eq $imgBody.job_id -and $imgJob.status -in @('done', 'error', 'cancelled') -and $imgJob.stage -eq 'images') "status=$($imgJob.status) stage=$($imgJob.stage)"

# The history endpoint must list this run's own extension job: newest first, as
# the same job envelope (its real type/stage, not a reshaped history row), with
# the two optional timestamps python adds for the panel's "last sync" line.
# Runs in BOTH modes, unlike the 5b assertions above.
$imgHist = Invoke-Status 'GET' '/api/v1/sync/history'
$imgHistBody = $null
try { $imgHistBody = $imgHist.Body | ConvertFrom-Json } catch { $imgHistBody = $null }
$imgHistFirst = @($imgHistBody.data)[0]
Step 'history lists this run''s extension job, newest first, with timestamps' `
  ($imgHist.Code -eq 200 -and $imgHistFirst.job_id -eq $imgBody.job_id -and
   $imgHistFirst.stage -eq 'images' -and $imgHistFirst.created_at -and $imgHistFirst.finished_at) `
  "first=$($imgHistFirst.job_id) stage=$($imgHistFirst.stage) finished=$($imgHistFirst.finished_at)"

# The other extension: same 202 convention. It errors immediately here (this
# instance's /data has no CSV yet) without ever reaching the database, so it
# cannot disturb the assertions below.
$loadResult = Invoke-Status 'POST' '/api/v1/load/start'
$loadBody = $null
try { $loadBody = $loadResult.Body | ConvertFrom-Json } catch { $loadBody = $null }
Step 'DB reload extension starts a job (/api/v1/load/start)' ($loadResult.Code -eq 202 -and $loadBody -and $loadBody.job_id) "$($loadResult.Code)"

# 9c. the per-stage routes the contract does NOT have must stay gone. Syncing used
# to be startable three different ways (sync/start, images/start, load/start) with
# three separate cancellers; a 404 here is what keeps "one pipeline, one job, one
# job API" true instead of aspirational.
$legacyCodes = @()
foreach ($legacy in @('/api/v1/sync/start', '/api/v1/images/start', '/api/v1/sync/cancel')) {
  $r = Invoke-Status 'POST' $legacy
  $legacyCodes += "$legacy=$($r.Code)"
}
$badLegacy = @($legacyCodes | Where-Object { $_ -notmatch '=404$' })
Step 'removed per-stage routes are 404' ($badLegacy.Count -eq 0) "$($legacyCodes -join ', ')"

# 10. clear (contract: {deleted: n})
if (-not $Keep) {
  $cleared = InvokeApi 'DELETE' '/api/v1/albums'
  $after = InvokeApi 'GET' '/api/v1/albums?limit=1'
  Step 'delete all {deleted:3}' ($cleared.deleted -eq 3 -and $after.total -eq 0) "deleted=$($cleared.deleted) total_now=$($after.total)"
}

Write-Host ''
if ($failures.Count -gt 0) { Write-Host "SMOKE FAILED: $($failures -join ', ')"; exit 1 }
Write-Host 'SMOKE OK - python backend (import->filter->stats->jobs->sync-history->queue->export->meta->export-history->delete)'
exit 0
