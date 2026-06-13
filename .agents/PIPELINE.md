---
title: "Pipeline overview — OverGate"
status: active
version: "2.4"
date: 2026-05-19
source: "github.com/komleff/overgate/.agents/PIPELINE.md"
tags: [pipeline, overview, philosophy, invariants]
related:
  - .agents/AGENTIC_PIPELINE.md
  - .agents/HOW_TO_USE.md
  - .agents/AGENT_ROLES.md
  - .agents/INSTALL.md
---

# Пайплайн разработки OverGate

**Версия:** 2.4 (v3.9 + U2 evidence rule for GPT-5.3-Codex invocation)
**Обновлён:** 2026-05-19

---

## 1. Философия

### Zero Trust to Human Tech Skills

1. **Человек не проверяет код.** Оператор принимает решения на основе вердиктов.
2. **Бинарный контроль.** Каждый этап: `APPROVED` или `CHANGES_REQUESTED`.
3. **Автономность качества.** Тесты + 4-аспектное ревью + разделение ролей.

Соло-разработчик управляет ИИ-агентами как менеджер, а не как программист.

### Инварианты

Полный список — `PIPELINE_ADR.md` §3 «Инварианты пайплайна» (7 нумерованных инвариантов). Ключевые в этой сводке (нумерация PIPELINE_ADR §3 в скобках):

1. Все review-pass публикуются в PR одним владельцем (PM) — инвариант #4.
2. Review привязан к commit hash. Нет merge без fresh review на текущем commit — производное от инвариантов #1+#4.
3. Merge — отдельное решение оператора. Только через `/finalize-pr` — инвариант #7.
4. Любое замечание имеет статус: fix now / defer to Beads (с ID) / reject with rationale — инвариант #5.
5. PM не искажает findings ревьюверов — защита findings (ADR 3.12).

---

## 2. Карта компонентов

| Компонент | Тип | Расположение | Назначение |
|-----------|-----|-------------|-----------|
| PM | Роль | `.agents/PM_ROLE.md` (детали), `AGENT_ROLES.md` (сводка) | Оркестрация спринтов |
| Architect | Роль | `.agents/AGENT_ROLES.md` | Архитектурные решения |
| Developer | Роль + агент | `.claude/agents/developer.md` | Реализация, TDD |
| Reviewer | Роль + агент | `.claude/agents/reviewer.md` | Проверка PR по 4 аспектам |
| Tester | Агент | `.claude/agents/tester.md` | Тесты и покрытие |
| Planner | Агент | `.claude/agents/planner.md` | Исследование, планы, Verification Contract |
| verify | Скилл | `.claude/skills/verify/` | Единый build/test gate |
| sprint-pr-cycle | Скилл | `.claude/skills/sprint-pr-cycle/` | Цикл PR: ревью → фикс → отчёт |
| external-review | Скилл | `.claude/skills/external-review/` | Кросс-модельное ревью (4 режима деградации) |
| finalize-pr | Скилл | `.claude/skills/finalize-pr/` | Hard gate перед merge (commit binding) |
| pipeline-audit | Скилл | `.claude/skills/pipeline-audit/` | Проверка консистентности документов |
| Rules | Правила | `.claude/rules/*.md` | Ограничения по типу кода |
| Hooks | Хуки | `.claude/settings.json` | Тесты перед коммитом, PR-gate, deny-rules |
| Memory Bank | Контекст | `.memory-bank/` | Состояние между сессиями |
| Beads | Задачи | `.beads/` | Issue tracking для ИИ |

---

## 3. Жизненный цикл спринта

