# Skill: project-manager (мастер-копия)

Управление сессиями, спринтами и прогрессом проекта. Работает с Beads и Git, отвечает за Landing the Plane protocol.

## Состав

- SKILL.md — главный файл скилла
- references/templates.md
- install.ps1 — установщик в локальную папку плагинов Claude
- README.md — этот файл

## Установка

```powershell
powershell -ExecutionPolicy Bypass -File "<REPO_ROOT>\.claude\skills\project-manager\install.ps1"
```

Или одной командой для всех мастер-скиллов сразу:

```powershell
powershell -ExecutionPolicy Bypass -File "<REPO_ROOT>\.claude\skills\install-all.ps1"
```

После установки перезапустить Cowork-сессию.

## Источник истины

Эта папка в репозитории — мастер-копия. Правки делать здесь, коммитить, потом запускать install. Не править напрямую в `%APPDATA%\Claude\...\skills\project-manager\` — изменения не сохранятся между машинами.
