---
title: "OverGate v4.0.0-rc.1 — Delivery First implementation plan"
status: draft
version: "0.1"
date: 2026-10-01
tags: [delivery-first, release-candidate, implementation, migration]
beads: og-uw7
---

# OverGate v4.0.0-rc.1 — Delivery First

**Goal:** перенести проверенный в U2 Delivery First в универсальный OverGate reference, сохранив старый stable и проверяемые fresh install, upgrade и rollback.

**Source:** U2 `fb8ebfa5133c13726bd7960a1a075ab7a7089191`; **base:** OverGate `466ad2020b8c46e6c14b4bbe67b5335017726542`. [Intake](../baselines/2026-10-01-delivery-first-rc-intake.md) содержит фактические PR, релизы, старые теги и baseline checks; [source inventory](../baselines/2026-10-01-delivery-first-source-inventory.md) — карту source→target и blob identities. Implementation-ready исходная процедура — U2 ADR §3.29–3.31 и принятые Foundation/Activation. Этот план конкретизирует generic extraction; не проектирует другой lifecycle.

**Режим:** CRITICAL, named risks R1–R7 ниже. Ветка и Draft PR содержат план до implementation. Начало implementation — только после независимого `PLAN_READY`. Один основной Developer, одна QA-сессия и один scoped Code Review; исправления возвращаются тем же проверяющим для affected recheck. Budget 6 independent verifier launches; planning/research и deterministic tests не считаются.

## 1. Scope и решения

1. Generic core содержит пять процедур: `canon-router`, `product-gap`, `product-handoff`, `diagnose`, `handoff`. Registry `.agents/SKILLS.md` владеет membership; skill owner — процедурой; role owner — условием вызова. Смысл source-контрактов сохраняется.
2. `u2-almanac-authoring` остаётся в U2. Нет нового generic structured-authoring, Almanac schema, gameplay или game assets. Все шесть исходных skills учитываются в provenance, включая исключённый.
3. Шесть обязательных delivery owners: PM, SV, PL, DEV, QA, RV. Product authority задаётся проектом в `AGENTS.md`; при отсутствии адресата решение возвращается оператору. Обязательная GD/PD роль не создаётся. PM/Planner/Developer не получают право выбирать отсутствующий WHAT.
4. `.agents/` — общая policy; `.claude/` и `.codex/` — adapters. Claude `tester` остаётся compatibility pointer к QA. Старые Architect/project-manager wrappers либо thin pointers/optional capability без новых полномочий, либо явно historical; они не возвращают обязательный старый маршрут.
5. FAST/PRODUCT/CRITICAL, budget 2/5/6, Plan Review → implementation → QA → один scoped Review → affected fix → single finalize → operator merge. External review только по named risk/прямому запросу; advisory не исправляется автоматически. Base-only movement не запускает новое LLM review при доказанном content equivalence.
6. Установленная копия получает source SHA и install inventory. Project owner, команды тестов, project context и runtime overrides не затираются. В reference `/verify` исполняет реальные reference tests; install-time шаблон проверок проекта хранится отдельно и требует заполнения.
7. Исходная задача оператора разрешает публикацию PR, evidence и финализацию. Отдельные permission prompts для этих действий не нужны. Merge выполняет оператор; неизученные продуктовые решения и известные Important/Critical риски не принимаются за него.

**OUT:** перенос U2 доменных документов/данных; переписывание исторических ADR; новое review framework; обязательный generic designer; новый API/model/account setup; изменения PR #6 и личного checkout; движение существующих тегов; исправление payload уже опубликованного Dreadnought.

## 2. Доставка в одном candidate PR

Срезы ниже — reviewable commits одного кандидата, не отдельные review cycles. Промежуточные несовместимые срезы не публикуются как релиз.

### A. Doctrine, role owners и Skill Layer

**Файлы:** `.agents/{PIPELINE_ADR,PIPELINE,AGENT_ROLES,PM_ROLE,SV_ROLE,PL_ROLE,DEV_ROLE,QA_ROLE,RV_ROLE,SKILLS,HOW_TO_USE,REFERENCES}.md`, пять `.agents/skills/*/SKILL.md`; `AGENTS.md`, `.agents/templates/AGENTS.template.md`; `.claude/agents/{developer,planner,reviewer,tester}.md`; active `.claude/skills/{project-manager,architect}/` pointers; historical `.agents/AGENTIC_PIPELINE.md` banner.

- [ ] Добавить новую OverGate ADR supersession старых mandatory four-aspect/external/dual-finalize правил; сохранить историю и ссылку на frozen U2 source.
- [ ] Перенести роли и пять contracts по inventory с единой rename map. Удалить U2-only адреса authority и domain examples из active instructions; provenance links не считаются operational leaks.
- [ ] До реализации structural checker добавить отрицательные fixtures: missing owner, dangling registry, orphan/nested skill, duplicate membership, unresolved role pointer. Реализовать `scripts/check-reference.py` только для OverGate; не копировать U2 Unity/Caddy/legacy-web checks.
- [ ] Добавить static positive/non-trigger fixtures в `scripts/tests/activation-routing.test.sh`: complete source PASS_THROUGH; missing WHAT PRODUCT GAP; technical uncertainty сначала repo; unknown diagnosis RED/evidence/GREEN либо REPRODUCTION LIMIT; QA ambiguity NOT RUN; completed work без handoff. Fixture не объявляется доказательством произвольного LLM behavior.

