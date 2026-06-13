---
title: "References — pipeline sources and inspirations"
status: reference
version: "1.1"
date: 2026-05-04
source: "github.com/komleff/overgate/.agents/REFERENCES.md"
tags: [pipeline, references, sources, frameworks]
---

# Референсы и источники

Материалы, на основе которых построен AI-пайплайн проекта.

---

## Конкурирующие фреймворки (проанализированы при создании плана v3.3)

- **Superpowers** — Jesse Vincent / Prime Radiant: композируемые скиллы, принудительный TDD (RED → GREEN → REFACTOR), brainstorming → plan → implement workflow. 93K+ звёзд. Ключевая идея: дисциплина важнее модели.
  https://github.com/obra/superpowers

- **GSD (Get Shit Done)** — meta-prompting и context engineering для Claude Code. Lean Orchestrator на 15% контекстного бюджета, атомарные git-коммиты, субагенты в изолированных контекстах. 23K+ звёзд.
  https://github.com/gsd-build/get-shit-done

- **GitHub Spec-Kit** — официальный тулкит GitHub для Spec-Driven Development. CLI `specify`, constitution.md, шаблоны спецификаций. Агностичен к IDE и модели.
  https://github.com/github/spec-kit

- **BMAD Method** — Breakthrough Method for Agile AI-Driven Development. Персоны-агенты (Analyst, PM, Architect, Scrum Master, Dev), enterprise-grade governance. Самый тяжёлый фреймворк.
  https://github.com/bmad-code-org/BMAD-METHOD

- **OpenSpec** — Spec-Driven Development от Fission AI. Brownfield-first стратегия, компактные спеки (~250 строк), GIVEN/WHEN/THEN сценарии. Поддержка 20+ AI-ассистентов.
  https://github.com/Fission-AI/OpenSpec

- **Фреймворк Молянова** — набор скиллов и команд для Claude Code. User-spec → tech-spec → атомарные задачи → TDD. Заточен под не-программистов. Skill-master и skill-tester для мета-создания скиллов.
  https://github.com/pavel-molyanov/molyanov-ai-dev

- **Superflow** — egerev/superflow: промпт-конвейер для Claude Code
  https://github.com/egerev/superflow

---

## Статьи и практики

- **Memory Bank для Claude Code** — подход к персистентной памяти AI-агентов. Источник паттерна `.memory-bank/` с lazy loading по ролям.
  https://habr.com/ru/articles/896690/

- **Beads — AI Issue Tracker** — интеграция трекера задач в AI-workflow. Источник решения использовать `bd` вместо GitHub Issues.
  https://habr.com/ru/articles/912174/

- **Защита от галлюцинаций в Claude Code** — техники повышения надёжности: deny-rules, hooks, structured prompts.
  https://habr.com/ru/articles/911990/

- **Adversarial Code Review для Claude Code** — кросс-модельное ревью через Codex CLI, adversarial-промпты. Источник скилла `/external-review` и концепции adversarial diversity.
  https://habr.com/ru/articles/1019588/

- **Настройки Claude Code** — hooks, settings.json, плановая директория. Источник паттерна PreToolUse hooks и deny-rules.
  https://habr.com/ru/articles/906750/

- **Фреймворк Молянова (статья на Хабре)** — описание полного цикла: user-spec → tech-spec → задачи → TDD → ревью. Опыт автора, не являющегося разработчиком.
  https://habr.com/ru/articles/1022050/

- **Гигиена проекта при работе с ИИ** — четырёхслойная модель проектной памяти (живое состояние, снимок, стабильные знания, архив решений), ADR как фильтр от «пережитков» — идей, переживших свой контекст. Источник идеи `docs/architecture/ADR-INDEX.md` и обязательного блока «отклонённые альтернативы» в каждом ADR.
  https://habr.com/ru/sandbox/283242/

---

## Документация и инструменты

- **Claude Code** — документация агентного CLI от Anthropic. Субагенты, Agent Teams, worktrees, плагины.
  https://code.claude.com/docs/en/overview

