<#
.SYNOPSIS
    Start FarmGrid AI - backend and frontend together.

.DESCRIPTION
    This project has no separate frontend application. Django serves the
    HTML templates (FarmGridAI-frontend/templates) and the static assets
    (FarmGridAI-frontend/static) from the same origin, so one command brings up
    both the API (/api/v1/...) and the UI (/, /dashboard/, /login/, ...).

.PARAMETER Port
    Port to listen on. Default 8000.

.PARAMETER Settings
    Django settings module. Default FarmGridAI.settings.development.

.PARAMETER Migrate
    Apply pending migrations before starting. Off by default because migrate is
    not free; turn it on after pulling changes that add a migration.

.PARAMETER Seed
    Run the idempotent seed_platform command (benchmarks, subsidy schemes,
    knowledge base, equipment catalog). Safe to re-run.

.PARAMETER DemoUser
    Create the demo login farmer@farmgrid.in / FarmGrid@123 if missing, so the
    sign-in and sign-out flow can be exercised without registering by hand.

.PARAMETER NoBrowser
    Do not open a browser window on startup.

.PARAMETER Reload
    Use Django's autoreloader. Convenient while editing, but it forks a child
    process, so Ctrl+C can leave an orphan holding the port.

.EXAMPLE
    .\run.ps1
    Starts on http://127.0.0.1:8000

.EXAMPLE
    .\run.ps1 -Port 9000 -Migrate -Seed -DemoUser
    First-time setup on a different port.
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [string]$Settings = "FarmGridAI.settings.development",
    [switch]$Migrate,
    [switch]$Seed,
    [switch]$DemoUser,
    [switch]$NoBrowser,
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = (Get-Location).Path }

# --- locate the interpreter -------------------------------------------------
# Prefer the project virtualenv; fall back to whatever python is on PATH so the
# script still works in a shell that has already activated it.
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $VenvPython) {
    $Python = $VenvPython
    Write-Host "  interpreter : $Python (project virtualenv)" -ForegroundColor DarkGray
} else {
    $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $Python) {
        throw "No Python interpreter found. Create .venv or activate one, then re-run."
    }
    Write-Host "  interpreter : $Python (from PATH - no .venv found)" -ForegroundColor Yellow
}

function Invoke-Django {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $Python manage.py @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "manage.py $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

# --- pre-flight -------------------------------------------------------------
$env:DJANGO_SETTINGS_MODULE = $Settings
Write-Host ""
Write-Host "FarmGrid AI - starting backend + frontend" -ForegroundColor Cyan
Write-Host "  project    : $ProjectRoot"
Write-Host "  settings   : $Settings"
Write-Host "  url        : http://127.0.0.1:$Port" -ForegroundColor Cyan

Push-Location $ProjectRoot
try {
    # Fail fast and loudly on a bad checkout rather than half-starting.
    Invoke-Django check

    if ($Migrate) {
        Write-Host "`n  applying migrations..." -ForegroundColor Cyan
        Invoke-Django migrate --noinput
    }

    if ($Seed) {
        Write-Host "`n  seeding platform data..." -ForegroundColor Cyan
        Invoke-Django seed_platform
    }

    if ($DemoUser) {
        Write-Host "`n  ensuring demo user..." -ForegroundColor Cyan
        $code = @'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "FarmGridAI.settings.development")
django.setup()
from django.contrib.auth import get_user_model
U = get_user_model()
u, created = U.objects.get_or_create(
    username="farmer", defaults={"email": "farmer@farmgrid.in"}
)
if created or not u.has_usable_password():
    u.set_password("FarmGrid@123")
    u.save()
print("  demo user ready: farmer / FarmGrid@123")
'@
        $code | & $Python -
        if ($LASTEXITCODE -ne 0) { throw "demo user creation failed" }
    }

    if (-not $NoBrowser) {
        # Best effort only - a headless box has no browser to launch and that
        # must not stop the server.
        try {
            Start-Process "http://127.0.0.1:$Port/login/"
        } catch {
            Write-Host "  (could not open a browser - open the URL above manually)" -ForegroundColor DarkGray
        }
    }

    # Invoke-Django already puts manage.py in front of these.
    $serverArgs = @("runserver", "127.0.0.1:$Port")
    # The autoreloader forks a child that can outlive Ctrl+C and keep the port,
    # so single-process is the default and -Reload is opt-in.
    if (-not $Reload) { $serverArgs += "--noreload" }

    Write-Host "`n  Ctrl+C to stop.`n" -ForegroundColor DarkGray
    Invoke-Django @serverArgs
}
finally {
    Pop-Location
}