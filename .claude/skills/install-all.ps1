# Установка всех мастер-копий скиллов из репозитория OverGate в локальную папку плагинов Claude.
# Сканирует подпапки .claude/skills/, в каждой, где есть install.ps1, запускает его.
#
# Запуск:
#   powershell -ExecutionPolicy Bypass -File "<OVERGATE_REPO>\.claude\skills\install-all.ps1"
#
# Подходит как для первоначальной установки на новом компьютере, так и для синхронизации
# после `git pull` с обновлёнными мастер-копиями.

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
Write-Host "Scanning skills in: $Root" -ForegroundColor Cyan
Write-Host ""

$Installers = Get-ChildItem -Path $Root -Directory | ForEach-Object {
    $candidate = Join-Path $_.FullName "install.ps1"
    if (Test-Path $candidate) {
        [PSCustomObject]@{
            Name = $_.Name
            Installer = $candidate
        }
    }
}

if (-Not $Installers) {
    Write-Host "No skills with install.ps1 found." -ForegroundColor Yellow
    exit 0
}

Write-Host "Found $($Installers.Count) skill(s) to install:" -ForegroundColor Cyan
$Installers | ForEach-Object { Write-Host "  - $($_.Name)" -ForegroundColor White }
Write-Host ""

$Success = @()
$Failed = @()

foreach ($skill in $Installers) {
    Write-Host "=== Installing: $($skill.Name) ===" -ForegroundColor Magenta
    try {
        & $skill.Installer
        $Success += $skill.Name
    } catch {
        Write-Host "  FAILED: $($_.Exception.Message)" -ForegroundColor Red
        $Failed += $skill.Name
    }
    Write-Host ""
}

Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host "Installed: $($Success.Count)" -ForegroundColor Green
$Success | ForEach-Object { Write-Host "  + $_" -ForegroundColor Green }

if ($Failed.Count -gt 0) {
    Write-Host "Failed: $($Failed.Count)" -ForegroundColor Red
    $Failed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Restart Cowork session AFTER fixing failed installs." -ForegroundColor Yellow
    exit 1
} else {
    Write-Host ""
    Write-Host "All skills installed. Restart your Cowork session to pick them up." -ForegroundColor Green
}
