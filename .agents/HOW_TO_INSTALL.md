---
title: "Установка OverGate — entrypoint"
status: active
version: "5.0.0-rc.2"
date: 2026-11-21
tags: [installation]
---
# Установка

Единственный актуальный путь fresh/upgrade/rollback: [INSTALL.md](INSTALL.md).
Чистый source Git checkout с `.git` (не release ZIP) и exact source SHA → target Draft PR + plan/Verification Contract → PLAN_READY → backup/apply
→ project verify + QA/scoped review → одна финализация → operator merge.
Штатный маршрут сохраняет project overrides. Тег выпуска или exact SHA кандидата
выбирается по [INSTALL.md](INSTALL.md).