**Выход:** один owner каждого правила, шесть delivery roles, пять core skills, структурный checker обнаруживает перечисленные мутации.

### B. Исполнение и доверенная публикация

**Файлы:** `.claude/settings.json`, `.codex/hooks.json`, `.gitignore`; `.claude/hooks/{check-repository-mutation.py,check-tests-before-commit.sh,check-merge-ready.py}`; необходимое замыкание `.claude/hooks/lib/` из source inventory; `.claude/tools/{run-python.sh,with-timeout.sh,publish-pr-comment.py}`; `.claude/skills/{verify,sprint-pr-cycle,external-review,finalize-pr,pipeline-audit}/SKILL.md`; соответствующие `scripts/tests/` и единый `scripts/verify-reference.sh`.

- [ ] Добавить failing cases для agent merge/auto-merge/direct main mutation и positive read-only cases, затем перенести shared classifier/grammar/guard closure из frozen source без project-specific allowlists.
- [ ] Подключить одинаковый mutation contract к Claude и Codex. Tracked `.codex/hooks.json` не должен исчезать из-за старого blanket ignore; всё личное состояние `.codex/` остаётся ignored.
- [ ] Перенести commit/readiness/publication closure полностью: parser, policy, launcher, timeout и их реальные dependencies. Сохранить fail-closed обработку ошибок и точную проверку публикуемого body. Не переписывать security parser с нуля и не упрощать проверки ради короткого diff.
- [ ] Review/finalize инструкции привести к принятому lifecycle. Сохранить triage, actual blocker handling, exact-HEAD/content-equivalence, current deterministic checks, known-risk acceptance и race recheck. Beads lookup обязан использовать авторитетную базу/снимок установленного проекта, не U2 path/prefix; добавить нужный generic helper только с dependency closure и тестом.
- [ ] Existing `codex-login`/external tooling не запускает настройку учётных записей или передачу credentials по умолчанию. Optional external capability сохраняется без mandatory второго прохода и без жёстко заданных модельных профилей оператора.
- [ ] Сделать `scripts/verify-reference.sh` единым fail-fast entrypoint: structural checker + relevant hook/parser/timeout/publisher/activation/install tests + существующий bd-sync suite. Добавить `.github/workflows/ci.yml`, job `verify-reference`, только `contents: read`; workflow ничего не коммитит и не меняет в репозитории.

**Выход:** policy и фактические guards согласованы; запрет на agent merge/main mutation и allow read-only доказаны поведенческими cases. Состав перенесённых dependencies фиксирован; пропущенный helper ломает closure check.

### C. Distribution, upgrade и rollback

**Файлы:** `.agents/{INSTALL,HOW_TO_INSTALL}.md`, `.agents/templates/` project verify/authority templates, `README.md`, `CHANGELOG.md`, `.agents/REFERENCES.md`; `scripts/tests/install-{fresh,upgrade,rollback}.*` или эквивалентная единая fixture-suite; `.memory-bank/{activeContext,progress}.md`; file-level provenance manifest рядом с intake.

- [ ] Installer читает trusted source и фиксирует SHA; target plan/VC + Draft PR + PLAN_READY предшествуют копированию. Source movement/dirty copied surfaces дают адресный отказ; обновляется тот же target PR.
- [ ] Определить explicit managed inventory: roles, пять skills, runtime adapters, hooks/tools и их dependencies. Установка проверяет missing/nested/orphan payload; не копирует папки U2 skills/rules/Memory Bank целиком.
- [ ] Fresh fixture без domain owner возвращает product gap оператору; после установки есть ровно пять skills и все owner/runtime paths разрешаются.
- [ ] Upgrade fixture начинается с v3.9 inventory и изменённых project-specific `AGENTS.md`, test commands, context, runtime settings. Создать backup/rollback manifest до изменений. Конфликтующие overrides сохраняются или дают понятный stop для адресного разрешения; force overwrite запрещён.
- [ ] Rollback fixture восстанавливает исходные managed bytes/overrides после upgrade. Beads/Memory Bank не откатываются вслепую; no credentials, game data или personal runtime state в package.
- [ ] Операторские docs описывают один фактический install/upgrade путь, stable vs RC, ограничения платформ и возврат к stable. Credits отделяют inspiration от скопированных материалов, сохраняют MIT notices и авторство. Для каждого перенесённого файла manifest содержит source path/blob, target и адаптацию; новые файлы помечены как original integration.

**Выход:** воспроизводимые fresh/upgrade/rollback fixtures и один согласованный пакет. Source provenance не является обещанием универсальной лицензии на весь U2.

## 3. Verification Contract

