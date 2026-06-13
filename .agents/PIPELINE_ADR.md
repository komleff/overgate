---
title: "Pipeline ADRs"
status: decision
version: "v3.9"
date: 2026-05-05
source: "github.com/komleff/overgate/.agents/PIPELINE_ADR.md"
tags: [pipeline, adr, decisions, history]
related:
  - .agents/PIPELINE.md
  - .agents/INSTALL.md
  - .agents/pipeline-improvement-plan-v3.3.md
---

# ADR: Архитектура AI-пайплайна разработки

**Статус:** Принято
**Дата принятия:** 2026-04-05
**Последнее ревью эволюции:** 2026-05-05 (v3.9 — ADR 3.27: внешнее ревью → Codex CLI ChatGPT subscription primary, `openai-review.mjs` → Mode A-legacy fallback; полная хронология — таблица «Sprint Pipeline version history» ниже. Ранее: 2026-05-04 v3.7 — решения 3.16–3.24 по U2 PR #185/#186)
**Тип документа:** Историческая запись принятых решений. Не обновляется в каждом спринте — только при принятии новых ADR. Текущее состояние пайплайна см. в `PIPELINE.md`, `AGENT_ROLES.md`, `PM_ROLE.md`.
**Авторы:** PM (Claude Opus 4.6/4.7) + GPT-5.4/5.5 + Оператор
**Источники:** PIPELINE_ADR.md (Opus), AGENTIC_PIPELINE.md (GPT-5.4), U2 PR #185 (Bootstrap dogfood)

### Sprint Pipeline version history

Версия пайплайна (Sprint Pipeline vN.M) отличается от версии этого документа (PIPELINE_ADR vN.M) — pipeline version отслеживает протокольные приращения (новые гейты, новые режимы, новые ADR-семейства), а doc version — версию самого ADR-документа.

| Sprint Pipeline | Когда | Что добавлено |
|----------------|-------|---------------|
| v3.3 | 2026-04-13 | ADR 3.11-3.15: hard gate `/finalize-pr`, единый владелец публикации, Verification Contract, triage protocol, контекстная изоляция PM |
| v3.4 | 2026-04-20 | Pre-merge landing protocol (PM_ROLE.md §2.5): landing artifacts inline-в-ветке PR через dual-invocation `/finalize-pr --pre-landing` → landing commit → `/finalize-pr` |
| v3.5 | 2026-04-22 | Light tier для doc-only (2 аспекта: Архитектура + Гигиена кода); Critical tier расширен на нормативные артефакты пайплайна (`.claude/settings.json` hooks, `.agents/*.md` governance) |
| v3.6 | 2026-04-30 | `/external-review` через Node.js native `openai-review.mjs` (Mode A); Codex CLI subprocess deprecated до legacy fallback (Mode B deprecated) |
| v3.7 | 2026-05-04 | ADR 3.16-3.24: Bootstrap PR pattern (chicken-and-egg формализация), trust boundary через `--head`, matcher coverage `*gh pr comment*`, hook catch-22 fix, Mode C для landing, bash $VAR rule, GPT-5.5 stateless dedup, FINALIZE_PR_TOKEN inline, **external review iteration cap + convergence detection + binary escalation (3.24)**. INSTALL.md как onboarding deliverable |
| v3.8 | 2026-05-05 | ADR 3.27: External review backend → Codex CLI ChatGPT subscription path (primary). `openai-review.mjs` Platform API остаётся как Mode A-legacy fallback. Profile `[profiles.review]` в `~/.codex/config.toml` для pipeline isolation. Dual-account swap script (`.claude/tools/codex-account-switch.ps1`). CODEX_AUTH.md §8/§9 split. Governance docs sync (AGENT_ROLES.md tier table, PIPELINE.md §5 modes, INSTALL.md §B.x) — отложено в Beads U2-rhm (отдельный план переписывания `external-review/SKILL.md`). |
| v3.9 | 2026-05-05 | U2-rhm: `external-review/SKILL.md` переписан под Codex CLI subscription primary path (Шаги 1.4 двухступенчатый availability check, 2 mode table расширена до 5 режимов, 3.1 Mode A primary через `codex -p review --commit`, 3.1.2 hybrid fallback Reviewer B → Mode A-legacy при недоступности gpt-5.3-codex на subscription tier, 3.1.3 Mode A-legacy full path как v3.6 baseline, 5.1 attribution table, 7.1/7.2/7.3 error handling split). Decision keep both reviewers подтверждён данными big-heroes/surprise-arena (U2-275 research: 22.7% unique-to-Codex Critical/High > 20% threshold). Governance docs synced: AGENT_ROLES.md Sprint Final tier, PIPELINE.md §5 modes table, INSTALL.md §B.8/§D.3/§D troubleshooting. Source: `docs/research/2026-05-05-codex-overlap-analysis.md`. |

---

## 1. Контекст

**Команда:** один человек-оператор без глубоких технических навыков + несколько ИИ-моделей (Claude Opus, GPT-5.4, GPT-5.3-Codex, GitHub Copilot).

**Ключевое ограничение:** оператор не читает и не ревьюит код — он управляет агентами через промпты и принимает решения на основе бинарных вердиктов (`APPROVED` / `CHANGES_REQUESTED`).

Это означает, что пайплайн должен быть:
- **Самопроверяющимся** — качество гарантируется автоматически, не человеком
- **Атомарным** — каждый шаг завершается полностью или откатывается
- **Прозрачным** — оператор получает отчёты на понятном языке, не diff-ы

---

## 2. Философия: Zero Trust to Human Tech Skills

Центральный принцип, из которого вытекают все остальные решения:

> Соло-разработчик управляет ИИ-агентами как менеджер, а не как программист.

### Три директивы

1. **Человек не проверяет код.** Если качество зависит от того, что оператор заметит баг в diff — система сломана.
2. **Бинарный контроль.** Каждый этап заканчивается вердиктом: `APPROVED` или `CHANGES_REQUESTED`. Нет полутонов.
3. **Автономность качества.** Тесты + 4-аспектное ревью + разделение ролей = качество без человеческого кода-ревью.

### Почему не «один агент делает всё»

Один агент (даже мощный) склонен к confirmation bias — он ревьюит собственный код и находит меньше ошибок. Разделение на роли создаёт adversarial dynamic: Developer пишет, Reviewer ломает, PM арбитрирует.

---

## 3. Инварианты пайплайна

Инварианты — это механизмы, которые **нельзя убирать** без нового явного обоснования. Локальная оптимизация, ослабляющая инвариант, — это не оптимизация, а ослабление контроля.

1. **Роли разделены.** Один агент не может быть единственным источником реализации, оценки качества и решения о завершённости.
2. **Код идёт через build/test gate.** Ревью начинается только после прохождения машинных проверок.
3. **Ревью идёт вокруг существующего PR.** У обсуждения должен быть публичный контейнер с историей.
4. **Результат ревью публикуется в PR.** Push без отчёта = незавершённый цикл.
5. **У незавершённой работы есть адрес в task tracker.** Замечание без issue = потерянный долг.
6. **Контекст между сессиями не живёт только в чате.** Memory layer обязателен.
7. **Merge — отдельное решение оператора.** Агенты доводят до merge-ready, но не мержат.

### Антипаттерны (нарушение инвариантов)

- Один агент пишет код и сам себя окончательно одобряет.
- PR создаётся слишком поздно, после скрытых локальных циклов.
- Push считается завершением работы.
- Замечания исправлены, но не опубликовано, что именно изменилось.
- Документация говорит одно, а хуки и реальные команды делают другое.
- Memory Bank разрастается до полной копии репозитория.
- Найденный долг не занесён в task tracker.
- Пайплайн редактируется точечно, без сверки всех связанных инструкций.

---

## 4. Ключевые решения

### 3.1 Пять ролей агентов

**Решение:** PM, Architect, Developer, Reviewer, Tester — пять отдельных ролей с разными инструкциями.

**Обоснование:**
- **PM** нужен для оркестрации: последовательность шагов, делегирование, контроль прогресса. Без PM каждый агент работал бы в вакууме.
- **Architect** нужен для стратегических решений (декомпозиция, RFC). Developer не должен сам решать архитектуру — это scope creep.
- **Developer** и **Tester** разделены, потому что автор кода не должен писать все тесты для своего кода (TDD допускает это, но Tester может добавить edge-cases, которые Developer не предусмотрел).
- **Reviewer** — отдельная роль, не Developer, потому что самоRevью неэффективно.

**Альтернатива отвергнута:** единый агент «Full-Stack AI» — быстрее, но нет adversarial проверки.

### 3.2 Четыре аспекта ревью

**Решение:** каждый Standard/Critical ревью проверяет ровно 4 аспекта:
1. **Архитектура** — разделение слоёв, чистота `shared/`, соответствие архитектурному документу
2. **Безопасность** — XSS, injection, OWASP Top 10
3. **Качество** — тесты, edge-cases, производительность (< 16 мс/кадр)
4. **Гигиена кода** — мёртвый код, дублирование типов, захардкоженные константы

**Обоснование:**
- Первые три аспекта — каноничные для любого ревью. Но агенты систематически пропускали «тихие» проблемы: мёртвый код, дублирование типов между `shared/` и `client/`, числа вместо `balance.json`. Четвёртый аспект «Гигиена кода» был добавлен после Pipeline Audit (PR #3), потому что эти проблемы не покрывались ни одним из трёх.
- Фиксированный список из 4 пунктов — это чеклист, а не свободная форма. Агенты следуют чеклистам лучше, чем инструкции «проверь всё».

**Альтернатива отвергнута:** свободная форма ревью («проверь PR») — приводит к тому, что агент проверяет поверхностно и пропускает целые категории.

### 3.3 Четыре уровня ревью (Review Tiers)

**Решение:**

| Уровень | Когда | Глубина |
|---------|-------|---------|
| **Light** | doc-only, конфиги | Один проход, без тестов |
| **Standard** | Фичи, рефакторинг | Все 4 аспекта |
| **Critical** | `shared/`, `balance.json`, формулы | Два прохода, 4 аспекта |
| **Sprint Final** | Перед merge в main | Внешние модели (GPT-5.4 + GPT-5.3-Codex) |

**Обоснование:**
- Не все PR одинаково рискованны. Doc-only PR не нуждается в тестах — но до Pipeline Audit правило «PR без тестов будет отклонён» блокировало и документацию.
- **Critical** получает два прохода, потому что `shared/` — единственный источник игровой математики. Ошибка здесь = ошибка во всей игре.
- **Sprint Final** использует внешние модели: Claude Opus ревьюит код, написанный Claude Opus — однако GPT-5.4 имеет другие bias и ловит другие ошибки. Кросс-модельное ревью — это adversarial diversity.

**Альтернатива отвергнута:** одинаковый уровень для всех PR — слишком много overhead на документацию, слишком мало внимания критичному коду.

### 3.4 Hard Gate на публикацию отчётов

**Решение:** сессия агента не завершена, пока не выполнены оба шага: `git push` + `gh pr comment` (при наличии PR).

**Обоснование:**
- До Pipeline Audit агенты систематически пропускали публикацию отчётов. Триггером завершения считался `git push`, а отчёт — опциональным «хорошим тоном». В результате PR содержал коммиты, но оператор не получал объяснений.
- Корневая причина: правила были аддитивными (soft constraints), а не блокирующими. Агент мог «забыть» мягкое правило без последствий.
- Решение: в AGENTS.md, PM_ROLE.md, reviewer.md и sprint-pr-cycle/SKILL.md фраза «push прошёл — цикл завершён» заменена на жёсткое условие. Self-check таблица PM содержит строку «Push прошёл — цикл завершён → Нет».

**Урок:** для ИИ-агентов soft constraints = no constraints. Если шаг обязателен — он должен быть записан как hard gate с явным «НЕ завершено, пока X не выполнен».

### 3.5 Comment-only (`gh pr comment`, не `gh pr review`)

**Решение:** все агенты публикуют через `gh pr comment`, никогда через `gh pr review`.

**Обоснование:**
- Все агенты работают под аккаунтом оператора (одна личная машина, один GitHub-аккаунт).
- GitHub не позволяет автору PR ревьюить свой собственный PR через `gh pr review` — команда падает с ошибкой.
- `gh pr comment` не имеет этого ограничения и подходит для публикации вердиктов и отчётов.

**Альтернатива на будущее:** отдельные bot-аккаунты для каждой роли — тогда можно будет использовать `gh pr review` и получить встроенные Approve/Request Changes.

### 3.6 Memory Bank — персистентный контекст между сессиями

**Решение:** `.memory-bank/` содержит 5 файлов контекста. Каждая роль при старте читает только нужные файлы (lazy loading).

**Обоснование:**
- ИИ-агенты не имеют долгосрочной памяти между сессиями. Без Memory Bank каждая новая сессия начинается с нуля — агент не знает, что было сделано.
- Lazy loading: Developer читает только `activeContext.md` (что делать), Reviewer — `activeContext.md` + `systemPatterns.md` (что проверять). Полная загрузка всех файлов тратит контекстное окно на ненужную информацию.

**Источник:** подход заимствован из [Superpowers](https://github.com/obra/superpowers) и адаптированной [Memory Bank для Claude Code](https://habr.com/ru/articles/896690/).

### 3.7 Beads — AI Issue Tracker

**Решение:** `bd` (beads) — трекер задач, встроенный в CLI и файловую систему (`.beads/`).

**Обоснование:**
- GitHub Issues требует API-вызовов и имеет ограничения rate limiting. Beads работает локально и интегрируется в git.
- ИИ-агенты лучше работают с CLI-командами, чем с web API. `bd create`, `bd close`, `bd ready` — простые команды, не требующие авторизации.

**Источник:** [Beads — AI Issue Tracker](https://habr.com/ru/articles/912174/).

### 3.8 Pre-commit хуки (тесты перед коммитом)

**Решение:** `.claude/settings.json` содержит hook `PreToolUse` на `Bash(git commit*)`: запуск `npm run test` перед каждым коммитом.

**Обоснование:**
- Агент может накопить ошибки и закоммитить нерабочий код. Hook физически блокирует коммит, если тесты падают — это не правило, которое можно «забыть», а enforcement на уровне инфраструктуры.
- Второй hook на `Bash(gh pr comment*)` проверяет наличие PR — нельзя отправить отчёт в несуществующий PR.

### 3.9 Deny-правила в settings.json

**Решение:** прямой push в `main` (и legacy `master` для совместимости с исходными big-heroes deny-rules) физически заблокирован через `.claude/settings.json` deny-правила.

**Обоснование:**
- Даже если агент «забудет» правило «не пушить в main», deny-правило не даст выполнить команду. Это defence in depth: правило в документации + enforcement в конфигурации.
- Заблокированы также `--force` push, `gh pr merge`, `gh repo delete` — необратимые действия оставлены только оператору.

### 3.10 Автоматическое кросс-модельное ревью через Codex CLI

> ℹ️ Решение и Обоснование ниже зафиксированы в редакции v3.6 (две модели авторизации: API key / ChatGPT login; модели GPT-5.4). Это исторический ADR — проза не переписывается. Актуальный backend v3.9 (5-режимная mode chain, Codex CLI subscription primary) — см. блок «Backend evolution» в конце этого ADR + ADR 3.27.

**Решение:** Sprint Final выполняется автоматически скиллом `/external-review`. В API key режиме: два ревьюера (GPT-5.4 + GPT-5.3-Codex) последовательно по **всем 4 аспектам**. В ChatGPT login режиме: один проход дефолтной модели (ограничение CLI не позволяет различить проходы) (архитектура, безопасность, качество, гигиена кода). Claude PM консолидирует результаты и публикует в PR. Copilot re-review запрашивается автоматически после каждого fix-цикла.

**Обоснование:**

- До этого Sprint Final был ручным: PM готовил промпты в `docs/plans/sprint-N-review-prompts.md`, оператор копировал в ChatGPT/Codex, результаты возвращал PM. Bottleneck и источник ошибок.
- Codex CLI (`codex review --base "$BASE_BRANCH"`, где base берётся из PR; global binary, не `npx`-подпроцесс) позволяет вызвать внешние модели из CLI с diff-awareness — модель видит полный контекст файлов, а не только diff.
- Оба ревьюера проверяют все 4 аспекта (а не делят между собой) — максимизирует adversarial diversity. Практика Sprint 2 и Sprint 3 показала: GPT-5.4 и GPT-5.3-Codex находят разные проблемы в одних аспектах.
- Формат вердикта един для внутреннего и внешнего ревью (4 аспекта) — предотвращает drift.
- Adversarial-промпты (attack_surface, finding_bar, scope_exclusions) из [статьи](https://habr.com/ru/articles/1019588/) снижают noise и фокусируют ревью на реальных проблемах.
- Скилл поддерживает два режима авторизации: API key (две разные модели, полная adversarial diversity) и ChatGPT login (один проход дефолтной модели — ограничение CLI не позволяет различить проходы). Fallback автоматический.

**Альтернативы отвергнуты:**

| Альтернатива | Почему отвергнута |
|-------------|-------------------|
| Разделение аспектов между моделями (GPT-5.4 = арх+кач, Codex = без+тесты) | Снижает adversarial diversity — каждая модель видит только часть картины |
| Ручной процесс (текущий) | Медленный, error-prone, зависит от оператора |
| 5-й аспект «Тесты» для внешнего ревью | Drift с внутренним форматом (4 аспекта); тесты проверяются в «Качество» |

**Связь с инвариантами:**

- Инвариант 1 (роли разделены): сохранён — внешние модели ревьюят, Claude PM оркестрирует
- Инвариант 4 (результат в PR): сохранён — Pre-Chat Gate обязателен
- Инвариант 6 (контекст между сессиями): сохранён — Memory Bank не затрагивается, PM по-прежнему обновляет `.memory-bank/activeContext.md` при завершении спринта (PM_ROLE.md секция 2.5)
- Инвариант 7 (merge = решение оператора): сохранён

**Backend evolution:**

- **v3.6 (изначально):** Platform API key (`OPENAI_API_KEY` + `openai-review.mjs`); Codex CLI запускался как `npx`-подпроцесс без глобальной установки.
- **v3.9 (2026-05-05, см. ADR 3.27):** primary backend — Codex CLI ChatGPT subscription, global binary `codex`. Platform API сохранён как Mode A-legacy fallback (`openai-review.mjs`).

Решение об автоматизации cross-model ревью через Codex CLI (ядро этого ADR) остаётся валидным; меняется только конкретный invocation pattern. ADR 3.10 сохраняет статус `active`.

**Источник:** [Adversarial Code Review для Claude Code](https://habr.com/ru/articles/1019588/)

### 3.11 Hard gate для merge-readiness (`/finalize-pr`)

**Решение:** Новый скилл `/finalize-pr` — единственный разрешённый способ объявить PR готовым к merge. Прямой `gh pr comment` с текстом «готово к merge» перехватывается hook-ом. Скилл проверяет: verify на текущем commit, review привязан к commit hash, external review для Sprint Final, triage всех замечаний.

**Обоснование:**
- PM систематически объявлял merge-ready, пропуская повторный ревью или незакрытые замечания. Чеклист «PM обязан» не работал — это была рекомендация, не enforcement.
- Commit binding (review привязан к hash) закрывает конкретный сценарий: review → fix → merge без re-review.
- Emergency override `--force` (только по команде оператора) предотвращает pipeline deadlock при сбое скилла.

**Источник:** План v3.3, 5 раундов кросс-модельного ревью.

### 3.12 Единый владелец публикации + защита findings

**Решение:** PM — единственный владелец публикации review-pass. Reviewer-субагенты возвращают structured findings PM, не публикуют самостоятельно. PM не имеет права изменять findings (только структурирование и triage). Raw output внешних ревьюверов сохраняется в collapsible блоке.

**Обоснование:**
- Два режима публикации (PM или Reviewer) создавали серую зону ownership и потерю отчётов.
- PM мог «сгладить» или потерять findings при консолидации, нарушая Zero Trust.

### 3.13 Verification Contract до кода

**Решение:** Planner обязан создать секцию с acceptance criteria, expected behaviors, edge-cases и списком тестов до начала реализации. Reviewer в аспекте «Качество» проверяет покрытие контракта. Отсутствие контракта → автоматический `CHANGES_REQUESTED`.

**Обоснование:** Без независимого контракта TDD вырождается в «тесты подтверждают, что код делает то, что делает», а не «код делает то, что требуется». Подход близок к OpenSpec (GIVEN/WHEN/THEN), но в более компактной форме.

### 3.14 Протокол triage замечаний

**Решение:** Каждое замечание получает статус: fix now / defer to Beads (с обязательным ID) / reject with rationale. Defer без Beads ID = неразрешённое замечание. При >50% defer `/finalize-pr` выдаёт warning.

**Обоснование:** Без формализованного triage замечания либо терялись (нарушение инварианта 5), либо бесконечно блокировали merge. Исторически подтверждено: «потом добавим → забыли → потеряли».

### 3.15 Контекстная изоляция PM

**Решение:** PM обновляет activeContext.md после каждой задачи, формирует handoff packet после каждого review-pass. После 3 задач или 5 review-итераций — обязательная рекомендация session reset.

**Обоснование:** Основная деградация контекста — от длинного review-loop (5–10 итераций), не от числа задач. Процедурные правила заменяют субъективную оценку PM.

### 3.16 Bootstrap PR pattern (chicken-and-egg для self-installing pipeline)

**Решение:** Первая миграция пайплайна в новый проект выполняется через **Bootstrap PR** — один большой PR, который содержит сам пайплайн, проходит свой же первый review-cycle и завершается ручным merge оператора. Для последующих PR (обычные спринты) hard gates `/finalize-pr` обязательны без исключений.

**Обоснование:**

- Парадокс самоустанавливающегося пайплайна: hard gates требуют пайплайн, но первый PR — это и есть пайплайн.
- В U2 PR #185 решено через **один разовый ручной gate** (merge оператора). Все остальные шаги (review/fix/external/finalize) проходят как обычно: hooks и skills уже работают на ветке после первого commit.
- Альтернатива (полная автоматизация Bootstrap merge через override) отвергнута: нарушает инвариант 7 (merge — решение оператора) и создаёт рекурсивную дыру в trust model.

**Источник:** U2 PR #185 — 21 коммит, 7 итераций cross-model review через GPT-5.4 на iter 1 + GPT-5.5 на iters 2-7, ~10 deferred Beads issues.

**Bootstrap landing protocol (revised 2026-05-05 после PR #186 retrospective):** Bootstrap PR следует **тому же pre-merge inline landing pattern** что обычный Sprint Final (см. PM_ROLE.md §2.5).

> ⚠️ **REVISION:** Прежняя версия ADR 3.16 (до 2026-05-05) предписывала post-merge landing для Bootstrap PR с обоснованием «Bootstrap COMPLETE имеет смысл только ПОСЛЕ фактического merge». Это был **over-engineered design**. Reasoning исправлен:
>
> 1. Запись «Bootstrap COMPLETE» в Memory Bank на ветке PR — это **intent**, который становится фактом ПОСЛЕ operator merge. Это semantic identical для любого Sprint Final landing (запись «Sprint N завершён» тоже становится фактом после merge).
> 2. Operator pain point из PR #186 retrospective: «не нравится такая бюрократия! гораздо проще было сделать landing в последнем коммите вместе с finalize».
> 3. **Branch protection на main** делает Путь 2 (operator direct push) технически невозможным. Остаётся либо follow-up PR (бюрократия), либо inline pre-merge landing (стандартный pattern v3.4). Inline всегда выигрывает.
>
> Bootstrap «exception» больше **не существует**. Все Sprint Final PR (включая Bootstrap) используют один и тот же v3.4 dual-invocation pattern: `/finalize-pr --pre-landing` → landing commit inline → `/finalize-pr` → operator merge. PR #186 фактически использовал post-merge landing исторически, но это исключение из обновлённого правила, не precedent.

**Связанный документ:** `.agents/INSTALL.md` секция C — полное описание Bootstrap pattern для будущих миграций.

### 3.17 Trust boundary через `--head` флаг (без `gh pr checkout`)

**Решение:** `external-review` skill принимает `--head <ref>` параметр и работает с PR head как с локальным ref, **не выполняя `gh pr checkout`**. PR head fetched через `git fetch origin pull/N/head:refs/pull/N/head`, скрипт читает diff против base без переключения worktree.

**Обоснование:**

- `gh pr checkout` переключает worktree в untrusted PR код — потенциальный leak prompts из `.claude/skills/` в среду, контролируемую внешним PR-автором (worst case: malicious PR с инструкциями для хук-перехвата).
- Trust boundary держится через separation: trusted base (main/local feature) → fetch untrusted PR head как ref → diff/review без checkout.
- В U2 PR #185 Step 7.5 архитектурно переписан `openai-review.mjs` для приёма `--head`. Это устранило класс уязвимостей.

**Источник:** GPT-5.5 finding в Step 7.5 cross-model review, U2 PR #185.

### 3.18 PreToolUse matcher coverage для `gh pr comment`

**Решение:** Hook `.claude/hooks/check-merge-ready.py` подключён через **расширенный matcher pattern** в `.claude/settings.json`: `"Bash(*gh pr comment*)"` (wildcard на оба конца), а не узкий `"Bash(gh pr comment*)"`.

**Обоснование:**

- Узкий matcher не срабатывал на цепочечные команды (`some-cmd && gh pr comment ...`) и backtick-обёрнутые вызовы.
- Wildcard matcher гарантирует hook coverage на любую форму вызова — это инвариант 4 (результат в PR должен пройти hard gate).
- Тестировано в U2 PR #185 Step 7.6 — defence-in-depth для `--body-file` блокировки и `## ✅ Готов к merge` enforcement.

**Источник:** Internal review-pass U2 PR #185 Step 7.6.

### 3.19 Hook catch-22 в bootstrap-режиме

**Решение:** PR-existence check (`gh pr list --head $BRANCH`) удалён из hook `check-merge-ready.py`. Раньше hook требовал существования PR перед публикацией comment — но в Bootstrap-режиме (или при первом push с trusted base без PR) это блокировало `external-review`.

**Обоснование:**

- Catch-22: external-review публикует отчёт в PR, hook требует PR существования для публикации, но скрипт сам ещё не дошёл до создания PR.
- Решение: убрать matcher на PR-existence, оставить только matchers на содержание (no `## ✅ Готов к merge` без `/finalize-pr`).
- Trade-off: теоретически можно опубликовать comment в несуществующий PR — но `gh pr comment` в этом случае сам падает с понятной ошибкой, hook не нужен.

**Источник:** GPT-5.5 finding iter 6, U2 PR #185 Step 7.10.

### 3.20 Mode C (degraded) допустим для doc-only landing commit

**Решение:** Для landing commit (Memory Bank update, plan archive, bd close, memory entry) допустим **Mode C external-review** (Claude adversarial вместо GPT). Это не общая релаксация — только для landing artifacts со scope `*.md` без логики.

**Обоснование:**

- Landing commit меняет только doc/state — нет game logic, нет кода. Cross-model adversarial diversity даёт минимальный value на doc-only.
- В U2 PR #185 Step 7.11 проверено эмпирически: Mode C для landing commit прошёл без скрытых проблем, GPT не нашёл бы дополнительных findings.
- Sprint Final без landing (полный код-PR) по-прежнему требует Mode A — это не размывается.

**Источник:** U2 PR #185 Step 7.11 (landing review pass).

### 3.21 Bash variable expansion правило для `bd` команд

**Решение:** Все `bd create --description=...`, `bd remember "..."` и аналогичные команды с потенциально-чувствительными значениями **обязательно** используют single-quoted строки. Double-quoted с `$VAR` запрещены — bash раскрывает переменную ДО передачи в `bd`, и значение попадает в Beads/Dolt persisted state.

**Обоснование:**

- В U2 PR #185 mid-session оператор-Claude использовал `bd create --description="...$OPENAI_API_KEY..."` для создания issue с context — bash раскрыл `$OPENAI_API_KEY` в реальный ключ, который попал в Beads и Dolt.
- GitHub push protection заблокировал leak в public, но local Dolt history уже содержал secret.
- Single-quoted ('text') — bash не раскрывает переменные внутри. Это default правило для всех bd-команд с user-controlled или env-derived контентом.

**Источник:** U2 PR #185 mid-session incident, memory `bash-vs-bd-create-no-shell-vars`.

### 3.22 GPT-5.5 stateless dedup для повторяющихся findings

**Решение:** GPT-5.5 (как и любая stateless модель) при повторных вызовах не помнит предыдущие итерации и может повторять уже triage'нутые findings. PM **агрегирует duplicates** по правилу `AGENT_ROLES.md "Защита findings"` — не запускает повторный fix-cycle, отмечает в triage `previously addressed in iter N (commit <hash>)`.

**Обоснование:**

- В U2 PR #185 после iter 3 GPT-5.5 начал повторять findings из iter 1 (например, про `dotnet test src/server/U2.Server.csproj` после fix на `U2.sln`).
- Без dedup PM запускал бы бесконечный fix-cycle на одни и те же replays.
- PM не имеет права изменять/удалять findings, но **агрегация duplicates с reference на предыдущую итерацию** — допустимое структурирование.

**Источник:** U2 PR #185 iters 4-7 (повторяющиеся replays), AGENT_ROLES.md §3 Reviewer.

### 3.23 `FINALIZE_PR_TOKEN` inline env (safety guard, не security boundary)

> ⚠️ **Уточнение semantics (по итогам external review iter 2 PR #186, gpt-5.5):** `FINALIZE_PR_TOKEN=1` — это **safety guard от случайной публикации**, НЕ security boundary против намеренного обхода. Любой агент или оператор может вручную установить переменную и вызвать `gh pr comment ...` — hook пропустит. Защита от accidental misuse (опечатка, copy-paste из другого контекста), не от malicious intent. Real security boundary — review-pass binding к commit hash + операторский merge как final gate (инвариант #7).

**Решение:** `/finalize-pr` skill использует одноразовый `FINALIZE_PR_TOKEN=1` env-var, передаваемый **inline** в команде (`FINALIZE_PR_TOKEN=1 gh pr comment ...`), а не через `export` или `setx`. PreToolUse hook check-merge-ready.py читает `os.environ.get("FINALIZE_PR_TOKEN")` и пропускает `## ✅ Готов к merge` только если token = "1".

**Обоснование:**

- Empirical proof в U2 PR #185 Step 7.10: Python child process inheritance работает корректно — inline env передаётся в subprocess `gh`, hook видит token, пропускает publish.
- Альтернатива (`export FINALIZE_PR_TOKEN=1; gh pr comment ...`) утечёт token в session env и может быть использован re-entrant вызовами/цепочками — нарушает one-shot-token инвариант.
- Inline env — atomically scoped к одному вызову, hook проверяет, дальше env исчезает.

**Источник:** U2 PR #185 Step 7.10 — финальная публикация `## ✅ Готов к merge`.

### 3.24 External review iteration cap + convergence detection + binary escalation

**Решение:** Cross-model external review имеет formal convergence detection + soft iteration cap (safety valve, не ceiling). Триггеры завершения:

1. **Convergence detected (preferred path):** PM объявляет APPROVED если выполнены ВСЕ условия:
   - **3 итерации подряд** с 0 новых Critical/High findings,
   - только replays уже-deferred + Low refinements,
   - **AND total external iter ≥ 5** (минимум для adversarial coverage — обеспечивает что cross-model diversity отработала достаточно),
   - **AND каждое выявленное Low/Med/High finding имеет явный triage-статус:** fix now (closed) / defer to Beads (с ID) / reject with rationale. Без полного triage convergence не объявляется (сохраняет инвариант #5: «У незавершённой работы есть адрес в task tracker»).

2. **Soft iteration cap (safety valve, не «спешим закрыть»):**

   Базируется на эмпирической статистике PR в зрелых проектах (big-heroes 26-69 commits для pipeline-class, bonk-race 38-48 commits для doc-heavy, surprise-arena 8-17 для sprint). Средняя 10-15 iter, минимум 5-7 — норма для нетривиальных PR.

   | Scope diff | Soft cap | Когда escalation к оператору |
   |------------|----------|------------------------------|
   | Ordinary docs (`*.md` для product/spec/gdd, не governance) | 7 | После iter 7 если convergence не detected |
   | Mixed (doc + config, без executable, без governance) | 12 | После iter 12 если convergence не detected |
   | Executable / governance / security-sensitive (`.claude/hooks/*`, `.claude/skills/*/SKILL.md`, `.claude/tools/*`, `.claude/settings.json`, `.claude/rules/*.md`, `.agents/*.md`, server/client code) | 20 | После iter 20 если convergence не detected |

   **Важно:** cap — soft, не hard ceiling. Если оператор явно требует продолжения после cap — продолжаем. Cap — только trigger для binary escalation, не для автоматического APPROVE.

3. **При hit cap — binary escalation к оператору, не оценка findings:**
   PM формулирует **бинарный вопрос** в PR comment:
   > «Iter N reached cap. Findings: X новых Med refinements, Y replays. Не блокеры.
   > **(a) Approve с deferred bundle U2-XXX** (рекомендация PM)
   > **(b) Continue iter N+1**, ожидаемо: ещё refinements того же класса, не новые Critical/High»

   Оператор выбирает между «принять текущее качество» vs «полировать дальше», **без необходимости оценивать каждый finding**.

**Обоснование:**

- **Stateless reviewers не сходятся естественно.** GPT-5.5/5.3-Codex каждую iter перечитывают весь diff, не помнят что уже triage'нуто. ADR 3.22 (PM-side dedup) частично решает, но сами модели **продолжают surfacing replays + новые refinement-уровень findings** indefinitely.
- **Документация для doc-only PR быстро уходит в polish-loop** (U2 PR #186 эмпирический baseline: iter 1-3 нашли 3 настоящих Critical, iter 4-6 — только replays + style refinement).
- **Operator не должен evaluating findings.** Правила Zero Trust to Human Tech Skills (ADR §2 + AGENTIC_PIPELINE.md §4.1) явно говорят: human judges по бинарным verdicts, не по содержанию. Cap + binary escalation сохраняет этот принцип.
- **Cap dependent от scope:** doc-only имеет меньше векторов багов чем executable, нужно меньше iter для покрытия. Executable infra оправдывает 7 iter (как U2 PR #185 baseline).

**Альтернативы рассмотрены:**

- **Diff-narrowing (reviewer iter ≥ 2 видит только diff с предыдущей iter-headed):** структурно сильнее, но требует доработки `openai-review.mjs` (`--prev-head <commit>` флаг). Открыта Beads-задача для post-merge enhancement; пока — процедурный cap.
- **Confidence-weighted convergence (require 2 моделей согласиться на APPROVED):** не работает для adversarial design — модели специально находят разное.
- **Отказаться от external review для doc-only:** отвергнуто, iter 2-3 PR #186 нашли 2 реальных Critical regressions от моих же fix-ов.

**Источник:** U2 PR #186 retrospective — 6 iter external review converged практически на iter 3, iter 4-6 = polish loop. Operator явно сигнализировал что polish уже во вред целям пайплайна.

**Связанный документ:** `.claude/skills/external-review/SKILL.md` секция «Convergence detection и iteration cap».

### 3.27 External review backend: Codex CLI ChatGPT subscription (Mode A primary)

> **Numbering note:** ADR 3.25 и 3.26 — нереализованные placeholders из ранних итераций плана Sprint 1A (multi-vendor cascade и token spend optimization). Заменены этим ADR (одно решение покрывает обе цели проще).

**Решение:** External review backend для Mode A — **Codex CLI с ChatGPT subscription quota** (Plus/Pro/Business tier). Вызов из pipeline:

```bash
codex -p review -c sandbox_mode="danger-full-access" review --commit "$HEAD_COMMIT"
```

`openai-review.mjs` (Platform API) остаётся как **Mode A-legacy** для случаев недоступности subscription (network failure, quota exhaust, login expired).

**Обоснование:**

- **Cost:** Mode A (Platform API) ~$20-22/вызов с `reasoning_effort: high`. Один Sprint Final ≈ $40-44/iter × 14 iter = **$560-620** (PR #186 baseline). ChatGPT subscription: $0/вызов в пределах квоты + fixed $25-100/мес. Operator потерял $100 за один вечер на infinite loop через Platform API.
- **Agentic context pull:** Codex CLI имеет встроенные `codex_apps/github_*` MCP tools (`fetch_pr`, `fetch_commit`, `fetch_file`, `list_pr_comments`). Reviewer сам поднимает PR через GitHub Apps API без pre-cooked diff в prompt. Закрывает PR-as-info-bus паттерн (operator clarification 2026-05-05): reviewer читает существующие PR-комментарии и не повторяет уже-разобранные findings.
- **Workspace picker для same-email accounts:** browser OAuth показывает picker (Personal vs Business workspace) → один email = два независимых аккаунта = fallback chain.
- **Profile-based isolation:** `[profiles.review]` в `~/.codex/config.toml` подавляет MCP_DOCKER (`mcp_servers = {}` table-replace) для предсказуемой pipeline invocation. Default config оператора (interactive) не затронут. **Quirk:** `sandbox_mode` в profile игнорируется — всегда передавать `-c sandbox_mode="danger-full-access"`.
- **BE-11 workaround:** `sandbox_mode="danger-full-access"` обходит `CreateProcessWithLogonW failed: 1326` на Windows npm install (sandbox-bin install имел свой workaround через `[windows] sandbox = "elevated"`, npm install не имеет elevation hooks). Acceptable для review — read-only по природе.
- **Account swap:** `.claude/tools/codex-account-switch.ps1` — `Use-CodexAccount {personal-plus|work-business}` копирует backup auth.json в active. Pipeline-сценарий fallback: 429 → swap → retry.

**Подтверждено эмпирически (2026-05-05):**

- ✅ Smoke-test gpt-5.5 high reasoning_effort через Personal Plus (verdict получен ~2 мин)
- ✅ Smoke-test через TOO Overmobile Business (verdict получен ~1 мин, 136 строк output vs 677 на Personal — может быть caching)
- ✅ Profile + sandbox override pattern работает идентично на обоих аккаунтах
- ✅ Account switch script idempotent + recovery from corrupted auth.json

**Альтернативы отвергнуты:**

| Альтернатива | Почему отвергнута |
|-------------|-------------------|
| Multi-vendor cascade (Anthropic + Gemini + DeepSeek) | Anthropic = same-vendor лосс diversity; Gemini 2.5 Pro слаб для review; DeepSeek/Qwen3 — 1-документ context, бесполезны |
| OpenAI Pro top-up second account ($100/мес) | ChatGPT subscription tiers НЕ включают Platform API credits — это разные продукты |
| Self-hosted reviewer (Qwen3 локально) | Operator проверял через расширение — слаб для review, ложные APPROVED |
| Оставить openai-review.mjs primary | Не решает quota cost, не решает PR-комментарии паттерн |
| WSL2 для Codex CLI | Windows native работает (BE-11 mitigated), WSL2 добавил бы UX overhead |

**Источник:** PR #186 retrospective + smoke-tests 2026-05-05 + operator priorities clarification (quality > cost > security; pipeline для solo agentic engineer без enterprise overhead).

**Связанные документы:** `.agents/CODEX_AUTH.md` §8 (subscription path setup), `.claude/tools/codex-account-switch.ps1` (account swap), `docs/archive/2026-05-05-plan-a-polish-codex-subscription.md` (этот спринт, завершён и заархивирован).

**Out of scope:** переписывание `external-review/SKILL.md` под новый backend — отдельный план (Beads U2-rhm).

---

## 4. Альтернативы, которые были рассмотрены и отвергнуты

| Альтернатива | Почему отвергнута |
|-------------|-------------------|
| Один агент «Full-Stack AI» | Нет adversarial проверки, confirmation bias |
| Свободная форма ревью | Агенты пропускают целые категории, нет чеклиста |
| Одинаковый уровень ревью для всех PR | Overhead на документацию, недостаточно внимания к critical |
| `gh pr review` вместо `gh pr comment` | Автор не может ревьюить свой PR (один аккаунт) |
| Все файлы Memory Bank при старте | Расходует контекстное окно на ненужную информацию |
| Soft constraints (мягкие правила) | Агенты пропускают мягкие правила без последствий |
| Temp-файлы за пределами воркспейса | VS Code не авто-одобряет запись вне воркспейса |

---

## 5. Известные ограничения и риски

### Текущие ограничения

1. **Один аккаунт для всех агентов.** Нет audit trail — непонятно, кто из агентов сделал коммит. Решение: подпись `— Role (Model)` в конце каждого отчёта.
2. **CI без required checks.** CI уже работает (`.github/workflows/ci.yml`: build + test на push/PR), но нет required status checks и branch protection. При merge без агента хуки Claude Code не срабатывают, а CI не блокирует merge.
3. **Нет автоматического Copilot auto-review на все коммиты.** Copilot ревьюит только при создании PR или re-request.
4. **Beads CLI не стабилен.** Некоторые команды (`bd sync`) не существуют, документация отстаёт от реализации.

### Риски

| Риск | Вероятность | Влияние | Митигация |
|------|------------|---------|-----------|
| Агент игнорирует hard gate | Средняя | Высокое | Enforcement через hooks + deny rules + `/finalize-pr` |
| Memory Bank устаревает | Высокая | Среднее | PM обязан обновлять; warning при финализации |
| Кросс-модельное ревью даёт конфликтующие вердикты | Средняя | Низкое | PM арбитрирует, CRITICAL приоритет |
| Оператор мержит без Sprint Final | Низкая | Высокое | `/finalize-pr` проверяет наличие external review |
| Drift между документами | Высокая | Среднее | `/pipeline-audit` после каждых 3–5 спринтов |
| PM искажает findings при консолидации | Средняя | Среднее | Raw output в collapsible блоке, инвариант 6 |
| Defer-abuse (все замечания → defer) | Средняя | Среднее | Warning при >50% defer в `/finalize-pr` |
| `/finalize-pr` сломался | Низкая | Высокое | Emergency override `--force` (только оператор) |

---

## 6. Связанные документы

| Документ | Назначение |
|----------|-----------|
| `.agents/PIPELINE.md` | Операционная карта пайплайна (ЧТО) |
| `.agents/AGENTIC_PIPELINE.md` | Универсальная методология (ПОЧЕМУ) |
| `.agents/AGENT_ROLES.md` | Роли, обязанности, промпты (КАК) |
| `.agents/PM_ROLE.md` | Детальный workflow PM |
| `.agents/HOW_TO_USE.md` | Шпаргалка оператора |
| `.agents/REFERENCES.md` | Источники и референсы |
| `.agents/INSTALL.md` | Установка пайплайна в новый проект (Bootstrap PR pattern) |
| `.claude/agents/*.md` | Инструкции нативных агентов |
| `.claude/skills/sprint-pr-cycle/` | Оркестрация ревью-цикла |
| `.claude/skills/external-review/` | Кросс-модельное ревью |
| `.claude/skills/finalize-pr/` | Hard gate перед merge |
| `.claude/skills/verify/` | Единый build/test gate |
| `.claude/skills/pipeline-audit/` | Проверка консистентности |
| `.claude/settings.json` | Hooks, deny-rules, permissions |
| `.memory-bank/` | Персистентный контекст проекта |

---

## 7. Процедура изменения пайплайна

1. Создать issue в Beads с описанием проблемы
2. Создать ветку `review/*` или `fix/pipeline-*`
3. Внести изменения во **все** связанные файлы (см. секцию 6)
4. Запустить Pipeline Audit — полный grep на противоречия
5. PR → ревью (Standard) → merge
6. Обновить этот ADR (добавить решение + обоснование)

> Исторический урок из PR #3: изменение в одном файле (например, «3→4 аспекта» в reviewer.md) без обновления всех связанных файлов (PM_ROLE.md, PIPELINE.md, AGENT_ROLES.md) создаёт drift. Pipeline Audit потребовал 11 раундов, чтобы вычистить все несоответствия.
