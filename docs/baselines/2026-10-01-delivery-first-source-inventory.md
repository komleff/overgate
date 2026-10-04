---
title: "OverGate RC — frozen source inventory и граница generic core"
status: reference
version: "0.2"
date: 2026-10-03
tags: [overgate, delivery-first, skill-layer, inventory, release-candidate]
beads: [og-uw7, U2-0jfah]
---

# OverGate RC — frozen source inventory и граница generic core

**Исторический initial read-only снимок:** U2 tree `fb8ebfa5133c13726bd7960a1a075ab7a7089191` (Foundation #820 + Activation #827), OverGate `main` tree `466ad2020b8c46e6c14b4bbe67b5335017726542`. Все наблюдения ниже получены из tracked blobs через `git show`/`git ls-tree`; локальные untracked `.agents/skills`, `docs/plans` и `docs/archive` OverGate не читались. Acceptance Activation: [финальный passport #827](https://github.com/komleff/u2/pull/827#issuecomment-5931647528). Это source inventory для реализации, не verifier и не evidence исполнения RC.

## Текущий frozen refresh 2026-10-03

Current source — U2 `c450fa7b0d90fecf970f9931011255ea836da258`, #829 + выпуск 0.27.1 #830.
Initial source/plan выше сохранён как история. Approved refresh и portability amendment
зафиксированы в `docs/plans/2026-10-03-*`; bound plan bytes не меняются ради bookkeeping.
Шесть source skills и шесть generic delivery owners сохраняют прежние source blobs и границы.
File-level current provenance — [JSON](2026-10-01-delivery-first-provenance.json): source path,
полный blob, target, adaptation и классификация source delta каждого затронутого файла.
Новый source не зависит от локального checkout состояния: все reads — `git show` frozen SHA.

- Existing transfer delta: `INSTALL.md`, `PIPELINE_ADR.md`, `settings.json`, три consumers
  `merge-gate-parse-budget`, `publish-pr-comment`, `repository-mutation-guard`.
- Новые transfers: `pre-bash.sh`, native dispatcher unit, `claude_hooks.py`,
  `seed-claude-hooks.sh`; current credits адаптированы из source `REFERENCES.md`.
- Обязательный rename producer/consumer: `U2_COMMIT_GATE_TEST_MAX_SECONDS` →
  `OVERGATE_COMMIT_GATE_TEST_MAX_SECONDS`. Real installed gate test доказывает остаточный
  бюджет и ловит ошибочное имя; project verifier вместо U2 `npm`.
- Две `${label}` delimiters исправляют fail-closed диагностику на macOS Bash 3.2;
  source unit сначала дал RED на crash/timeout, затем GREEN. Timing/guards/recovery сохранены.
- `check-bash-cwd.py` удалён upstream, old wrappers отсутствуют в active payload.
  U2 native install/inventory/cwd/commit fixture consumers покрываются generic suites;
  raw `run-all.sh`, game/CDP (`cdp-touch.test.py`), project rules и Almanac исключены.
- Recovery rc.1 — одна unquoted absolute `cd` для простой формы пути; spaces/Cyrillic/
  parentheses и внутренние prefix cleanup deferred `og-7sr`. Codex adapter не мигрирует.
- Original integration: staged closure/order checker, installer known previous-RC identity,
  NTFS native explicit Git Bash tests, UTF-8 metadata и source LF `.gitattributes`, read-only Windows CI, migration/platform notes.
  Test helpers не являются installed runtime dependencies; dispatcher/launcher/timeout/
  parsers/guards перечислены в manifest до settings. Installed checker не требует U2 checkout.

Ниже сохранена initial extraction-карта `fb8ebfa5`; current blobs и delta — в JSON выше.

## Решения по границе

1. **Минимальный generic Skill Layer — пять процедур:** source routing, product gap, conditional product handoff, diagnosis, unfinished-work handoff. Их контракт не требует Unity или U2, если имена и адреса authority задаёт установленный проект. Registry `.agents/SKILLS.md` владеет только membership/paths; `SKILL.md` — процедурой; role owner — условием вызова (U2 ADR §3.31).
2. **`u2-almanac-authoring` оставить вне core RC.** Его trigger, inputs и output прямо называют Pilot's Almanac и current Almanac schema. Примитив `FACT != EDITORIAL` переносим, но отдельный generic `structured-authoring` менял бы scope и контракт; это будущая design decision, а не переименование. В U2 остаётся project adapter. Из core registry/installer/fixtures убрать именно обязательность этого шестого owner, сохранив запись его source-классификации в migration manifest.
3. **Не создавать обязательный `PD_ROLE`/generic GD.** U2 `.agents/GD_ROLE.md` (blob `2837a56a…`) содержит GDD, `/game-designer`, U2 docs authority и Almanac route. Сам `u2-product-gap` требует ответа PO/GD, но не создаёт роль с полномочием решать WHAT; U2 PM уже возвращает gap GD/PO или оператору. В OverGate `AGENTS.md` установленного проекта назначает product authority; если он не назначен, PM возвращает вопрос оператору. Product-handoff вызывается только на реально существующей product→PM границе. Так сохраняются все anti-bureaucracy/non-trigger условия Activation без выдуманного владельца решения.
4. Source Activation §14 dogfood продолжается параллельно; завершение 5–10 задач не становится gate для extraction/RC. Зафиксированный merged source SHA выше уже удовлетворяет условию freeze.

## Шесть skill contracts: точное source → target

Нейтральные target-имена ниже — рекомендация implementation; один rename map должен применяться атомарно в registry, role triggers, installer и static fixtures. Blobs относятся к U2 frozen tree.

| U2 source path (blob) | OverGate RC target | Выбор и нужная адаптация |
|---|---|---|
| `.agents/skills/u2-canon-router/SKILL.md` (`6ded3ab7b87f103216e7fb4ca03ddefa001ba66a`) | `.agents/skills/canon-router/SKILL.md` | Core. Сохранить `CANON ROUTE`, minimal owner set и правило «search candidate ≠ authority»; убрать перечисление U2 domains/Almanac, брать first-read/authority route из target `AGENTS.md`. |
| `.agents/skills/u2-product-gap/SKILL.md` (`e5131f235e53cf519bfdae57ddadcce4730d9a50`) | `.agents/skills/product-gap/SKILL.md` | Core. Сохранить unresolved WHAT и `PRODUCT GAP`; `Decision required from` = owner в target authority map, fallback оператор, без GD по умолчанию. |
| `.agents/skills/u2-product-handoff/SKILL.md` (`998f481839a75ee2877f5a8915ee0dece07dd6d1`) | `.agents/skills/product-handoff/SKILL.md` | Core, conditional. Сохранить `PASS_THROUGH / AMEND_EXISTING / CREATE_SPEC`; удалить Unity HOW-примеры, заменить стек-независимым запретом навязывать implementation architecture. Не требовать новой spec при готовом source. |
| `.agents/skills/u2-diagnose/SKILL.md` (`fd6abb2d961075ef870f9ec64920f3382efd29af`) | `.agents/skills/diagnose/SKILL.md` | Core. Сохранить RED → discriminating evidence → root cause → GREEN / `REPRODUCTION LIMIT`; заменить Unity/WebGL примеры на общий manual/device/live evidence. Известная простая причина не запускает тяжёлый маршрут. |
| `.agents/skills/u2-handoff/SKILL.md` (`d9c0002086281cde27856c94e42d23e1e73a73c6`) | `.agents/skills/handoff/SKILL.md` | Core. `PROJECT`/role owner/mode, точные PR+SHA, evidence и `NEXT SAFE ACTION`; убрать U2 в Purpose и брать registry текущего проекта. Finished work и обычный role transition без пробела state не требуют артефакта. |
| `.agents/skills/u2-almanac-authoring/SKILL.md` (`ad269e9ba9fadadcc21e5028499b7424b83a7293`) | **Нет core target** | Project adapter U2. ENTITY/FACT/EDITORIAL packet и missing-fact semantics принадлежат Almanac route; не копировать в generic installer. Новый generic structured-authoring — отдельный contract, если когда-либо будет выбран. |

U2 registry `.agents/SKILLS.md` — blob `f4167128…` → новый target `.agents/SKILLS.md` (на OverGate baseline отсутствует). После выбора пяти owner target registry не должен обещать шесть U2 skills или повторять их policy.

## Роли и runtime adapters: точное source → target

| U2 source (blob) | OverGate target baseline → RC | Решение |
|---|---|---|
| `.agents/AGENT_ROLES.md` (`2946bd04…`) | существующий `.agents/AGENT_ROLES.md` (`2d22ab97…`) → обновить | Registry к owner paths и optional product authority; старые mandatory 4-aspect/Sprint Final правила target v3.9 снять из active route. |
| `.agents/PM_ROLE.md` (`e266cbb7…`) | существующий `.agents/PM_ROLE.md` (`1d0d9148…`) → обновить | PM route к источнику, PASS_THROUGH и PRODUCT GAP; single finalize; без автоматических skill-проходов. |
| `.agents/SV_ROLE.md` (`7b6a2b2d…`) | создать `.agents/SV_ROLE.md` | Supervisor только для portfolio/dependencies; не mandatory для single PR. |
| `.agents/GD_ROLE.md` (`2837a56a…`) | **не создавать generic GD/PD** | U2 product/game owner остаётся project adapter; authority в target `AGENTS.md` и у оператора. |
| `.agents/PL_ROLE.md` (`38160eaf…`) | создать `.agents/PL_ROLE.md` | Missing WHAT возвращается PM; technical uncertainty исследуется; canon-router conditional. |
| `.agents/DEV_ROLE.md` (`ea846155…`) | создать `.agents/DEV_ROLE.md` | Diagnose only unknown root cause, PRODUCT GAP вместо выбранного за PO поведения. |
| `.agents/QA_ROLE.md` (`0d4262f0…`) | создать `.agents/QA_ROLE.md` | AC ambiguity → `Result: NOT RUN`, не новый global verdict и не собственное product решение. |
| `.agents/RV_ROLE.md` (`9b7e95b8…`) | создать `.agents/RV_ROLE.md` | `PLAN_REVIEW`/`CODE_REVIEW`, scoped Review Contract, BLOCKER/ADVISORY, без product authority. |
| `.claude/agents/developer.md` (`e0130973…`) | существующий `.claude/agents/developer.md` (`52f25311…`) → thin pointer | Удалить старую дублирующую TDD/review policy, направить в `.agents/DEV_ROLE.md`. |
| `.claude/agents/planner.md` (`b0b61733…`) | существующий `.claude/agents/planner.md` (`96a2eb34…`) → thin pointer | `.agents/PL_ROLE.md`; старый v3.9 план/ritual в adapter не оставлять. |
| `.claude/agents/reviewer.md` (`a2ccf4f4…`) | существующий `.claude/agents/reviewer.md` (`fefe4fca…`) → thin pointer | `.agents/RV_ROLE.md`, mode берётся из задачи. |
| `.claude/agents/tester.md` (`795406b7…`) | существующий `.claude/agents/tester.md` (`d5d7f452…`) → QA compatibility pointer | `.agents/QA_ROLE.md`; не сохранять Tester как автора обязательного второго набора тестов. |

U2 `.agents/GD_ROLE.md` не должен стать вторым policy owner через `.claude/skills/game-designer/**`; target v3.9 `Architect` остаётся исторической/опциональной способностью, но не получает скрытого обязательного gate. Новые `.claude/skills/<generic-skill>` wrappers из source Foundation не требуются без runtime evidence.

## Исполнение и installer: dependency closure

| Closure | Frozen source → OverGate baseline | Минимальное действие для RC |
|---|---|---|
| Doctrine | U2 `.agents/PIPELINE_ADR.md §3.29–3.31`, `PIPELINE.md`, `HOW_TO_USE.md`, `AGENTS.md` → target файлы уже есть, но v3.9 active text | Новая ADR supersession + согласованные active summaries; `AGENTS.md` OverGate остаётся его собственным bootstrap, U2 bootstrap не копировать. |
| Claude/Codex mutation guard | U2 `.claude/settings.json` (`0835978c…`), `.codex/hooks.json` (`98b436e2…`), `check-repository-mutation.py` (`4dbe85e8…`); target имеет settings (`441b8ad7…`), старый merge-ready hook и SessionStart `codex-login.sh`; Codex adapter отсутствует | Минимальная shared closure: `check-repository-mutation.py` → `commit_command_classifier.py` → `shell_grammar.py`, launcher `.claude/tools/run-python.sh`, Claude settings и новый Codex hooks. `check-bash-cwd.py` добавлять только при принятии cwd-guard behavior; он тоже зависит от classifier. Unity allowlist/U2 env исключить. |
| Commit/readiness | Source `check-tests-before-commit.sh` → classifier + `run-python.sh` + `with-timeout.sh`; source `check-merge-ready.py` → `shell_comment_parser.py` → `shell_grammar.py` и `readiness_policy.py`; trusted publisher → `readiness_policy.py` | Для ADR §3.30 fast path нужен target test command и это замыкание. Старый target `check-merge-ready.py`/tests уже существуют: сохранять их поведение, менять только нужное для one-finalize и safe publication; если source finalize требует trusted publisher, добавить его вместе с policy/parser, не одиночным файлом. U2 suite/timeout/env не копировать буквально. Source mutation parser имеет известный `gh api --method` limit: локальный hook не считать полной remote-write защитой. |
| Session helpers | U2 `docs-orientation-primer.sh` содержит U2 docs route, `codex-login.sh` — U2 opt-in auth preference; target уже имеет `codex-login.sh`, но не orientation primer | Не расширять minimal core RC этими U2-вариантами. Если потребуются позже, отдельная адаптация без project paths/credentials. |
| Review/finalize | U2 `.claude/skills/{verify,sprint-pr-cycle,external-review,finalize-pr,pipeline-audit}/SKILL.md` → target одноимённые v3.9 files | Content-equivalence, one scoped Code Review, one finalize, optional one-shot external должны совпасть с ADR. U2 `/verify` содержит .NET/Unity commands: target сохраняет stack-adaptation placeholder; `external-review` содержит U2 model/profile и historical modes — не copy verbatim. `pipeline-audit` имеет U2/Almanac/game manifest — target inventory пересобрать. |
| Installer | U2 `.agents/INSTALL.md`, `.agents/HOW_TO_INSTALL.md` → target `INSTALL.md` v3.9, `HOW_TO_INSTALL.md` отсутствует | Обновить copy manifest для пяти generic owners, новых role owners, `.codex/hooks.json` и полного hook/tool closure. U2 installer жёстко перечисляет 7 ролей, 6 `u2-*` и копирует `.claude/skills/` целиком вместе с game-designer/mobile-game-analyst; generic RC должен перечислить только свой payload. Сохранить frozen reference/source check и fail-closed missing/nested/orphan guard. |
| Project data | U2 `.claude/rules/{docs-authority,client-unity,server,...}`, Beads wrappers, Memory Bank, game docs | Не переносить как generic payload. Project setup определяет test commands, product owner, docs route, Beads state; upgrade не перезаписывает их silently. |

## Самый малый осмысленный test/доставка scope

**Тесты для будущей реализации, сейчас не запускались:**

- `scripts/tests/activation-routing.test.sh` из U2 → адаптированный target static fixture для PM/PL/DEV/QA/RV/SV, positive **и non-trigger** paths; убрать mandatory GD/Almanac patterns. Source fixture сам честно говорит: static routing ≠ фактическое поведение произвольной LLM.
- `scripts/check-agent-context.py` + `scripts/tests/check-agent-context.test.sh` → переносить **только** ROLE-001–003/SKILL-001–005 с пятью target именами и active-corpus exclusions; исходный checker содержит Unity, web-client, Caddy и CI проверки U2, поэтому raw copy недопустим.
- `scripts/tests/install-runtime-closure.test.py/.sh` и `pipeline-audit-inventory.test.sh` → компактные target tests: missing owner/registry/hook/tool/adapter = fail closed, nested/orphan skills = fail, fresh install = five owners, archive/untracked content не попадает в package. Source тесты hardcode six U2 skills и весь U2 executable inventory; не копировать их без адаптации.
- Для executable guard family: портировать узкий набор `repository-mutation-guard.test.sh`, `hooks-executable.test.sh`, `check-merge-ready.test.sh`, `commit-gate-dispatcher.test.sh` + parser/timeout tests, соответствующих **реально** перенесённым hooks. Проверить allow для read-only и блок merge/direct main mutation/ambiguous commit; не копировать весь U2 `scripts/tests/run-all.sh` или Unity/product tests.
- Installer smoke на чистом fixture и upgrade fixture v3.9→RC с rollback доказательством. Не менять опубликованный старый installer/tag.

**Рекомендованные delivery slices в одном RC candidate PR (каждый — отдельный reviewable commit; release только после полного замыкания):**

1. **Owner contract:** ADR/roles/registry/пять skills + static routing/structure fixture. Нет нового PD/GD owner и нет hidden lifecycle gate.
2. **Executable contract:** минимальный shared mutation guard + Claude/Codex adapters, затем commit/readiness closure только по выбранным hook routes; scoped review/finalize/verify + узкие behavioural tests. На границе slice 2 не оставлять doc/runtime drift.
3. **Distribution contract:** installer, inventory/closure, operator docs/credits, fresh+upgrade+rollback fixture. Frozen candidate получает independent QA/scoped review по назначенным AC, затем штатную финализацию.

Границы срезов — способ сделать diff проверяемым, **не** три отдельных verifier cycles и не независимые промежуточные релизы.
