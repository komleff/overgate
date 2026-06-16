# Changelog

Все значимые изменения OverGate документируются в этом файле.
Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/); версия = версия спецификации пайплайна с SemVer-суффиксом.

## [v3.9.0-beta.1] — 2026-06-16

**Первый публичный beta-релиз.** OverGate — переносимый AI-пайплайн разработки для solo-оператора, управляющего флотом ИИ-агентов (PM-оркестрация, разделение ролей, hard-гейты перед merge, кросс-модельное adversarial-ревью). Релиз рассчитан на ранних адаптеров, которые устанавливают пайплайн в свои проекты через [`.agents/INSTALL.md`](.agents/INSTALL.md) и присылают фидбек.

### Added
- `LICENSE` — MIT.
- `CHANGELOG.md` (этот файл).
- Таблица пререквизитов (Python, `gh`, Node.js, `bd`, инструменты внешнего ревью) в `README.md` и `.agents/INSTALL.md §A`.
- Fail-closed гейт на незаполненные `<PLACEHOLDER>` в `/verify` и `.claude/rules/tests.md` при установке (`.agents/INSTALL.md`).
- Helper-скрипты синхронизации Beads: `scripts/bd-sync-export.sh`, `bd-sync-restore.sh`, `bd-sync-common.sh` (PR #3).

### Changed
- **Де-догфудинг** generic-артефактов: убраны операционные U2-утечки — пути `D:\GitHub\u2` → `<REPO_ROOT>`, хост `docs.u2game.space` → `<SITE_HOST>`, npm-скоп `@u2/openai-review` → `@overgate/openai-review`. Provenance-упоминания U2 (родословная, reference baseline) сохранены намеренно.
- Правила Beads и `AGENTS.md` приведены к **bd 1.0.2**: синхронизация через служебную ветку `beads-backup` (`bd export`/`bd import`), Dolt-remote и `bd dolt push/pull` отключены (PR #1, #3).
- Cost-warning для Mode A-legacy внешнего ревью (Platform API дорогой; предпочтителен Codex CLI + ChatGPT subscription).
- Канон heredoc-делимитеров для безопасной публикации больших payload'ов в PR (PR #2).

### Fixed
- `/verify` Шаг 1: `npm ci` запускается из корня репозитория в npm-workspace структуре (раньше из leaf-папки не доустанавливались `vite`/`vitest`) — баг `og-xxj` (PR #4).

### Removed
- Tracked Python-байткод `.claude/skills/sync-site-gdd/scripts/__pycache__/find-missing.cpython-314.pyc`.

### Known limitations (beta)
- `og-mk4` (P3) — hardening helper-скриптов bd-sync (целостность JSONL первого export, drop-guard на гибридном tip, детерминизм порядка ключей). Не дефект контракта синхронизации.
- Узкое окно совместимости трекера: helper-скрипты завязаны на command surface **bd 1.0.2**.
- EXAMPLE-артефакты (`/verify`, `.claude/rules/tests.md`, `/sync-docs`, `/sync-site-gdd`) поставляются с `<PLACEHOLDER>` — требуют адаптации под стек проекта (см. `.agents/INSTALL.md §B.4`).

[v3.9.0-beta.1]: https://github.com/komleff/overgate/releases/tag/v3.9.0-beta.1
