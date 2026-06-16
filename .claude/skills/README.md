# Custom Claude skills (мастер-копии)

Мастер-копии кастомных скиллов проекта U2. Лежат в git для портативности — устанавливаются на любую рабочую машину через PowerShell-скрипт.

## Установка всех скиллов одной командой

После клонирования репо или `git pull`:

```powershell
powershell -ExecutionPolicy Bypass -File "<REPO_ROOT>\.claude\skills\install-all.ps1"
```

Скрипт пройдёт по подпапкам, найдёт `install.ps1` в каждой и запустит их по очереди. Старые версии скиллов будут забэкаплены автоматически с timestamp.

После установки **перезапустить Cowork-сессию**.

## Установка одного скилла

```powershell
powershell -ExecutionPolicy Bypass -File "<REPO_ROOT>\.claude\skills\<skill-name>\install.ps1"
```

## Скиллы с мастер-копией в репо

| Скилл | Назначение |
|---|---|
| `architect` | Декомпозиция задач, архитектурные документы, планирование спринтов |
| `project-manager` | Сессии, спринты, прогресс, Beads + Git, Landing the Plane |

Прочие папки (`external-review`, `finalize-pr`, `pipeline-audit`, `sprint-pr-cycle`, `verify`) — другие артефакты проекта, не входят в этот установочный цикл.

## Источник истины

Эти папки — мастер-копии. Все правки — здесь, в репо. После правок коммитить и запускать `install-all.ps1` или индивидуальный `install.ps1`. Не править напрямую в `%APPDATA%\Claude\...\skills\` — изменения не сохранятся между машинами.