- **Codex CLI** — OpenAI CLI для code review и разработки. Используется в `/external-review` для кросс-модельного ревью.
  https://github.com/openai/codex

- **GitHub Copilot** — auto-reviewer в PR. Используется как дополнительный уровень ревью через `gh api` re-review request.
  https://docs.github.com/en/copilot

- **Beads CLI** — Steve Yegge. AI-native issue tracker, интегрированный в файловую систему и git.
  https://github.com/steveyegge/beads

---

## Аналитика и сравнения

- **Spec-Driven Development Is Eating Software Engineering** — карта 30+ фреймворков агентной разработки (2026). Контекст для позиционирования пайплайна.
  https://medium.com/@visrow/spec-driven-development-is-eating-software-engineering-a-map-of-30-agentic-coding-frameworks-6ac0b5e2b484

- **Superpowers, GSD, and gstack: What Each Framework Constrains** — сравнение подходов: Superpowers ограничивает процесс, GSD ограничивает среду, gstack ограничивает решения.
  https://medium.com/@tentenco/superpowers-gsd-and-gstack-what-each-claude-code-framework-actually-constrains-12a1560960ad

- **GSD vs Spec Kit vs OpenSpec vs Taskmaster AI** — глубокое сравнение контекстной изоляции, brownfield-поддержки, оркестрации.
  https://medium.com/@richardhightower/agentic-coding-gsd-vs-spec-kit-vs-openspec-vs-taskmaster-ai-where-sdd-tools-diverge-0414dcb97e46

- **Agentic Coding Tools 2026: 7 frameworks** — рекомендации по выбору фреймворка в зависимости от масштаба команды и проекта.
  https://www.obviousworks.ch/en/agentic-coding-tools-2026-the-7-frameworks-that-take-your-development-to-a-new-level/

---

## Собственные проекты (эволюция пайплайна)

> `komleff/overgate` (**этот репозиторий**) — канонический project-payload-free reference пайплайна, отчуждённый из U2 (dogfood) в 2026-06. Репозитории ниже — хронология эволюции; новый проект ставить из overgate через `.agents/INSTALL.md`.

- **slime-arena** — первая зрелая реализация PM-оркестратора с мульти-провайдерным review (Opus + Codex + Gemini + Copilot), алгоритмом консенсуса 3+ APPROVED, pm-orchestrator.py. 555 коммитов.
  https://github.com/komleff/slime-arena

- **bonk-race** — основной полигон для экспериментов с пайплайном. 629 коммитов.
  https://github.com/komleff/bonk-race

- **surprise-arena** — компактный проект с активным PR-based workflow. 207 коммитов.
  https://github.com/komleff/surprise-arena

- **big-heroes** — предыдущая итерация пайплайна (snapshot v2.1 / v3.4 pre-merge landing protocol перенесён в U2). Нативные агенты Claude Code, sprint-pr-cycle + external-review скиллы, diagnosis-first режим, AGENTIC_PIPELINE.md как переносимая методология. 160 коммитов.
  https://github.com/komleff/big-heroes

- **Universe Unlimited (U2)** — наиболее зрелый dogfood baseline пайплайна; **из него отчуждён `komleff/overgate` (этот репозиторий)** как канонический reference (2026-06). 2D testbed на TS+Vite+Three.js + .NET 8 server (Entitas ECS) + Unity 3D-клиент.
  - Bootstrap PR #185 (Plan A migration): 21 коммит, 7 итераций cross-model review через GPT-5.4 на iter 1 и GPT-5.5 на iters 2-7, ~10 deferred Beads issues, FINAL APPROVED через `/finalize-pr`.
  - Pipeline docs PR #186 (follow-up): 14+1 итераций cross-model review (Mode A + Mode D operator escalation при quota exhaustion), ~50+ findings closed across Critical/High/Med, **ADR 3.24 formalized convergence detection** + iteration cap по diff-shape (ordinary docs 7, mixed 12, executable/governance 20). INSTALL.md (~600 LOC) — onboarding для миграции в новые проекты.
  https://github.com/komleff/u2
