---
title: "OverGate 4.0 Delivery First — обновление кандидата после Windows-починки"
status: draft
version: "0.2"
date: 2026-10-03
tags: [overgate, delivery-first, release-candidate, migration, windows]
beads: og-uw7
related:
  - docs/plans/2026-10-01-delivery-first-rc.md
  - docs/baselines/2026-10-01-delivery-first-source-inventory.md
---

# OverGate v4.0.0-rc.1 — план обновления кандидата

**Цель:** довести текущую линию OverGate до кандидата-релиза на базе работающего сегодня пайплайна U2, с проверенной установкой и работой Bash на Windows и macOS.

**Подход:** продолжаем [Draft PR #7](https://github.com/komleff/overgate/pull/7), ветку `codex/delivery-first-rc` и задачу `og-uw7`. Сохраняем готовый generic core и правки установщика; обновляем только зависимый от свежего U2 пакет и доказательства его приёмки. Этот план заменяет устаревшие source/platform/status части [плана 2026-10-01](2026-10-01-delivery-first-rc.md); остальные принятые решения A–C сохраняются.

**Стек:** Markdown policy/skills, Bash hooks, Python installer/checker/tests, Node.js Beads reader, GitHub Actions; Claude Code и Codex adapters.

**Источник требований:** решения оператора в этой задаче; U2 `.agents/PIPELINE_ADR.md §3.29–3.32`, роли и реестры на frozen SHA ниже; принятый generic extraction из плана 2026-10-01. Спецификация Windows-поведения — [U2 #829](https://github.com/komleff/u2/pull/829), включая ратифицированное изменение аварийного режима.

## Исходное состояние и границы

| Объект | Зафиксированное состояние |
|---|---|
| Новый U2 source | `c450fa7b0d90fecf970f9931011255ea836da258`, текущий `origin/main`, merge выпуска 0.27.1 #830 |
| Исправление Windows в source | #829, merge `13a66f3842db00f6ff14077812f37d933ef490c1`; native Windows 22/22 и [живая проверка после pull](https://github.com/komleff/u2/pull/829#issuecomment-5945813363) |
| Dogfood | Оператор 2026-10-03 подтвердил работу настроенного пайплайна на Windows и лёгкое прохождение 0.27.1. Это опыт U2, а не тест установленного OverGate |
| OverGate base/main | `466ad2020b8c46e6c14b4bbe67b5335017726542` |
| Remote Draft #7 | `eb450b21d436fc1e7ec4e3b79fa32071b53499b2`, source ещё `fb8ebfa5`, до Windows-починки |
| Локальный кандидат | `bdc92fac13ad4a4c28b7bed9284ab9b50d3be256`: две installer QA-F1/F2 исправлены Developer; affected QA ещё не выполнена, commit не опубликован |
| Stable | `v3.9.0` **Dreadnought**, Latest, на `466ad202…`; `v3.9.0-beta.1` сохранён |
| Main protection | PR required, enforce admins, force push/delete запрещены; required `verify-reference` ещё не включён |
| Проверяющие | Ранее Plan Review 1/6 и initial QA 2/6; scoped Code Review ещё не запускался |

**Режим:** CRITICAL — pipeline governance: работа Bash, защита репозитория и безопасное обновление установленного проекта. Budget остаётся у той же линии: 6 независимых verifier launches, уже использовано 2. Планируем affected Plan Review 3/6, affected QA 4/6 и один scoped Code Review 5/6; 6/6 — резерв адресной проверки blocker fix. Повторные независимые запуски считаются независимо от переиспользования agent session. Deterministic tests и сбор evidence не расходуют этот budget.

**Инварианты:** merge только оператором; реализация изменённого плана только после `PLAN_READY`; публикация PR/evidence и финализация уже разрешены задачей. Проверка governance проводится по frozen U2 и контракту, а не по изменяемому OverGate finalizer. Новый релиз — `v4.0.0-rc.1`, `prerelease=true`, `make_latest=false`; stable 4.0 — отдельное решение.

**Scope:** шесть delivery owners PM/SV/PL/DEV/QA/RV, пять generic skills, актуальные Claude/Codex adapters, enforcement/dependency closure, установщик fresh/upgrade/rollback, документы/credits/provenance и RC publication.

**Границы:** игровой Almanac и U2 game/build/deploy/CDP-код остаются в U2. Product authority задаёт устанавливаемый проект, fallback — оператор. Memory Bank и Beads сохраняют контекст и задачи проекта. Новый перенос Codex на Bash-диспетчер не входит в эту линию: source #829 его не выполнял. Старый stable и его теги не изменяются.

## Review Focus / named risks

- **R1 — Windows quoting:** запись хука снова меняется при передаче из нативного процесса. Нативный тест должен запускать точные installed settings через настоящий Git Bash, включая канарейку прежнего сбоя.
- **R2 — неверный checkout или cwd:** работают хуки соседнего worktree либо возврат из чужого каталога невозможен. Проверить два checkout, stale `CLAUDE_PROJECT_DIR`, выход наружу и исполнимость показанного восстановления.
- **R3 — upgrade и горячая смена settings:** старые managed записи остаются рядом с новой, пользовательские настройки теряются либо запись начинает ссылаться на ещё не установленный dispatcher. Проверить порядок apply/rollback, отказ до записи и override preservation.
- **R4 — зелёный reference скрывает сломанный payload:** helper есть в source, но отсутствует в distribution. Checker и installer должны проверять staged/installed bytes; omitted entry даёт отказ до первой записи.
- **R5 — ложная приёмка или возврат бюрократии:** U2 evidence объявляется OverGate PASS, старые review loops становятся active либо RC подменяет Latest. Проверить точный контракт, active owners, platform matrix, source attribution и release identities.

## Задача 1. Заморозить новый источник и обновить контракт того же PR

**Файлы:** этот план; `docs/baselines/2026-10-01-delivery-first-source-inventory.md`; `docs/baselines/2026-10-01-delivery-first-provenance.json`; `.memory-bank/{activeContext,progress}.md`; body/comments PR #7. Старый frozen plan/evidence остаются историей.

**Вход:** новый U2 source, существующий manifest из 109 entries и исходные AC-01–09. **Выход:** обновлённый file-level inventory и один контракт кандидата, согласованный с этим планом.

- [ ] Зафиксировать source SHA и сравнить с `fb8ebfa5` только pipeline surface. Для каждого перенесённого файла записать source path/blob, target и адаптацию; новые generic integration files отметить отдельно. Проверить пять перенесённых source skills и исключённый Almanac.
- [ ] В existing transferred inventory изменились `INSTALL.md`, `PIPELINE_ADR.md`, `settings.json` и три test consumers: `merge-gate-parse-budget`, `publish-pr-comment`, `repository-mutation-guard`. Добавить новый dispatcher/native test/test helpers; остальные изменения U2 классифицировать по применимости, без копирования каталогов целиком. Изменённый `cdp-touch.test.py` — продукт U2, исключить.
- [ ] Опубликовать plan/VC в #7 и отметить supersession старого source/platform contract. Initial QA-F1/F2 FAIL сохранить как evidence; commit `bdc92fac…` обозначить как исправление, ожидающее affected QA.
- [ ] Получить один affected Plan Review по R1–R5 и AC-01/06/07/08/09. Старое `PLAN_READY` на `fb8ebfa5` не разрешает новую Windows-поверхность автоматически.

**Проверка:** source/base/candidate/contract не противоречат друг другу; reviewer выдаёт `PLAN_READY` либо адресные blockers. Изменение source позднее требует повторной классификации delta и affected check, а не тихого обновления SHA.

## Задача 2. Перенести Windows-починку и согласовать distribution

**Файлы:** `.claude/settings.json`, `.claude/hooks/pre-bash.sh` (новый), `scripts/tests/pre-bash-dispatch.test.py` (новый), `scripts/tests/lib/{claude_hooks.py,seed-claude-hooks.sh}` (новые); применимые test consumers; `.agents/distribution-manifest.json`; `scripts/{check-reference.py,install-overgate.py,verify-reference.sh}`; `scripts/tests/{reference-closure.test.py,install-distribution.test.py}`; ADR/INSTALL/pipeline-audit.

**Вход:** source #829 и обновлённый inventory. **Выход:** generic пакет с тем же утверждённым поведением и полным payload; существующие override/backup/approval interfaces installer сохраняются.

- [ ] Перенести одну managed `PreToolUse(Bash)` запись без обратных слэшей и с timeout 600 с. Её семантику сохранить; она вызывает dispatcher в cwd. Dispatcher определяет свой root по расположению и вызывает три действующие проверки последовательно с сохранением бюджета времени. Старые ROOT wrappers и `check-bash-cwd` в active payload отсутствуют.
- [ ] Сохранить принятый аварийный режим: вне root проходит только `cd <абсолютный путь к checkout с dispatcher>` одной командой; остальное блокируется с фактами и восстановлением. Не возвращать отвергнутые allowlists чтения. Ограничения формы пути/кавычек из source явно описать; пути с пробелами/не-ASCII проверить как отдельные cases и не обещать поддержку восстановления без evidence.
- [ ] До изменения checker/installer добавить negative cases: удалён dispatcher/его manifest entry; две managed записи; обратный слэш в command; смешение новых и известных старых managed hooks; изменённый пользовательский managed hook. Все случаи обязаны дать FAIL или адресный conflict до unsafe install.
- [ ] `scripts/check-reference.py:closure(root)` проверяет Claude wiring через dispatcher и наличие всех трёх guards в closure; Codex проверяется по своему действующему adapter contract. Не требовать inline имён трёх handlers в единственной Claude command, как делает старый checker.
- [ ] `scripts/install-overgate.py:merge_settings(existing, new, legacy)` обновить только для новых managed hook identities. Known old version заменяется, custom hook сохраняется либо вызывает conflict; custom managed variant не удаляется по substring. Fresh, v3.9 и previous-RC fixtures не оставляют дублирующие managed wrappers.
- [ ] Обеспечить проверяемый порядок: helpers/guards и dispatcher доступны до переключения settings; при rollback settings восстанавливаются до удаления нового dispatcher. Подтвердить interrupted/error path existing backup/restore механизмом; не объявлять multi-file update атомарным. План применения содержит этот порядок до approval.
- [ ] Добавить dispatcher в distribution и staged closure, native test — в `verify-reference`. Перенести применимые обновлённые consumers/helpers, сохранив generic test runner; целиком U2 `run-all.sh` не переносить.
- [ ] Повторно проверить regression QA-F1/F2: обновляется managed `large-payloads.md`; отсутствующая обязательная manifest entry обнаруживается ещё до backup/target writes. Правки `bdc92fac…` сохранить.

**Проверки:** `python3 scripts/check-reference.py`; `python3 scripts/tests/reference-closure.test.py`; `python3 scripts/tests/install-distribution.test.py`; `python3 scripts/tests/pre-bash-dispatch.test.py`; затем `bash scripts/verify-reference.sh`. На Windows native unit запускать из PowerShell штатным `py -3 scripts/tests/pre-bash-dispatch.test.py`, не через Linux/WSL. Test launcher выбирает реальный Git Bash, а не `System32/bash.exe`.

## Задача 3. Проверить установленный пакет и довести документы

**Файлы:** `.agents/{PIPELINE_ADR,PIPELINE,INSTALL,HOW_TO_INSTALL,HOW_TO_USE,REFERENCES}.md`, `AGENTS.md`, `README.md`, `CHANGELOG.md`, installer templates, `.github/workflows/ci.yml`, reports в PR #7; regression cases предыдущей задачи.

**Вход:** один frozen candidate commit после реализации. **Выход:** acceptance matrix установленного OverGate, короткий актуальный вход для пользователя и evidence, связанное с tested bytes.

- [ ] На macOS и isolated Linux выполнить полный `bash scripts/verify-reference.sh` на final candidate; не выдавать старые зелёные logs за проверку новой версии.
- [ ] На native Windows Git Bash выполнить dispatcher unit и установочные fresh/v3.9-upgrade/rollback fixtures. Зафиксировать OS, Claude/Git Bash/Python versions, source/installed SHA, команды, exit codes и logs. Локальный путь и prefix U2 не должны быть dependency.
- [ ] В disposable consumer на Windows и macOS проверить actual installed hooks в живой и новой Claude Code сессии: `git log` из root; уход наружу → диагностический блок следующей команды → показанный `cd` → снова чтение; commit с red tests и merge/main mutation блокируются до исполнения. Все dangerous probes используют disposable repo/несуществующий PR; real merge/изменение защищённой main не выполняется.
- [ ] Для двух checkout проверить, что исполняются guards рабочего checkout при stale `CLAUDE_PROJECT_DIR`; для unsupported recovery path показать честный предел и проверенный способ вновь открыть сессию в root. U2 post-pull smoke — reference, installed smoke — отдельный результат.
- [ ] Codex: на доступном runtime проверить actual activation после штатного одобрения `/hooks`; adapter не объявлять проверенным на Windows по Claude evidence. Недоступный case — `NOT RUN`/`DECLARED_LIMIT` в matrix и release notes. Известный Important/Critical риск требует решения оператора и останавливает RC до этого решения.
- [ ] README дать короткий путь «поручи агенту установить OverGate», затем конкретные prerequisites и ссылку на единый `plan → apply → rollback`. Installer требует clean Git checkout с exact SHA: это явно указать рядом с получением release source, чтобы распакованный ZIP без `.git` не выглядел готовым trusted source. Не разрабатывать второй установщик/архивный обход.
- [ ] HOW_TO_USE согласовать с roles/skills и фактическим аварийным режимом. В active docs убрать stale mandatory extra passes и claims непроверенных платформ; history оставить обозначенной историей.
- [ ] Credits обновить из текущего U2: Matt Pocock skills, Superpowers, Cline Memory Bank, Beads; отличить inspiration от перенесённых материалов, сохранить MIT/авторство и frozen provenance. Анонс — короткая заметка с хуком «Ваш проект должен жить дольше одного чата с ИИ», без истории коллег и длинного каталога инструментов.
- [ ] Провести affected QA: старые QA-F1/F2 и новая Windows/install surface плюс необходимые regression groups. Затем один scoped Code Review всего changed candidate по R1–R5; unchanged source не подвергать новому полному аудиту U2. Evidence публиковать с фактическими role/model и content binding, удалённые файлы обозначать `DELETED`.

**Проверка:** ни одного незакрытого acceptance blocker; обязательные Windows/macOS Claude/install cases PASS. Platform limits и accepted risks отдельны от PASS. Dogfood 0.27.1 уже достаточен как положительный опыт применения; новая серия 5–10 игровых задач не является release gate.

## Verification Contract (обновляет AC-01–09 того же PR)

| AC | Проверяемый результат |
|---|---|
| AC-01 | Source `c450fa7b…`, delta classification и file-level provenance полного transferred package; original integration отдельно, шесть U2 skills классифицированы |
| AC-02 | `v3.9.0` Dreadnought и beta refs неизменны; Dreadnought остаётся stable/Latest |
| AC-03 | Один Delivery First lifecycle/budget/findings/finalize contract у всех active owners/adapters; ordinary reports не требуют finalize |
| AC-04 | Пять generic skills, шесть delivery owners; structural negative cases FAIL, project authority/operator fallback; U2 game/Almanac отсутствуют |
| AC-05 | Existing activation positive/non-trigger scenarios PASS, без навязывания missing WHAT/нового spec/лишнего handoff |
| AC-06 | Одна managed Claude Bash запись без backslashes, source dispatcher semantics и timing; native Windows unit + installed Windows/macOS live smoke PASS; guards/reads/recovery/cross-checkout подтверждены; Codex matrix отдельна |
| AC-07 | Fresh/v3.9/previous-RC upgrade и rollback сохраняют overrides/bytes; custom managed conflict и omitted dependency — отказ до unsafe write; hot reload ordering и QA-F1/F2 regression PASS |
| AC-08 | Updated PLAN_READY, affected independent QA, один scoped Code Review, current full reference checks/CI, zero unresolved blockers, prior trusted bootstrap и final content binding |
| AC-09 | До merge required `verify-reference` и main protection проверены; merge оператором. После merge exact merged tag `v4.0.0-rc.1`, prerelease/not Latest, migration/platform/credits/rollback notes и проверка release identities |

## Задача 4. Финализация, операторский merge и публикация RC

**Файлы:** PR evidence/body, release notes, `.memory-bank/{activeContext,progress}.md`, Beads `og-uw7`/`U2-0jfah`; tag/release metadata после merge.

- [ ] Проверить успешный CI `verify-reference` на exact final candidate. Включить этот required check в уже настроенную main protection по ранее данному разрешению; подтвердить GET, admin enforcement и запрет force/delete. Не требовать второй GitHub-аккаунт для approval.
- [ ] Сверить contract, tested/reviewed blobs, source provenance, platform evidence и open risks. Выполнить один trusted `/finalize-pr`, дать оператору прямую ссылку на итоговый паспорт #7. Base-only движение требует fresh deterministic checks/passport binding, не автоматического нового LLM review.
- [ ] После сообщения оператора проверить фактический merge SHA. Создать `v4.0.0-rc.1` на exact merged candidate; публиковать GitHub prerelease с `make_latest=false`. Перед записью убедиться, что RC tag ещё отсутствует; существующий tag не передвигать. При совпадении уже созданного release — проверить и продолжить без дублирования; при расхождении — остановиться.
- [ ] Проверить удалённые tag/release identities, prerelease flag и сохранённый Dreadnought Latest. Закрыть `og-uw7` только после выполнения release AC; выгрузить Beads snapshot. U2 preparation отметить завершённой со ссылками на release/evidence.

**Откат:** до merge — исправить или отозвать draft; после merge — отдельный revert PR, merge оператором. Установленный проект — installer backup/rollback либо revert upgrade PR с адресным восстановлением overrides; Beads и Memory Bank не откатывать вслепую. Не передвигать опубликованные теги; дефектный RC обозначить в release notes и выпустить исправление как `rc.2`.

## Статус этого плана

- [x] Проверены актуальные U2/OverGate remote состояния, Windows-fix evidence, старый QA FAIL, локальные fixes и stable/protection identities.
- [x] План обновления составлен; реализации Windows-переноса в этом документе не утверждается.
- [ ] Affected independent Plan Review → PLAN_READY.
- [ ] Implementation / current checks / installed platform evidence / QA / scoped Review.
- [ ] Finalize → операторский merge → `v4.0.0-rc.1` publication.

— PM, GPT-6 (Codex).
