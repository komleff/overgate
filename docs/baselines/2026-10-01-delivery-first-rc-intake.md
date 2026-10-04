---
title: "Delivery First RC — source freeze и состояние OverGate"
status: active
version: "0.1"
date: 2026-10-01
tags: [delivery-first, release-candidate, provenance, baseline]
beads: og-uw7
---

# Delivery First RC — source freeze

## Источники

| Объект | Проверенное состояние |
|---|---|
| U2 source | `fb8ebfa5133c13726bd7960a1a075ab7a7089191` — operator merge [Activation #827](https://github.com/komleff/u2/pull/827), после Foundation #820 |
| U2 acceptance | [Final passport #827](https://github.com/komleff/u2/pull/827#issuecomment-5931647528): QA PASS, scoped Review APPROVED, deterministic verify и CI SUCCESS |
| U2 исходные планы | `2c1a1f607c9d0d4aa46c867843776de79b97babb`, [PLAN_READY](https://github.com/komleff/u2/pull/815#issuecomment-5886794868); оба документа byte-identical в merged source |
| OverGate base | `466ad2020b8c46e6c14b4bbe67b5335017726542` — актуальный remote main на момент intake |
| Рабочая ветка | `codex/delivery-first-rc`, отдельный clean worktree от exact base |
| Независимая линия | [PR #6](https://github.com/komleff/overgate/pull/6), head `099ff76763513079a426b9cc80bdbb0ee18e0982`; не входит в source/RC scope |
| Трекер | OverGate `og-uw7`; U2 preparation `U2-0jfah`; completed Activation `U2-mtdze` |

Первичный план переноса и его AC-01–09 сохранены в [merged U2](https://github.com/komleff/u2/blob/fb8ebfa5133c13726bd7960a1a075ab7a7089191/docs/plans/2026-10-01-overgate-delivery-first-rc.md). Этот intake обновляет факты; реализация RC ещё не выполнена.

## Старый стабильный выпуск

Оператор принял старую линию по четырём месяцам использования, имя и схему версий. 2026-10-01 опубликован [OverGate v3.9.0 — Dreadnought](https://github.com/komleff/overgate/releases/tag/v3.9.0): `draft=false`, `prerelease=false`, `/releases/latest` указывает на него.

- Новый тег `v3.9.0` указывает непосредственно на `466ad2020b8c46e6c14b4bbe67b5335017726542`.
- Beta `v3.9.0-beta.1` сохранила annotated tag object `5dfc1a43c3802db62b86636b283eb09aa4d3a488`, peeled commit `466ad2020b8c46e6c14b4bbe67b5335017726542`.
- Прежний `v3.9` сохранил annotated object `5d603d8ca43f18a36ffc5b970c6da63f666934b1`, peeled commit `592905a981d967b0e673d1ac759f811c8829308b`.
- Payload старого выпуска не изменялся. Его известные ограничения не объявлены исправленными; они перечислены в release notes. `LICENSE` остаётся MIT, copyright Dmitriy Komlev.

Для установки старой линии читать installer из тега `v3.9.0`, а не из будущего плавающего main. Новая линия уже названа оператором `v4.0.0-rc.1`; её будущий выпуск — prerelease и не Latest. Стабильный `v4.0.0` требует будущей приёмки.

## Baseline проверки до изменения исполнения

На clean OverGate base выполнены локальные проверки:

| Проверка | Результат | Граница |
|---|---|---|
| `python3 .claude/hooks/test_check_merge_ready.py` | 150/150 PASS | Старый merge-ready guard, native macOS |
| `bash scripts/test-bd-sync.sh` | 23 PASS, 0 FAIL | Синтетический локальный remote и stub bd; без записи в реальные задачи |
| Reference `/verify` | Не запускался | Это незаполненный шаблон для target-проекта; не выдаётся за runnable reference healthcheck |
| Рабочее дерево | Clean на baseline | Личный checkout и untracked файлы PR #6 не использовались и не менялись |

Эти результаты устанавливают baseline, а не приёмку будущего RC. В RC нужны собственные runnable reference checks и отдельный install-time шаблон для проекта-потребителя.

## Внешние зависимости и ограничения

- Remote `main.protected=false`; repository rulesets пусты. GitHub-side protection должна быть настроена и подтверждена перед RC merge/publication. Локальный hook этого не доказывает.
- Локальные runtime-проверки пока выполнены только на macOS. Linux проверяется в изолированной среде; Windows/Codex/Claude live activation не объявляется проверенной по одному чтению конфигурации.
- Доступный Beads — 1.2.2. Старый restore отказал из-за различия сериализации: у тех же семи issues добавлено `_type: issue`; одна memory и остальные поля совпали. Remote и last-seen оба `83d8c8cad0342ea6b055fa24c9376a46ea2c4a2c`. Оба снимка сохранены, forced restore не применялся; штатный export после добавления sprint issue прошёл. Это не исправление старого restore и не новая гарантия совместимости stable.
- Задача оператора разрешает публикацию PR/evidence и начало финализации без отдельного permission prompt. Merge остаётся решением и действием оператора. Эта граница явно уточнена оператором при dogfood U2 #827.

## Bootstrap доверия

RC меняет собственный процесс. Для его разработки применяется уже принятый Delivery First из frozen U2 source: CRITICAL budget 6; independent Plan Review до implementation, QA по AC, один scoped Code Review и affected rechecks по дефектам. Изменяемые review/finalize/guard файлы проверяются как объект работы, а не используются для самосертификации.

— PM, GPT-6 (Codex).
