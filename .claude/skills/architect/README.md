# Skill: architect (мастер-копия)

Декомпозиция задач, анализ архитектуры, планирование спринтов. Создаёт архитектурные документы, диаграммы и задачи.

## Состав

- SKILL.md — главный файл скилла
- references/templates.md
- install.ps1 — установщик в локальную папку плагинов Claude
- README.md — этот файл

## Установка

```powershell
powershell -ExecutionPolicy Bypass -File "D:\GitHub\u2\.claude\skills\architect\install.ps1"
```

Или одной командой для всех мастер-скиллов сразу:

```powershell
powershell -ExecutionPolicy Bypass -File "D:\GitHub\u2\.claude\skills\install-all.ps1"
```

После установки перезапустить Cowork-сессию.

## Источник истины

Эта папка в репозитории — мастер-копия. Правки делать здесь, коммитить, потом запускать install. Не править напрямую в `%APPDATA%\Claude\...\skills\architect\` — изменения не сохранятся между машинами.
