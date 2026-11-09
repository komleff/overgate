# ADR-INDEX — реестр архитектурных решений

> Реестр канон-решений проекта. Процесс ведения — [`ADR-0000-ADR-Process.md`](ADR-0000-ADR-Process.md), шаблон новой записи — [`ADR-TEMPLATE.md`](ADR-TEMPLATE.md).
> Перед задачами по архитектуре/домену сверяйся с этим реестром (см. `.claude/rules/universal.md`, блок «Канон-решения»). Если решение противоречит записи — не «улучшать по ходу»: новый ADR со статусом `supersedes`, потом код.

## Процесс (generic, входит в OverGate)

| ADR | Тема | Статус |
|-----|------|--------|
| [ADR-0000](ADR-0000-ADR-Process.md) | Процесс ведения ADR | accepted |
| [Pipeline ADR §§3.28–3.33](../../.agents/PIPELINE_ADR.md) | Delivery First generic binding, lifecycle, single finalize, пять skills, автономная установка rc.4 | accepted for v4 RC |
| [Pipeline ADR §3.34](../../.agents/PIPELINE_ADR.md) | Managed Beads publication, typed queue и trusted publisher | proposed for rc.5 WI-A |
| [Pipeline ADR §3.35](../../.agents/PIPELINE_ADR.md) | Portable Bash recovery в текущем Git root | proposed for rc.5 WI-C |
| [Pipeline ADR §3.36](../../.agents/PIPELINE_ADR.md) | Шпаргалка оператора в HOW_TO_USE и generic роль проекта GD; частично заменяет inventory/AC-04 PR #7 | proposed for rc.5.1 |
| [Pipeline ADR §3.37](../../.agents/PIPELINE_ADR.md) | Commit tier reference-гейта overgate: ограниченный набор для гейта коммита, полный — `/verify` и CI | proposed for rc.5.1 |
| [Pipeline ADR §3.39](../../.agents/PIPELINE_ADR.md) | Обычный вход пользователя в Git для сетевых вызовов Beads: перенос allowlist `credential.*`/`user.*` только в ls-remote/fetch/push/commit-tree; дополняет §3.34 | proposed for rc.5.2 |

## Решения проекта

> Продуктовые и архитектурные ADR конкретного проекта добавляются сюда по [`ADR-TEMPLATE.md`](ADR-TEMPLATE.md) (каждый — с обязательным блоком «Отклонённые варианты»).
>
> В dogfood-проекте U2 это были ADR-0001…0031 (физика, HUD, экономика, базы и т.д.) — они **не переносятся** в overgate как project payload. Этот раздел в новом проекте наполняется с нуля.
