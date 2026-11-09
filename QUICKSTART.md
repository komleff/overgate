# OverGate: первый проект с агентом

Для одного оператора, то есть человека, который ставит задачу, принимает результат и нажимает
merge — кнопку принятия изменений. Программировать и управлять проектом за вас будут агенты
в Codex или Claude Code. Поддерживаемые среды: Windows с Git Bash, macOS и Linux.

## Что понадобится

Агент проверяет `git --version`, `bash --version`, `python3 --version` (Windows: `py -3 --version`),
`jq --version`, `node --version`; `gh --version` — при shell PR route, `bd --version` —
перед post-merge Beads activation.
Git хранит историю; GitHub размещает проект; gh — программа доступа к GitHub; Python/Bash/Node/jq
запускают инструменты. Версию выбранного Codex/Claude Code агент фиксирует из его интерфейса;
`claude --version` нужен только при выборе Claude Code. Beads (`bd`) хранит задачи между сессиями, Memory Bank — принятые решения.
Для Beads проверена только версия **1.2.2**. Если её нет, агент выбирает именно v1.2.2 (не latest), подходящий архив Windows/macOS/Linux по
[инструкции для ОС](https://github.com/gastownhall/beads/releases/tag/v1.2.2), затем проверяет версию.
Helper и установщик сами bd не скачивают. Для PR нужен доступ к GitHub через `gh`
или авторизованный коннектор; `gh auth status` проверяют при использовании shell `gh`.
Для Beads после merge нужен отдельный авторизованный `git push` из publisher checkout.

Source OverGate — чистый Git checkout (`git clone`) на выбранном RC и точном SHA (номере версии
исходного кода). ZIP без `.git` не подходит. `v4.0.0-rc.5` — опубликованный prerelease;
`v4.0.0-rc.5.1` пока candidate: выбирайте его exact SHA для проверки.
Stable/Latest остаётся v3.9.0.

На Windows для fresh install source OverGate и проектный target создавайте сразу как LF checkout:
`git clone -c core.autocrlf=false '<repo-url>' '<checkout-path>'` (замените оба
placeholder). Этот repo-local параметр задаётся **до checkout/install**; для fresh
Beads после merge тем же способом создайте отдельные publisher и peer clone.
Существующий CRLF checkout без Beads state не перенастраивайте и не сбрасывайте:
сохраните работу, создайте новый LF clone и проверьте чистоту. При **любых** уже
имеющихся Beads DB/queue/receipts сохраните старый checkout и выполните B4 reviewed
inventory/preservation до перехода; новый clone сам по себе task state не переносит.

## Одна фраза агенту

Откройте корень проекта в выбранном runtime — Codex или Claude Code — и загрузите project hooks
при запросе доверия. Для Claude Code используйте явный запуск `claude --permission-mode auto`.
Для Codex сохраняются его существующие permissions; Claude-specific mode flags к нему не относятся.
Поручите агенту:

> Установи OverGate из чистого trusted Git checkout выбранного RC по `.agents/INSTALL.md`.
> Сохрани мою product authority, команды проверок и custom hooks; подготовь target Draft PR,
> получи PLAN_READY от отдельного reviewer-агента, выполни apply и helpers в указанном порядке,
> заполни `.agents/project/verify.sh` тестами проекта и проверь результат. Merge оставь мне.

Draft PR — предложение изменений, пока не готовое к принятию. PLAN_READY — независимая проверка
плана; установщик сам себе её не выдаёт. Product authority означает ваше право выбирать цель.
Если проекта ещё нет на GitHub, агент создаёт репозиторий с первым README-коммитом в main через
создание репозитория, затем работает в отдельной ветке; агент не пушит в main.

Дальше агент открывает Draft PR, описывает проверки, создаёт план без записи файлов,
получает независимый PLAN_READY, выполняет `apply` и запускает на install branch:

```bash
bash scripts/og-init-memory-bank.sh
bash scripts/og-protect-main.sh
```

Первый helper создаёт шесть файлов Memory Bank, второй настраивает и проверяет защиту главной ветки
на GitHub. Существующие данные проекта сохраняются. Агент заполняет `verify.sh`
реальными тестами проекта; если тестов нет, создаёт минимальные и запускает их.
Незаполненный шаблон проверки намеренно возвращает ошибку. **В install PR нет**
`bd init`, локальной Beads DB, task ID и публикации `beads-backup`.

После проверок и вашего merge install PR агент переходит на чистый доверенный `main`
проекта. Для нового Beads проекта он получает от вас фактическую задачу и явный
project prefix, готовит отдельные publisher и peer checkout, затем запускает:

```bash
bash scripts/bd-activate.sh --publisher-root '<absolute-publisher-checkout>' \
  --peer-root '<absolute-peer-checkout>' --bd-bin '<absolute-qualified-bd-1.2.2>' \
  --prefix '<project-prefix>' --actor '<agent-UUID>' \
  --title 'Название принятой задачи' --work-dir '<absolute-private-work-dir>'
```

Замените placeholders на абсолютные пути вашей ОС; private work directory находится
вне проекта и обоих checkout. На Windows используйте пути, которые принимает Git Bash.
Activation требует repo-local Git identity и авторизованный HTTPS credential helper
либо SSH agent/remote. Успех — реальный ID, confirmed claim, published SHA и чтение
того же task state из peer. Если отказ произошёл **после создания checkpoint**, сохраните
очередь/private work directory для `--resume` или reviewed recovery. Отказ preflight
до checkpoint требует устранить причину и повторить новый запуск; без принятой
задачи очередь не создаётся. При недоступном writer после checkpoint очередь pending;
`tmp:` не является готовым ID. Подробности — [INSTALL](.agents/INSTALL.md#beads-и-облачный-агент).

## Режимы Claude Code

`auto` проверяет действия классификатором Claude Code без рутинных вопросов. Файл settings с
`defaultMode: auto` сам по себе не доказывает режим сессии: текущий Claude Code может игнорировать
auto/bypass в project settings. Поэтому используйте явный запуск `claude --permission-mode auto`.
Агент записывает фактический режим и версии. Если auto недоступен (Manual, сообщение об ошибке
или рутинные запросы разрешения), запасной вариант: пересоздать план с `--mode bypass`, затем
запустить `claude --permission-mode bypassPermissions`. Хуки и deny-запреты остаются теми же.
Если доступный auto блокирует штатное действие, агент фиксирует R6/FAIL для оператора;
bypass не используется для скрытия такого отказа. [Правила Claude Code](https://code.claude.com/docs/en/permission-modes).
Settings с правками вашего проекта сохраняют permissions и mode; явный --mode на них остановится.

Для разовой задачи добавьте к поручению «используй `--no-beads`»: Beads closure не
устанавливается, режим остаётся `none`, Memory Bank создаётся. При upgrade прежний
`beads:false` тоже остаётся `none`; `legacy-v0` не меняется молча. Переход существующего
Beads проекта на `managed-v1` требует отдельного preservation packet, fence всех
известных старых writers, принятого target PR и merge. Pending работа сохраняется
и блокирует switch до разрешения. PR через коннектор не требует shell `gh` login,
но для post-merge Beads publication всё равно нужен авторизованный Git transport.

## Что появится

`.agents` объясняет агентам роли и порядок работы; `.claude` и `.codex` подключают защитные хуки
(проверки перед действиями). `.memory-bank` хранит контекст; при Beads activation
локальная `.beads` и опубликованный `beads-backup` хранят задачи.
`.overgate/install-state.json` хранит версию и режимы без абсолютных путей вашей машины.
Существующий Memory Bank даже с недостающими файлами не перезаписывается: агент сообщает пробелы.

Главная инструкция для вас — **шпаргалка оператора** `.agents/HOW_TO_USE.md` в проекте:
копируемые промпты ролей (PM, Supervisor, гейм-дизайнер, Planner, Developer, Reviewer, QA),
частые команды и правила решения о merge. Папка `.agents` начинается с точки, поэтому скрыта:
в Finder покажите её `Cmd+Shift+.`; в Проводнике Windows 11 — «Вид → Показать → Скрытые
элементы», Windows 10 — вкладка «Вид», флажок «Скрытые элементы».

## Как ставить задачи после установки

Откройте корень проекта в Claude Code или Codex и напишите:

```text
Ты PM. Прочитай .agents/PM_ROLE.md.
Задача: [конкретный результат]
```

Промпты остальных ролей — в шпаргалке `.agents/HOW_TO_USE.md`.

## Первый небольшой PR

Поручите, например: «Исправь опечатку в README». Агент выбирает FAST — краткий путь безопасного
изменения: задача → план → реализация → реальные проверки → finalize → вы принимаете результат
и нажимаете merge. Для функциональности сначала независимый PLAN_READY, затем QA (проверка
результата) и один Code Review (проверка кода другим агентом). Финализация фиксирует exact HEAD —
конкретную версию, прошедшую проверки. Агент не выполняет merge.

## Ограничения и откат

Защита main на GitHub требует admin. Коды helper: 2 — нет прав, 3 — нет gh auth, 4 — тариф
не позволяет защиту private repo, 5 — работает ruleset (набор правил GitHub, требуется сверка).
Агент записывает код/R8 в target PR и уже созданный Memory Bank. При 2/3/4 удалённая защита
не обеспечена helper-ом; при 5 он ruleset не меняет. Код 6 — остановка: проверка не подтвердилась.
Локальные хуки не защищают remote-коннекторы; прямое снятие protection API остаётся риском R7.

Сразу после `apply`, до helpers и изменений, агент может выполнить `rollback --target ...
--backup <путь из apply>` по INSTALL: вернутся исходные managed-файлы и install-state;
любой изменённый файл из журнала остановит откат. После project правок — revert install PR
(обратное изменение через PR). После первой managed публикации откат protocol запрещён;
База задач, Memory Bank и защита GitHub installer rollback не снимает.

Запускайте сессию в корне проекта. Из подкаталога своего checkout dispatcher показывает
одну копируемую shell-safe команду `cd` к проверенному root, включая пути с пробелами,
кириллицей, скобками и апострофом. Вне проверенного Git root для сложного пути начните
новую сессию из root: неизвестный каталог не превращается в разрешённый `cd`.
Windows и живые Claude/Codex проверки требуют отдельных receipts в candidate PR;
unit-тесты и CI не заменяют их. Prefix новой Beads базы задаётся явно при activation
и сверяется с native CLI; существующие ID не переписываются.
