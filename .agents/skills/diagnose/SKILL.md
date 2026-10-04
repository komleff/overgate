# diagnose

## Purpose

Не позволить DEV чинить дефект с неизвестной причиной по первой гипотезе.

## Trigger

Причина наблюдаемого дефекта неизвестна.

## Inputs

Observed failure, environment, reproduction data, relevant code and evidence.

## Process

```text
Observed failure → Reproduce → RED confirmed → Minimise failing surface
→ Facts vs hypotheses → Discriminating evidence → Root cause → Minimal fix
→ Original reproduction GREEN → Regression → Affected verification
```

RED — проверенный failing reproducer/evidence, не обязательно automated unit test.
Для visual/device/live-only допускаются deterministic/manual reproducer,
screenshot/log, build/device matrix или другой проверяемый failure signal.
Автоматизированная regression нужна, когда её разумно и надёжно построить.

## Output

Краткая diagnosis с RED, подтверждённой причиной, fix, GREEN и affected verification.
Если воспроизвести объективно невозможно: `REPRODUCTION LIMIT` + substitute evidence.

## Stop conditions

Нельзя установить причину по имеющимся данным — зафиксировать предел воспроизведения и evidence.

## Do not

Не заменять diagnosis первой гипотезой. Не дублировать TDD: TDD доказывает новое поведение,
diagnose — причину существующего failure.
