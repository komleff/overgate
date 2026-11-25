# Legacy Beads: preservation живого server-mode — план исследования

Статус: DRAFT / NOT PLAN_READY. Режим CRITICAL: потеря данных, общий writer и governance установщика. Источник: `f27571057547ba4e17dcf09be44af28a83f688f7` (Slipstream rc.2); изменение требует нового точного source SHA и отдельного принятия потребителем. Merge выполняет оператор.

## Цель и предел

Дать существующему legacy-v0 проекту с локальным Dolt server проверяемый переход к установленной helper closure и затем managed-v1 без потери существующего состояния. Старые задачи могут остаться в опубликованной истории; archive/reset и fresh activation поверх существующей DB не входят в scope. Первый consumer — LBA, однако решение не должно содержать product data или LBA-пути.

Текущий rc.2 принимает только `embedded` и отождествляет target и standalone writer. В LBA server DB расположена в основном checkout, target — отдельная PR-ветка, клиенты используют связанные worktree. Существующий `beads-backup` нельзя объявить отсутствующим. `bd export --all` — логический экспорт, не полный Dolt backup.

## Предлагаемая граница

Поддержать только явно идентифицированный локальный standalone owner и его зарегистрированные linked worktree. Отдельные server DB/remote servers, shared/proxied Dolt и неизвестные clients должны давать отказ. Явно различать target и owner, фиксировать их canonical paths, common Git directory, origin fetch/push, SHA target и trusted owner main, полный перечень клиентов и очередей. Не ослаблять packet v1 или существующий embedded путь; новый формат и его область действия должны быть явно распознаны и повторно проверены при plan/apply.

Надёжный способ доказать идентичность server и DB, избежать автозапуска server через `bd` и обнаружить перезапуск/замену при экспорте **ещё не установлен**. Его необходимо доказать на синтетической базе и описать до PLAN_READY: привязать процесс и listener к owner и ожидаемому DB identity, выбрать проверяемую консистентную логическую выборку и подтвердить, что неизвестные/несогласованные pid, port, config, metadata или процесс блокируют операцию. OS-specific реализация допустима только с явным fail-closed для остальных платформ. Нельзя полагаться только на `--readonly`, количество записей или liveness PID.

Синтетическая проверка доказала, что host/port/database/project_id и `bd context` могут оставаться прежними при замене server и изменении экспортируемых задач. Изменение listener PID обнаруживает только этот частный случай; защита от PID reuse и TOCTOU пока не доказана. В исходниках Beads v1.2.2 external lifecycle выбирается `BEADS_DOLT_SERVER_MODE=1`: на недоступном тестовом port экспорт отказал без наблюдаемого автозапуска. Это кандидат, а не подтверждение всех сценариев. Требуется связать конкретное открытое соединение с квалифицированным процессом и owner DB и повторно проверить процесс/DB и экспорт в границах операции; если связь или quiescence недоказуемы — STOP.

Нужны определённые authority и заморозка writers: fence обновлённых helpers сам по себе не блокирует прямой `bd` и старые экземпляры. В manifest и evidence зафиксировать владельца подтверждения полного списка, каждый client и очередь, временные границы quiescence, frozen R и неизменность состояний до/после. При недоказанной полноте или активности — STOP. DB backup должен быть приватным, восстанавливаемым и проверенным отдельно от логического export; источник не вправе сам менять живую DB или публиковать snapshot при inventory.

На отдельной synthetic DB без конкурентных писателей `dolt backup sync-url` восстановлен в новый каталог: совпали 29 видимых SQL tables, выбранный `dolt_log`, две ветки и working set; локальные metadata/config/port и перечень named backup не изменились. Команда Dolt описывает `sync-url` как point-in-time snapshot branches, tags, working sets и remote-tracking refs. Эти результаты не доказывают всю историю, отсутствие изменений внутренних файлов сервера, непрерывную quiescence или identity живой LBA DB. Перед выбором маршрута нужны отрицательные проверки конкурентной записи, рестарта и подмены, независимое полное readback и привязка restore receipt к одному server/DB state и frozen R.

В отдельной synthetic проверке с конкурентным writer успешный backup содержал промежуточное состояние, отличное от до и после. Проверка `6 → 7 → 6` показала, что равенство before/after не доказывает отсутствие промежуточных записей. Переход требует надёжно подтверждённой quiescence или отдельно доказанного непрерывного контроля writes: простого сравнения снимков недостаточно. Tuple listener PID/start/cwd/port отразил рестарт и подмену на тесте, но секундная точность `lstart`, PID reuse и TOCTOU не позволяют объявить его полноценной гарантией identity.

В synthetic server `SET GLOBAL read_only=ON` успешно возвращал `1`, но SQL UPDATE и `bd create` оставались возможны: этот переключатель не является freeze. Startup `--readonly` отклонял обе записи и допускал backup на тесте, но требует отдельного управления lifecycle и не препятствует другому серверу или файловой записи владельца ОС. Transaction/table lock не проверялся. Не переключать или перезапускать живой server по результатам этой репетиции; owner/quiescence protocol сначала должен быть определён, независимо проверен и согласован с фактическими клиентами.

## Поверхность реализации

После отдельного PLAN_READY: `scripts/bd-upgrade-preserve.py`, `scripts/install-overgate.py`, `scripts/bd-upgrade-fence.py`, связанные Beads helpers и тесты `scripts/tests/bd-upgrade-preserve.test.py`, `scripts/tests/install-distribution.test.py`; документация `.agents/INSTALL.md` и `.agents/HOW_TO_USE.md`, manifest только при добавлении файлов. Перед реализацией дополнить точные interfaces, формат packet, доверенный источник identity/restore receipt, матрицу этапов восстановления и решение о platform scope. Не начинать реализацию с непроверенными placeholders.

## Verification Contract

| AC | Поведение и метод |
|---|---|
| 1 | Disposable server с собственными DB/port/PID: полный логический export, независимый readback и физический backup/restore с проверкой состояния; никакого доступа к реальным проектным DB. |
| 2 | Подмена/перезапуск server, неверный DB/port/path, расхождение metadata/config/port, stopped server и автозапуск дают STOP до packet/apply/task write. Тест доказует привязку именно к owner DB. |
| 3 | У каждого авторизованного owner/client отдельный учёт queue/receipt; неизвестный client, pending или drift DB, R, target, owner, CLI/source/fence приводят к fail-closed. Прямой старый writer не считается защищённым одним marker. |
| 4 | Target с отличающимся HEAD и owner на trusted main допустимы только по точному reviewed contract; подмена target/owner и неизвестный Git common-dir блокируются. Plan/apply заново проверяют один и тот же packet. |
| 5 | Отдельные fixture для fence, прерывания, полного и неполного installer journal, publisher setup и первой publication; unsafe rollback запрещён, state и журналы сохранены для reviewed recovery. |
| 6 | Существующие embedded и packet v1 не меняют условия и проходят regression; ни одна подмена legacy DB, metadata или remote не допускается. Live LBA отдельно квалифицируется после независимого review и репетиции. |
| 7 | Независимые PLAN_READY, QA и scoped Code Review привязаны к фактическому source, тестам и contract. GitHub CI и live Windows/Codex/Claude сообщаются отдельно. |

## Откат и зависимость

До реализации правок LBA не менять. До коммита в target возможен только подтверждённый rollback по полному журналу с допустимыми fence/R/control; прерванный журнал, partial fence и publisher setup требуют reviewed recovery, а не предположения об автоматическом откате. После первой publication сохранять новую историю; protocol rollback автоматом запрещён. LBA PR #27 и #28 остаются заблокированы до проверенного source и отдельного точного плана.
