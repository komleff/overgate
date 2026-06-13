#!/usr/bin/env bash
# SessionStart hook: автоматический логин Codex CLI из $OPENAI_API_KEY.
#
# ⚠️ LEGACY / EMERGENCY-ONLY (с 2026-05-17, bead U2-v43k).
# Это устаревший Platform API-key путь авторизации Codex CLI. Штатный путь
# внешнего ревью v3.9 — ChatGPT subscription через `codex login` (OAuth),
# см. .agents/CODEX_AUTH.md §8 + ADR 3.27. Platform API key признан дорогим
# и на практике нерабочим (месячная квота исчерпывается мгновенно) — этот
# hook сохранён только как аварийный fallback и по умолчанию ВЫКЛЮЧЕН
# (opt-in через OVERGATE_CODEX_AUTOLOGIN, см. ниже). Миграция на global `codex`
# намеренно НЕ делается: для subscription/OAuth этот hook не нужен вовсе.
#
# Идемпотентен: ничего не делает, если уже залогинен (любой auth — API key или ChatGPT OAuth).
# Не валит сессию: при отсутствии ключа или сбое выдаёт предупреждение и выходит 0.
# Не светит ключ: передача через stdin (--with-api-key), без argv.
#
# Намеренно НЕ используется set -e: каждая ветка должна завершаться exit 0
# (fail-secure — hook никогда не прерывает старт сессии). set -u включён
# чтобы поймать опечатки в именах переменных при разработке hook'а.

set -u

# Если npx недоступен — Codex CLI не поставить, молча выходим.
command -v npx >/dev/null 2>&1 || exit 0

# Opt-in через env var (Шаг 7.7 Plan A — supply-chain hardening per gpt-5.5 review).
# По умолчанию hook ничего не делает: npx тянет latest @openai/codex каждый старт сессии
# + передаёт $OPENAI_API_KEY через stdin = supply-chain risk утечки ключа.
# Включить автологин: export OVERGATE_CODEX_AUTOLOGIN=1 в shell profile (или .env.local).
if [ "${OVERGATE_CODEX_AUTOLOGIN:-0}" != "1" ]; then
  exit 0  # Opt-out by default. См. .agents/CODEX_AUTH.md §6 «Manual login».
fi

# Если уже залогинены — выходим без шума.
# Codex пишет статус в stderr, поэтому сливаем stderr→stdout перед grep.
# Regex anchor: ^Logged in (using|to) — покрывает известные wording'и CLI
# ("Logged in using ChatGPT", "Logged in using an API key - ..."), но НЕ
# матчит произвольные подстроки типа "Logged in but expired" — те уйдут
# в login-branch. Adversarial review F1 (Sprint 5): grep без anchor
# делал overmatch на любом "Logged in" → ложный early-return.
# Pinned version (supply-chain): @openai/codex@~0.20 — обновление через ADR.
if npx --no-install '@openai/codex@~0.20' login status 2>&1 | grep -qE '^Logged in (using|to) '; then
  exit 0
fi

# Ключа нет — предупреждение, но не ошибка (для работ без внешнего ревью).
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "[codex-login] OPENAI_API_KEY не установлен — /external-review работать не будет." >&2
  echo "[codex-login] Добавь ключ в Claude Code Secrets (см. .agents/CODEX_AUTH.md)." >&2
  exit 0
fi

# Логинимся через stdin; вывод команды подавляем, чтобы не засорять старт сессии.
# Важно: codex login --with-api-key НЕ валидирует ключ на login (только сохраняет
# в auth.json). Реальная валидность проверяется при первом API call. Поэтому
# wording ниже — «установлен», а не «залогинен/валиден» — честное описание.
if printenv OPENAI_API_KEY | npx '@openai/codex@~0.20' login --with-api-key >/dev/null 2>&1; then
  # chmod только если HOME непустой И файл реально существует.
  # Copilot round 2 C-7: при пустом $HOME путь "/.codex/auth.json" абсолютный
  # и на Unix может случайно задеть файл в корне (теоретический, но легитимный
  # security concern). Двойной guard — безопаснее bogus chmod.
  if [ -n "${HOME:-}" ] && [ -f "${HOME}/.codex/auth.json" ]; then
    chmod 600 "${HOME}/.codex/auth.json" 2>/dev/null || true
  fi
  echo "[codex-login] Codex CLI: API key установлен (валидность проверится при первом запросе)."
else
  # Сбой login — возможных причин несколько: невалидный $OPENAI_API_KEY,
  # отсутствие сети, проблема npm/npx cache, отсутствует Node, timeout.
  # Диагностика ниже в .agents/CODEX_AUTH.md §4 troubleshooting таблице.
  echo "[codex-login] Не удалось залогинить Codex CLI. Возможные причины: невалидный \$OPENAI_API_KEY, нет сети, сбой npx/Node или timeout. См. .agents/CODEX_AUTH.md §4." >&2
fi

exit 0
