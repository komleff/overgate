# OverGate

**Переносимый AI-пайплайн разработки** для solo-оператора, управляющего флотом ИИ-агентов (Claude Code + кросс-модельное ревью). PM-оркестрация, разделение ролей, hard-гейты перед merge, кросс-модельное adversarial-ревью.

**Версия пайплайна:** v3.9 · **Статус:** канонический reference (отчуждён из dogfood-проекта [U2](https://github.com/komleff/u2), 2026-06)

---

## Философия — Zero Trust to Human Tech Skills

1. **Человек не проверяет код.** Оператор принимает решения по вердиктам (`APPROVED` / `CHANGES_REQUESTED`).
2. **Бинарный контроль** на каждом этапе.
3. **Автономность качества** — тесты + 4-аспектное ревью + разделение ролей.

Соло-разработчик управляет ИИ-агентами как менеджер, а не как программист.

---

## Требования

| Инструмент | Зачем |
|---|---|
| Claude Code (Opus 4.7+) | основной агент-исполнитель |
| `git` + GitHub CLI (`gh`, authenticated) | ветки, PR, review-операции |
| **Python 3.x** (`py`/`python3`/`python`) | hook `check-merge-ready.py`, EXAMPLE-скилл `/sync-site-gdd` |
| **Node.js ≥ 18.17.0** | `openai-review.mjs` (Mode A-legacy внешнего ревью) |
| **Beads `bd` ≥ 1.0.2** | трекер задач + helper-скрипты синхронизации |
| ChatGPT subscription + Codex CLI **или** `OPENAI_API_KEY` | кросс-модельное внешнее ревью (Mode A); иначе degradation Mode C/D |

Детали и проверки — [`.agents/INSTALL.md §A.1`](.agents/INSTALL.md).

---

## Установка в новый проект

```
Ты — установщик OverGate-пайплайна. Прочитай .agents/INSTALL.md секцию B
и выполни Bootstrap PR в этом проекте.
```

Полная инструкция — [`.agents/INSTALL.md`](.agents/INSTALL.md) (короткая для оператора + детальная для AI-агента). Шпаргалка оператора — [`.agents/HOW_TO_USE.md`](.agents/HOW_TO_USE.md).

---

## Что внутри

| Слой | Где | Назначение |
|------|-----|-----------|
| **Роли** | [`.agents/AGENT_ROLES.md`](.agents/AGENT_ROLES.md), [`PM_ROLE.md`](.agents/PM_ROLE.md) | PM, Architect, Developer, Reviewer, Tester, Doc Sync |
| **Нативные агенты** | `.claude/agents/` | developer, planner, reviewer, tester |
| **Скиллы** | `.claude/skills/` | `/verify`, `/sprint-pr-cycle`, `/external-review`, `/finalize-pr`, `/pipeline-audit`, `/project-manager`, `/architect` + EXAMPLE: `/sync-docs`, `/sync-site-gdd` |
| **Хуки** | `.claude/hooks/`, `.claude/settings.json` | merge-ready gate (`check-merge-ready.py`), тесты перед коммитом, deny-rules, Codex SessionStart-логин |
| **Правила** | `.claude/rules/` | `universal.md`, `large-payloads.md` + EXAMPLE: `tests.md` |
| **Инструменты** | `.claude/tools/` | `openai-review.mjs` (Mode A-legacy внешнего ревью), `codex-account-switch.ps1` |
| **ADR-процесс** | `docs/architecture/` | `ADR-0000` (процесс), `ADR-TEMPLATE.md`, `ADR-INDEX.md` |
| **Контекст** | `.memory-bank/` | состояние между сессиями (lazy-loading по ролям) |

Карта компонентов и жизненный цикл спринта — [`.agents/PIPELINE.md`](.agents/PIPELINE.md). Решения и обоснования — [`.agents/PIPELINE_ADR.md`](.agents/PIPELINE_ADR.md).

---

## Жизненный цикл спринта (коротко)

```
Оператор → PM (Memory Bank + ветка) → Planner (план + Verification Contract)
   → Developer (TDD) → /verify → PR → /sprint-pr-cycle (4 аспекта, commit-bound)
   → /external-review (5-режимная mode chain: GPT-5.5 + GPT-5.3-Codex)
   → /finalize-pr (hard gate) → pre-merge landing → оператор мержит
```

Внешнее ревью — кросс-модельное (Codex CLI ChatGPT subscription primary; `openai-review.mjs` Platform API как Mode A-legacy fallback). Настройка Codex — [`.agents/CODEX_AUTH.md`](.agents/CODEX_AUTH.md).

---

## Адаптация под стек

OverGate generic-strict: ядро копируется как есть, а **стек-/проект-специфичные артефакты помечены EXAMPLE и заполняются под проект** (`<PLACEHOLDER>`-команды):

- `/verify` и `.claude/rules/tests.md` — подставь свои build/test-команды и baseline-числа.
- `/sync-docs`, `/sync-site-gdd` — пример doc/site-навигации; адаптируй пути или удали `sync-site-gdd`, если нет публичного сайта.

Детали адаптации — `.agents/INSTALL.md §B.4`.

---

## Родословная

Эволюция пайплайна: `slime-arena` → `bonk-race` → `surprise-arena` → `big-heroes` → **U2** (зрелый dogfood) → **overgate** (этот канонический reference). Полный список источников и фреймворков-вдохновителей — [`.agents/REFERENCES.md`](.agents/REFERENCES.md).

---

## Лицензия

[MIT](LICENSE) © 2026 Dmitriy Komlev. Копируй, адаптируй и внедряй пайплайн в свои проекты свободно.
