<#
.SYNOPSIS
    Publish FarmGrid AI to a public HTTPS URL through a Cloudflare tunnel.

.DESCRIPTION
    Starts Django on loopback and puts a `cloudflared` quick tunnel in front of
    it, then prints the resulting https://<random>.trycloudflare.com address.
    Nothing has to be opened on the router or in the firewall, and no Cloudflare
    account or domain is required for a quick tunnel.

    The tunnel URL is public: anybody who has it can reach the site. This script
    therefore defaults to the development settings, which means DEBUG is on. That
    is fine on loopback and NOT fine on a public URL - a Django error page can
    leak settings and environment values. See the warning printed at startup, and
    prefer a named tunnel on a real host for anything longer than a demo.

    Ctrl+C stops both processes and the URL stops resolving.

.PARAMETER Port
    Loopback port for Django. Default 8000.

.PARAMETER Migrate
    Apply pending migrations before publishing.

.PARAMETER Seed
    Run the idempotent seed_platform command before publishing.

.PARAMETER Yes
    Skip the interactive public-exposure confirmation. Required for unattended
    runs; without it the script stops and waits for a Y.

.PARAMETER NoBrowser
    Do not open a browser at the public URL.

.PARAMETER TimeoutSeconds
    How long to wait for Django and the tunnel to come up. Default 90.

.EXAMPLE
    .\run_live.ps1
    Asks for confirmation, then prints the public URL.

.EXAMPLE
    .\run_live.ps1 -Yes -NoBrowser
    Non-interactive; useful from an existing shell or a scheduled task.

.NOTES
    Requires cloudflared on PATH:
        winget install --id Cloudflare.cloudflared
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$Migrate,
    [switch]$Seed,
    [switch]$Yes,
    [switch]$NoBrowser,
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = (Get-Location).Path }

# --- preflight --------------------------------------------------------------
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $Python) {
        throw "No Python interpreter found. Create .venv or activate one, then re-run."
    }
}

$cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cloudflared) {
    throw @"
cloudflared was not found on PATH.

Install it with:
    winget install --id Cloudflare.cloudflared
"@
}

Write-Host ""
Write-Host "FarmGrid AI - public tunnel via Cloudflare" -ForegroundColor Cyan
Write-Host "  interpreter : $Python"
Write-Host "  cloudflared : $cloudflared"
Write-Host "  loopback    : http://127.0.0.1:$Port"

Write-Host ""
Write-Host "  WARNING: the tunnel URL is reachable by anyone who has it." -ForegroundColor Yellow
Write-Host "  This runs the Django development server, so DEBUG is ON. A Django" -ForegroundColor Yellow
Write-Host "  error page can expose settings and environment values. Treat this as" -ForegroundColor Yellow
Write-Host "  a demo, not a deployment." -ForegroundColor Yellow

if (-not $Yes) {
    $answer = Read-Host "`n  Publish anyway? [y/N]"
    if ($answer -ne "y" -and $answer -ne "Y") {
        Write-Host "  cancelled." -ForegroundColor DarkGray
        exit 1
    }
}

# Django must believe it is behind TLS, otherwise secure cookies lose their
# Secure flag and is_secure() is wrong for every proxied request.
$env:TRUST_PROXY_HEADERS = "true"
$env:DJANGO_SETTINGS_MODULE = "FarmGridAI.settings.development"

$LogDir = Join-Path $env:TEMP "farmgrid_live"
if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$ServerLog = Join-Path $LogDir "django.log"
$TunnelLog = Join-Path $LogDir "cloudflared.log"
foreach ($f in @($ServerLog, $TunnelLog)) {
    if (Test-Path -LiteralPath $f) { Remove-Item -LiteralPath $f -Force }
}

$server = $null
$tunnel = $null

function Wait-Http {
    param([string]$Url, [int]$Seconds)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 4
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
        } catch {
            $code = $null
            try { $code = $_.Exception.Response.StatusCode.value__ } catch { }
            if ($code) { return $true }
        }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

try {
    Push-Location $ProjectRoot
    try {
        Write-Host "`n  checking the project..." -ForegroundColor Cyan
        & $Python manage.py check
        if ($LASTEXITCODE -ne 0) { throw "manage.py check failed" }

        if ($Migrate) {
            Write-Host "`n  applying migrations..." -ForegroundColor Cyan
            & $Python manage.py migrate --noinput
            if ($LASTEXITCODE -ne 0) { throw "migrate failed" }
        }
        if ($Seed) {
            Write-Host "`n  seeding platform data..." -ForegroundColor Cyan
            & $Python manage.py seed_platform
            if ($LASTEXITCODE -ne 0) { throw "seed_platform failed" }
        }

        Write-Host "`n  starting Django on 127.0.0.1:$Port ..." -ForegroundColor Cyan
        $server = Start-Process -FilePath $Python `
            -ArgumentList "manage.py", "runserver", "127.0.0.1:$Port", "--noreload" `
            -WorkingDirectory $ProjectRoot -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $ServerLog -RedirectStandardError "$ServerLog.err"

        if (-not (Wait-Http -Url "http://127.0.0.1:$Port/api/v1/health" -Seconds $TimeoutSeconds)) {
            Write-Host "  Django did not answer in time. Tail of $ServerLog.err :" -ForegroundColor Red
            if (Test-Path "$ServerLog.err") {
                Get-Content "$ServerLog.err" -Tail 20 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkRed }
            }
            throw "Django did not become ready"
        }
        Write-Host "  Django is up." -ForegroundColor Green

        Write-Host "  opening the Cloudflare tunnel..." -ForegroundColor Cyan
        $tunnel = Start-Process -FilePath $cloudflared `
            -ArgumentList "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$Port" `
            -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $TunnelLog -RedirectStandardError "$TunnelLog.err"

        # cloudflared prints the public hostname a few seconds after connecting.
        $publicUrl = $null
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            if (Test-Path -LiteralPath "$TunnelLog.err") {
                $text = Get-Content "$TunnelLog.err" -Raw -ErrorAction SilentlyContinue
                if ($text) {
                    $m = [regex]::Match($text, 'https://[a-z0-9-]+\.trycloudflare\.com')
                    if ($m.Success) { $publicUrl = $m.Value; break }
                }
            }
            if ($tunnel.HasExited) { break }
            Start-Sleep -Milliseconds 800
        }

        if (-not $publicUrl) {
            Write-Host "  The tunnel did not report a URL. Tail of $TunnelLog.err :" -ForegroundColor Red
            if (Test-Path "$TunnelLog.err") {
                Get-Content "$TunnelLog.err" -Tail 20 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkRed }
            }
            throw "no tunnel URL - is there outbound network access?"
        }

        Write-Host ""
        Write-Host "  PUBLIC URL" -ForegroundColor Green
        Write-Host "  $publicUrl" -ForegroundColor White
        Write-Host ""
        Write-Host "  share it, then press Ctrl+C to take it down." -ForegroundColor DarkGray
        Write-Host "  logs: $ServerLog" -ForegroundColor DarkGray
        Write-Host "        $TunnelLog.err" -ForegroundColor DarkGray
        Write-Host ""

        if (-not $NoBrowser) {
            try { Start-Process $publicUrl } catch { }
        }

        # Park until the tunnel exits (Ctrl+C) so cleanup below always runs.
        while (-not $tunnel.HasExited) {
            Start-Sleep -Seconds 2
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    Write-Host ""
    Write-Host "  stopping..." -ForegroundColor DarkGray
    foreach ($proc in @($tunnel, $server)) {
        if ($proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Milliseconds 800
    Write-Host "  the public URL no longer resolves." -ForegroundColor DarkGray
}