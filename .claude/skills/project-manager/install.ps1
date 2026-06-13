# Установка скилла project-manager из репозитория OverGate в локальную папку плагинов Claude.
# Запуск:
#   powershell -ExecutionPolicy Bypass -File "<этот_файл>"

$ErrorActionPreference = "Stop"

$Src = $PSScriptRoot
$Dest = "$env:APPDATA\Claude\local-agent-mode-sessions\skills-plugin\895eadaa-7627-4e16-a251-a6569dc507c4\71b9303c-6821-4825-9aae-ddf7d998e891\skills\project-manager"
$Backup = "$Dest.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

Write-Host "Source : $Src" -ForegroundColor Cyan
Write-Host "Target : $Dest" -ForegroundColor Cyan

if (-Not (Test-Path "$Src\SKILL.md")) {
    Write-Error "SKILL.md not found in source directory: $Src"
    exit 1
}

if (Test-Path $Dest) {
    Write-Host "Backup : $Backup" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Step 1/3: backup current version..." -ForegroundColor Yellow
    Copy-Item -Path $Dest -Destination $Backup -Recurse -Force
    Write-Host "  OK: backed up to $Backup" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Step 1/3: target does not exist yet, fresh install (no backup)" -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
}

Write-Host ""
Write-Host "Step 2/3: copy SKILL.md..." -ForegroundColor Yellow
Copy-Item -Path "$Src\SKILL.md" -Destination "$Dest\SKILL.md" -Force
Write-Host "  OK: SKILL.md installed" -ForegroundColor Green

Write-Host ""
Write-Host "Step 3/3: copy references/*.md..." -ForegroundColor Yellow
if (-Not (Test-Path "$Dest\references")) {
    New-Item -ItemType Directory -Path "$Dest\references" | Out-Null
}
Get-ChildItem -Path "$Src\references" -Filter "*.md" | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination "$Dest\references\$($_.Name)" -Force
    Write-Host "  OK: references/$($_.Name)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Done. Restart your Cowork session to pick up the new skill version." -ForegroundColor Green
if (Test-Path $Backup) {
    Write-Host "Backup at $Backup." -ForegroundColor DarkGray
}
