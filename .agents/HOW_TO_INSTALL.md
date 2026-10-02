---
title: "Установка OverGate — entrypoint"
status: active
version: "4.0.0-rc.1"
date: 2026-10-01
tags: [installation]
---
# Установка

Единственный актуальный путь fresh/upgrade/rollback: [INSTALL.md](INSTALL.md).
Чистый source Git checkout с `.git` (не release ZIP) и exact source SHA → target Draft PR + plan/Verification Contract → PLAN_READY → backup/apply
→ project verify + QA/scoped review → одна финализация → operator merge.
Нельзя копировать дерево поверх project overrides или использовать legacy install scripts для RC.
