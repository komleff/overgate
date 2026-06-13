# Codex CLI account switcher для OverGate pipeline.
#
# Validated 2026-05-05: dual-account swap (Personal Plus + TOO Overmobile Business).
# Оба аккаунта залогинены через browser OAuth на одном email (komleff@gmail.com),
# различаются workspace picker'ом OpenAI на etap login.
#
# Backup-файлы:
#   ~/.codex/auth-personal-plus.json   — Personal Plus tier (~$25/мес)
#   ~/.codex/auth-work-business.json   — TOO Overmobile Business tier (~$30/мес/seat)
#   ~/.codex/auth.json                 — active (копия одного из выше, читается Codex CLI)
#
# Usage (dot-source from any pwsh session in OverGate repo):
#   . .\.claude\tools\codex-account-switch.ps1
#   Show-CodexAccount                  # текущий active account (plan, account_id, expires)
#   Use-CodexAccount personal-plus     # переключить → Personal Plus
#   Use-CodexAccount work-business     # переключить → TOO Overmobile Business
#   Backup-CodexAccount personal-plus  # сохранить текущий auth.json как Personal backup
#                                      # (после повторного codex login)
#
# Pipeline invocation pattern (после Use-CodexAccount):
#   codex -p review -c sandbox_mode="danger-full-access" review --commit <SHA>
#
# Когда переключать:
#   - Active account вернул 429 (subscription quota exhausted) → Use другой → retry
#   - Подозрение что один account имеет stale OAuth token → Use другой
#
# Восстановление при поломке:
#   - Если auth.json потерян / сломан → Use-CodexAccount <любой> восстанавливает
#   - Если оба backup потеряны → codex login повторно (browser flow)
#
# См. .agents/CODEX_AUTH.md §8 ChatGPT subscription path
# См. .agents/PIPELINE_ADR.md ADR 3.27

# Cross-platform Codex home discovery: CODEX_HOME override (Codex CLI standard env) >
# USERPROFILE (Windows) > HOME (Linux/macOS/WSL/CI). Hardcoded $env:USERPROFILE
# падает на POSIX pwsh sessions (headless CI, WSL).
$script:CodexHome = if ($env:CODEX_HOME) {
  $env:CODEX_HOME
}
elseif ($env:USERPROFILE) {
  Join-Path $env:USERPROFILE '.codex'
}
elseif ($env:HOME) {
  Join-Path $env:HOME '.codex'
}
else {
  throw 'Cannot locate Codex home: set CODEX_HOME, USERPROFILE, or HOME environment variable.'
}
$script:ActiveAuth = Join-Path $script:CodexHome 'auth.json'
$script:ValidAccounts = @('personal-plus', 'work-business')

function Get-AccountBackupPath {
  param([string]$account)
  if ($account -notin $script:ValidAccounts) {
    throw "Invalid account name '$account'. Valid: $($script:ValidAccounts -join ', ')"
  }
  return Join-Path $script:CodexHome "auth-${account}.json"
}

function Show-CodexAccount {
  if (-not (Test-Path $script:ActiveAuth)) {
    Write-Host "Нет активного auth.json — выполни 'codex login' сначала." -ForegroundColor Yellow
    return
  }
  $auth = Get-Content $script:ActiveAuth -Raw | ConvertFrom-Json
  if ($auth.auth_mode -eq 'apikey') {
    $key = $auth.OPENAI_API_KEY
    $tail = if ($key.Length -ge 4) { $key.Substring($key.Length - 4) } else { '****' }
    Write-Host "Active: API key (Platform API path), suffix ***$tail" -ForegroundColor Cyan
    Write-Host "Это legacy fallback (CODEX_AUTH.md §9). Не использует ChatGPT subscription quota." -ForegroundColor Yellow
    return
  }
  if ($null -ne $auth.tokens -and $null -ne $auth.tokens.id_token) {
    $tok = $auth.tokens.id_token
    $payload = $tok.Split('.')[1]
    while ($payload.Length % 4) { $payload += '=' }
    $payload = $payload.Replace('-', '+').Replace('_', '/')
    $bytes = [Convert]::FromBase64String($payload)
    $decoded = [Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json
    $a = $decoded.'https://api.openai.com/auth'
    Write-Host "Active ChatGPT account:" -ForegroundColor Green
    Write-Host "  plan_type: $($a.chatgpt_plan_type)" -ForegroundColor Green
    Write-Host "  account_id: $($a.chatgpt_account_id)" -ForegroundColor Green
    Write-Host "  subscription_active_until: $($a.chatgpt_subscription_active_until)" -ForegroundColor Green
    Write-Host "  email: $($decoded.email)" -ForegroundColor Green
  }
  else {
    Write-Host "Active auth.json malformed (no tokens). Восстанови через Use-CodexAccount." -ForegroundColor Red
  }
}

function Use-CodexAccount {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]
    [ValidateSet('personal-plus', 'work-business')]
    [string]$account
  )
  $backup = Get-AccountBackupPath $account
  if (-not (Test-Path $backup)) {
    Write-Host "Backup not found: $backup" -ForegroundColor Red
    Write-Host "Сначала: codex login (browser → выбрать workspace), затем Backup-CodexAccount $account" -ForegroundColor Yellow
    return
  }
  Copy-Item -Force $backup $script:ActiveAuth
  Write-Host "Switched to: $account" -ForegroundColor Green
  Show-CodexAccount
}

function Backup-CodexAccount {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]
    [ValidateSet('personal-plus', 'work-business')]
    [string]$account
  )
  if (-not (Test-Path $script:ActiveAuth)) {
    Write-Host "Нет active auth.json для backup." -ForegroundColor Red
    return
  }
  $backup = Get-AccountBackupPath $account
  Copy-Item -Force $script:ActiveAuth $backup
  Write-Host "Saved current auth.json → $backup" -ForegroundColor Green
}