```
Оператор ставит задачу
       ↓
PM читает Memory Bank + создаёт ветку
       ↓
PM → Planner → план + Verification Contract в docs/plans/
       ↓
PM → Developer → реализует против контракта (TDD)
       ↓
/verify (build + test)
       ↓
git push → gh pr create
       ↓
PM → /sprint-pr-cycle → внутреннее ревью (4 аспекта, commit-bound)
       ↓
CHANGES_REQUESTED? → triage (fix / defer+Beads / reject) → Developer → fix → повтор
       ↓
APPROVED → PM → /external-review → кросс-модельное ревью
       ↓
APPROVED → PM → /finalize-pr <PR_NUMBER> --pre-landing (для Sprint Final) → hard gate
       ↓
✅ Готов к merge (с warning «⏳ landing впереди») → НЕ мержить
       ↓
PM делает chore(landing): commit в ту же ветку
       (activeContext.md + plan archive + bd close + memory entry)
       ↓
Doc-only review round + (для Sprint Final) повторный /external-review
       ↓
PM → /finalize-pr <PR_NUMBER> (без флага) → hard gate на новом HEAD
       ↓
✅ Готов к merge (без warning) → оператор мержит PR
       ↓
Sprint полностью закрыт одним merge — POST-merge шагов нет

(Для tier ≠ Sprint Final: один /finalize-pr без --pre-landing, один merge.)
```

---

## 4. Контекстный бюджет (lazy loading)

| Роль | Файлы Memory Bank при старте |
|------|------------------------------|
| Developer, Tester | `activeContext.md` |
| Planner | `activeContext.md` + `techContext.md` + `systemPatterns.md` |
| Reviewer | `activeContext.md` + `systemPatterns.md` |
| PM | `activeContext.md` |

---

## 5. Режимы деградации external-review

| Режим | Условие | Adversarial diversity |
|-------|---------|----------------------|
| **A** (primary, v3.9) | Codex CLI ChatGPT subscription (`codex login status` → "Logged in using ChatGPT", `[profiles.review]` загружается) | Максимальная (GPT-5.5 + GPT-5.3-Codex через subscription quota) |
| **A-hybrid** | Reviewer A на Codex CLI subscription, Reviewer B на Mode A-legacy (gpt-5.3-codex недоступна через subscription tier) | Максимальная (model diversity сохранена, разные backend'ы) |
| **A-legacy** (v3.6 baseline) | Codex CLI subscription недоступен, `openai-review.mjs --ping` → exit 0 (Platform API доступен) | Максимальная (GPT-5.5 + GPT-5.3-Codex через Platform API; GPT-5.4 fallback) |
| ~~B~~ | ~~ChatGPT login через npx codex subprocess~~ (deprecated в v3.6) | ~~Снижена~~ |
| **C** | Все Mode A варианты недоступны | Degraded (Claude adversarial standard + adversarial passes) |
| **D** | Автоматика недоступна, оператор требует ручной fallback | Ручной (VS Code Copilot Agent или аналог) |

> Backend evolution: v3.6 — `openai-review.mjs` Platform API primary; v3.9 — Codex CLI subscription primary, `openai-review.mjs` сохраняется как Mode A-legacy fallback. Решение: ADR 3.27 (cost-driven). Decision keep both reviewers подтверждён данными big-heroes/surprise-arena (22.7% unique-to-Codex Critical/High; см. `docs/research/2026-05-05-codex-overlap-analysis.md`, U2-275) и U2-native анализом PR #191/#199/#203/#210/#220/#225: GPT-5.3-Codex даёт уникальные P1/HIGH/P2 finding'и на Critical/Sprint Final/runtime/tooling PR, но не вызывается по умолчанию для Light/doc-only/landing проходов (`docs/research/2026-05-19-gpt55-vs-gpt53-codex-u2-review-effectiveness.md`).

---

## 6. Связанные документы

| Документ | Назначение |
|----------|-----------|
| `AGENTIC_PIPELINE.md` | Универсальная методология (ПОЧЕМУ) |
| `PIPELINE_ADR.md` | Решения и обоснования (ПОЧЕМУ ТАК) |
| `AGENT_ROLES.md` | Роли и промпты (КАК) |
| `PM_ROLE.md` | Детальный workflow PM |
| `HOW_TO_USE.md` | Шпаргалка оператора |
| `REFERENCES.md` | Источники и референсы |
| `INSTALL.md` | Установка пайплайна в новый проект (Bootstrap PR pattern) |
