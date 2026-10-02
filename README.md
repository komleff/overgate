# OverGate

**Ваш проект должен жить дольше одного чата с ИИ.**

Переносимый AI-пайплайн разработки для оператора, который задаёт цель и принимает результат.
Delivery First связывает принятую спецификацию, реализацию, независимую QA и один scoped Code Review.

**Текущий candidate: v4.0.0-rc.1.** Stable Dreadnought сохраняет прежний snapshot `466ad20`;
RC выбирается отдельно и не заменяет Latest. Здесь живёт generic reference из
[U2](https://github.com/komleff/u2), без его product/game data.

```text
Accepted WHAT → plan + Verification Contract → PLAN_READY
→ implementation/tests → QA → one scoped Code Review
→ affected blocker fix → landing + fresh checks → one finalize → operator merge
```

FAST подходит для безопасных docs/content/parameters; PRODUCT — обычная feature;
CRITICAL — явно названный высокий риск. Бюджет independent verifier launches: **2 / 5 / 6**.
External review доступен по named risk или прямому запросу. Advisory не создаёт автоматическую
правку, а движение base при доказанной эквивалентности содержания не требует нового LLM review.

| Слой | Владелец |
|---|---|
| Doctrine/lifecycle | [PIPELINE_ADR §3.28–3.32](.agents/PIPELINE_ADR.md), [краткая карта](.agents/PIPELINE.md) |
| Шесть delivery roles | [PM, SV, PL, DEV, QA, RV](.agents/AGENT_ROLES.md) |
| Пять core skills | [canon-router, product-gap, product-handoff, diagnose, handoff](.agents/SKILLS.md) |
| Project authority | AGENTS.md установленного проекта; fallback — оператор |
| Runtime adapters | `.claude/`, `.codex/hooks.json` |
| Distribution | [explicit inventory](.agents/distribution-manifest.json), [установка и rollback](.agents/INSTALL.md) |

Поручите агенту: «Установи OverGate в этот проект по `.agents/INSTALL.md`, сохрани
мою product authority, команды тестов и custom hooks; подготовь target Draft PR».
Source нужен как чистый **Git checkout**, полученный через `git clone` с выбранным RC tag
и exact commit SHA; распакованный release ZIP без `.git` installer не принимает.
Нужны Git, Bash (на Windows — Git Bash), Python 3; gh для PR, Node.js для Beads reader,
jq для finalize. `bd` нужен при использовании Beads.

Начните с [инструкции работы](.agents/HOW_TO_USE.md) или [установки](.agents/INSTALL.md).
Установщик сначала создаёт plan/inventory на frozen source SHA. Target Draft PR, Verification
Contract и независимый PLAN_READY предшествуют копированию. Project owner, tests, context и
runtime overrides сохраняются; conflict останавливает upgrade. Backup позволяет вернуть исходные
managed bytes. Fresh project tests нужно заполнить — шаблон до этого намеренно не проходит.

Для reference: Git, Bash, Python 3, Node.js и jq; `bash scripts/verify-reference.sh` выполняет
структурные, parser/guard/publisher, activation, fresh/upgrade/rollback и Beads fixtures.
Для PR publication используется gh; для local Beads — bd по правилам проекта. External tooling
не настраивает аккаунты автоматически и не требует конкретного модельного профиля.

Local guards проверяют shell-команды; они не защищают remote connectors. Защита main включается
на GitHub, а merge выполняет оператор. Static adapter fixtures не доказывают activation в любом
runtime. Windows и live Claude/Codex activation требуют отдельного smoke; accepted-risk validation
в finalize остаётся ручной. Точные платформенные результаты и declared limits публикуются в candidate PR.

Лицензия OverGate — [MIT](LICENSE), copyright Dmitriy Komlev. [Credits и provenance](.agents/REFERENCES.md)
отделяют источники идей от перенесённых файлов и не распространяют MIT автоматически на весь U2.

Для полного Claude Bash dispatcher запускайте сессию из корня checkout. Новая сессия
в подкаталоге, включая пакет монорепо, работает в режиме восстановления: остальные Bash
команды блокируются до возврата в root. В rc.1 допускается только одна unquoted команда
`cd <absolute-checkout-path>`; допустимые символы пути — латиница, цифры, `_ : / . -`.
Пробелы, кириллица, скобки и кавычки в этой форме не поддерживаются. Для такого пути
завершите сессию и откройте новую непосредственно в корне checkout через интерфейс
runtime/терминала. Root-запуск не зависит от `CLAUDE_PROJECT_DIR`, даже если переменная
указывает на соседний checkout. Исправление recovery paths и внутренних U2-префиксов
отложено в `og-7sr`; rc.1 сохраняет исходную семантику U2 #829.
