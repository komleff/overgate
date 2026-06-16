---
name: verify
description: Быстрый healthcheck проекта — сборка + тесты по всем платформам проекта одной последовательностью.
user-invocable: true
---

# Verify — healthcheck проекта

Запусти сборку и тесты для всех платформ проекта, выведи сводный результат.

> **Шаблон.** Командные шаги ниже — `<PLACEHOLDER>`-конвенция. Подставь команды и baseline'ы своего стека (см. `.claude/rules/tests.md`). Имя скилла менять нельзя — `/verify` должен резолвиться. Если у проекта только одна платформа (например, нет отдельного клиента и сервера) — оставь один шаг, второй удали. Если корень проекта — npm workspace, `npm ci` запускается из **корня** репо, а не из leaf-папки клиента (иначе `vite`/`vitest` не доустановятся), а build/test — через корневые root-скрипты, таргетящие workspace.

## Шаг 1 — Клиент / основная платформа

> **fail-fast:** `set -e` + `&&` chain — любая упавшая команда останавливает весь shell-блок.

```bash
set -e  # fail-fast — любой non-zero exit прерывает блок
cd <CLIENT_DIR> \
  && <CLIENT_BUILD_CMD>
cd -
```

`<CLIENT_DIR>` — каталог клиента/основной платформы. `<CLIENT_BUILD_CMD>` — сборка + клиентские тесты (`<TEST_CMD>`) одной цепочкой.

## Шаг 2 — Сервер / вторая платформа

> **fail-fast:** `set -e` + `&&` chain.

```bash
set -e
# <SERVER_BUILD_CMD> покрывает сборку серверного/второго проекта и его тесты.
<SERVER_BUILD_CMD>
```

`<SERVER_BUILD_CMD>` — сборка серверного слоя + запуск его тестов (`<TEST_CMD>`).

## Ожидаемый результат

- Клиент: build без ошибок + тесты зелёные (`<EXPECTED_CLIENT_TESTS>` — baseline в `.claude/rules/tests.md`).
- Сервер: build успешен (warnings до `<WARNING_BASELINE>` — структурный tech-долг, быстрый `/verify` на них не аборти́тся; их baseline и cold-команда аудита регрессий — в `.claude/rules/tests.md`, раздел «Baseline counts») + тесты зелёные (`<EXPECTED_SERVER_TESTS>`).

Если что-то упало — покажи stderr/stdout первого упавшего шага и предложи исправление. Не запускай дальнейшие шаги до исправления (fail-fast). Интеграционные тесты, если есть, держи за отдельным флагом — не включай по умолчанию.

## Пример (U2 reference)

Исходная U2-реализация скилла (TS-клиент Vite/Vitest + .NET сервер NUnit) — как ориентир при заполнении плейсхолдеров:

```bash
# Шаг 1 — TS-клиент (testbed на Vite, в корневом npm workspace)
set -e
# ⚠️ Корень репо — npm workspace ("workspaces": ["src/clients/testbed/*"]):
# npm ci ЗАПУСКАЕТСЯ ИЗ КОРНЯ. Из leaf-папки он ставит лишь её прямые deps —
# vite/vitest не появятся (command not found). Root-скрипты build/test таргетят workspace.
# `-- --run` пробрасывается в корневой test-скрипт и держит vitest в одноразовом (non-watch) режиме.
npm ci \
  && npm run build \
  && npm test -- --run

# Шаг 2 — .NET solution (server entry-point + shared game logic + NUnit тесты)
set -e
# U2.sln покрывает ОБА csproj: U2.Server.csproj (entry) + U2.Shared.csproj
# (где живут реальные тесты в src/shared/Tests/ECS/, Tests/Ships/ и т.д.).
dotnet build U2.sln --configuration Release \
  && dotnet test U2.sln --no-build --configuration Release --verbosity minimal
```

Ожидаемый результат U2: TS ~319 passed / 7 skipped из 326; .NET ~843 passed / 6 skipped из 849 (Release), warnings baseline 105. Подробности — `.claude/rules/tests.md`.
