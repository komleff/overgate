---
title: "OverGate RC — самостоятельный продукт: уточнения переноса"
status: draft
version: "0.3"
date: 2026-10-03
tags: [overgate, delivery-first, portability, release-candidate]
beads: og-uw7
related:
  - docs/plans/2026-10-03-delivery-first-rc-refresh.md
---

# Уточнение плана: OverGate как самостоятельный продукт

**Цель оператора:** перенести текущий пайплайн U2 в самостоятельный OverGate, устанавливаемый в чужие проекты с агентной разработкой. Исходный U2 — provenance и dogfood; работа установленного продукта не зависит от U2 checkout, команды тестов, task prefix или личных путей оператора.

Основа — [план v0.2](2026-10-03-delivery-first-rc-refresh.md), source `c450fa7b0d90fecf970f9931011255ea836da258`. [Дополнительный PLAN_REVIEW](https://github.com/komleff/overgate/pull/7#issuecomment-5959271663), Claude Opus 5.5: PLAN_READY, BLOCKER=0, ADVISORY=2. Уточнения ниже конкретизируют generic adaptation и AC-06/07; runtime implementation ещё не начата.

## 1. Бюджет и границы evidence

Фактически использовано **4/6**: initial Plan Review 1, initial QA 2, refresh Plan Review 3, дополнительный независимый Plan Review 4. Следующие слоты — affected QA **5/6** и один scoped Code Review **6/6**. Свободного reserve нет. Если потребуется обязательная дополнительная независимая проверка, PM остановит финализацию, опубликует конкретный незакрытый FAIL/риск и запросит дополнительный budget; проверки не исключаются и история счёта не меняется задним числом.

Это дополнение — PM-разбор полученного feedback, а не новая независимая verifier launch. Старые reports остаются привязанными к исходным плану/контракту/bytes; PLAN_READY не является доказательством реализованных исправлений или платформенного PASS.

## 2. Generic adaptation в задаче 2

**Файлы:** существующий `docs/baselines/2026-10-01-delivery-first-source-inventory.md` (rename map), provenance JSON, runtime helpers/dispatcher, `scripts/check-reference.py`, `scripts/tests/reference-closure.test.py`, native dispatcher test и installer fixtures. Нового policy owner или второго установщика не создавать.

- [ ] Применить existing rename map только там, где generic adaptation необходима для сохранения исходного поведения. Любое переименование связывает producer, consumer и dependent fixtures; слепая глобальная замена запрещена.
- [ ] Обязательная пара нового переноса: `U2_COMMIT_GATE_TEST_MAX_SECONDS` → `OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS` в dispatcher и его tests, поскольку существующий OverGate gate уже читает второе имя. Existing classify override `OVERGATE_COMMIT_GATE_TEST_MAX_CLASSIFY_SECONDS` сохраняется. Source wiring и accepted recovery semantics не расширяются.
- [ ] В installed dependency audit проверить отсутствие зависимости от личного U2 checkout, task database/prefix и команды тестов U2. Attribution/frozen source references разрешены. Внутренние имена `U2_WITH_TIMEOUT_TEST_STARTUP_PAUSE_SECONDS`, `$U2_UNKNOWN_SUBCOMMAND` и temporary prefix `u2-with-timeout.` сами по себе не требуют U2; их согласованную косметическую нормализацию и строгую автоматическую проверку префиксов вынести в следующий патч вместе с portability cleanup.
- [ ] Проверить сужение бюджета с **настоящим installed** `check-tests-before-commit.sh`, который читает `OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS`. Заглушка, читающая то же ошибочное имя, что экспортирует dispatcher, не доказывает интеграцию. Проверка имени producer/consumer и поведенческий case должны краснеть при mismatch.
- [ ] Native commit-verdict fixture подменяет **`.agents/project/verify.sh`** в disposable consumer, а не `npm`: red/green verifier даёт dispatcher code 2/0. Helper для limits test может сохраняться, но он не заменяет real-gate integration case.
- [ ] В reference ровно одна managed Bash entry; в installed settings допускаются сохранённые custom Bash hooks. Проверка считает managed entries, доказывает отсутствие known-old managed wrappers и сохранность custom hooks; не требует одну Bash entry во всём consumer JSON.

`sync-site-gdd` не входит в distribution manifest; его наличие в старом repository tree не означает включения в core. Его статус legacy/example должен быть виден, без active install instructions, требующих U2.

## 3. Дополнение installed matrix и migration notes

- [ ] На Windows/macOS проверить **запуск новой сессии в подкаталоге собственного checkout**, в том числе каталоге пакета монорепо: диагностический блок → показанный возврат в root → успешное чтение. Это отдельный case от выхода в чужой каталог.
- [ ] В HOW_TO_USE и migration notes явно указать изменение относительно v3.9: для полного dispatcher сессия работает из root; подкаталог считается режимом восстановления. Не утверждать, что старые hooks всегда корректно работали из subdirectory: их конкретные команды имели cwd dependencies.
- [ ] Для generic consumer проверить real project authority, project verifier и custom runtime hooks; package не использует U2 task database/prefix.

## 4. Принятое решение: rc.1 как совместимая исходная версия

**ACCEPTED_OPERATOR_DECISION, 2026-10-03.** Оператор: «текущий rc.1 по возможности копируем с u2, чтобы иметь точку обратной совместимости. а следующим минорным патчем уже внесем исправление в overgate».

Для **rc.1 принят вариант А**: сохраняем source #829 recovery semantics, ровно одну managed Bash запись и dispatcher. Вне root проходит только одна unquoted absolute `cd` команда с путём из латиницы/цифр/`_ : / . -`. Пробелы, кириллица и скобки не входят в форму восстановления. Предел видимо указан в README/INSTALL/HOW_TO_USE и release notes; rc.1 не объявляется поддерживающим восстановление для любых project paths.

Тесты rc.1 подтверждают отказ для unsupported recovery path и рабочий документированный способ вновь открыть сессию в root. Windows/macOS smoke остаётся обязательным в пределах явно заявленной поддержки. История U2 и планы source при этом не меняются.

**Следующий патч OverGate — Beads `og-7sr`:** безопасный возврат для пробелов/кириллицы/скобок — один literal absolute target path, никаких дополнительных команд, expansion или обхода guards; displayed recovery command сама проходит и возвращает в нужный checkout. Native Windows/macOS positive cases и injection negatives обязательны. Parser/wiring design и его Plan Review — отдельная линия после выпуска rc.1; это исправление не входит в rc.1. В той же следующей линии нормализуются оставшиеся внутренние U2-префиксы и добавляется адресная автоматическая portability-проверка с разрешённой provenance. Номер следующего патча пока не назначается.

— PM, GPT-6 (Codex).