| AC | Ожидаемое поведение и доказательство |
|---|---|
| AC-01 | Frozen merged U2 source и base фиксированы; manifest связывает каждый transferred owner/adapter с исходным blob; все 6 skills классифицированы. |
| AC-02 | Dreadnought stable опубликован на прежнем466ad20; beta/v3.9 refs не менялись. Уже проверено intake; перед RC повторно проверить только remote identity/Latest. |
| AC-03 | Active docs/roles/runtime дают один lifecycle, budget, findings и finalize contract. Structural/static fixtures + QA manual scenario matrix; historical text явно отделён. |
| AC-04 | Ровно пять generic skills и шесть delivery owners, без mandatory GD/Almanac; broken registry/missing/orphan/nested owner дают FAIL. Fallback product authority — оператор. |
| AC-05 | Positive/non-trigger cases из среза A PASS; skill call не считается verifier и не навязывает новый spec/handoff/diagnosis. QA ambiguities не решаются моделью. |
| AC-06 | Behavioral guard/parser/publisher tests: agent mutation/readiness bypass отвергаются; read-only и trusted finalize publication разрешаются; tool failure не читается как пустое clean evidence. Adapter wiring и dependencies проверены отдельно от live runtime activation. |
| AC-07 | Fresh, v3.9 upgrade и rollback fixtures PASS; project owner/test commands/context/overrides сохранены; snapshot/source drift/missing dependency дают FAIL до опасной записи. |
| AC-08 | Independent QA + один scoped Review, current verification, triage и fingerprints; один finalize на конечном HEAD. Modified governance проверена через prior trusted bootstrap, не сама собой. |
| AC-09 | Перед RC: GitHub main protection без bypass; operator merge; tag exact merged candidate; prerelease=true, make_latest=false; Dreadnought остаётся Latest; release notes дают migration/rollback/provenance/known limits. |

Reference tests запускаются на macOS и в изолированной Linux среде. Недоступные Windows/live Claude/live Codex activation cases фиксируются как NOT RUN и явный предел RC, не PASS; серьёзность известного риска определяет Reviewer, решение по Important/Critical принимает оператор. Статические adapters не доказывают установку hooks в произвольном runtime. 5–10 реальных задач dogfood продолжаются параллельно и не образуют нового merge gate.

## 4. Named risks / Review Contract

- **R1:** docs говорят Delivery First, а runtime всё ещё требует старые mandatory passes или пропускает readiness. Проверить каждый active entrypoint, parser/adapter/installer closure.
- **R2:** generic adaptation выдумывает WHAT, обязательную новую роль/spec/diagnosis или переносит U2/Almanac domain. Проверить authority fallback и обе стороны triggers.
- **R3:** потеря project-specific installation data. Проверить conflict/backup/source drift, fresh/upgrade/rollback fixtures и ранний отказ.
- **R4:** self-certification новых review/finalize/guards. Проверять по frozen U2 prior owners; финализацию этой линии проводить доверенной неизменённой процедурой, до выполнения новых реализаций как policy.
- **R5:** incomplete dependency package, ignored Codex adapter или несуществующие tests при зелёной документации. Исполнить installed fixture и missing-helper negative cases.
- **R6:** local guard объявлен защитой remote GitHub либо платформенный smoke выдуман. Разделить actual protected main, command-level tests и runtime NOT RUN limits.
- **R7:** stable tag drift, RC становится Latest или неясная provenance. Сверить tags/releases/manifest/license notices; не менять старый snapshot.

Review IN: весь changed generic policy/runtime/install surface и перечисленные dependencies. OUT: повторный аудит всего U2, новая модель ролей, автоматическая уборка advisory и незатронутые game/product files.

## 5. Финализация и выпуск

1. Подписанные QA/Review reports публикуются в том же candidate PR; исправленные blockers имеют affected evidence. Если tests/contract/blobs не менялись, не повторять LLM review из-за base movement.
2. Main OverGate пока не защищён. Перед RC настроить required PR, запрет force push/deletion и administrator bypass, required `verify-reference` после появления этого check. Не вводить обязательное GitHub approval от второго аккаунта: independent AI evidence публикуется комментариями; оператор вручную принимает merge.
3. После полного candidate acceptance — один trusted `/finalize-pr`, затем operator merge. Выпуск `v4.0.0-rc.1` привязывается к фактическому merged commit, не к плавающему main. Stable promotion4.0 не входит в этот спринт.
4. Rollback reference: revert candidate PR либо checkout неизменного stable tag. Rollback installed project: revert upgrade PR и восстановить saved overrides из manifest; задачи/контекст согласовать по содержанию, не удалять.

## 6. Текущий статус

- [x] U2 prerequisite merged; old stable опубликован и refs проверены.
- [x] Clean target worktree и baseline tests; source inventory подготовлен.
- [ ] Independent PLAN_READY.
- [ ] Implementation A–C, deterministic checks, QA, scoped Review.
- [ ] Main protection, finalization, operator merge, RC publication.

— PM, GPT-6 (Codex).
