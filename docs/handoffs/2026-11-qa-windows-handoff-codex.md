PROJECT: OverGate (komleff/overgate)
BOOTSTRAP: Прочитать .agents/QA_ROLE.md; затем .agents/PIPELINE_ADR.md §3.29 (формат QA EXECUTION)
PIPELINE: стандартный OverGate; публикация только через .claude/tools/run-python.sh .claude/tools/publish-pr-comment.py <PR> <файл>

ROLE: QA
ROLE OWNER: .agents/QA_ROLE.md
ROLE MODE: не применимо (QA)
MISSION: независимая приёмка на нативной Windows (Git Bash + нативный Python 3.14, русская локаль cp1251), в репозитории ничего не править

TASK: приёмка PR #20 (og-4py, B-08) и PR #19 (rc.5.2) на Windows; обе задачи НЕ начаты
MODE: только проверка и отчёт
PRODUCT SOURCE: описания PR #19 и #20 и их Verification Contract; PR #18 уже влит (merge commit b04b21c81cc1039b0ee499d80e28f4fc1a0a9850)
PLAN / VERIFICATION CONTRACT: PR #20 — AC B-08 (вход Beads, пробы push-dry-run через Bash, Node, Python); PR #19 — AC-02..AC-05, AC-07, D-7 (guard и гейт коммита, бюджет verify.sh 450 с на прогон)

REPOSITORY: komleff/overgate; рабочий клон C:/work/og-pr18-qa (LF, core.autocrlf=false, detached HEAD b04b21c), не удалять
PR: #19 (https://github.com/komleff/overgate/pull/19), #20 (https://github.com/komleff/overgate/pull/20)
BRANCH: ветки PR получить через git fetch origin; snapshot может устареть
BASE SHA: b04b21c81cc1039b0ee499d80e28f4fc1a0a9850 (main после PR #18)
CANDIDATE SHA: PR #19 — b16128dbdb28ce6ef4b6aea1888a1ba755e7c76d; PR #20 — 09dcc531f6ecaf0d15c7d2502cfcec20d6e6a451 (сверить с текущим HEAD PR перед работой)

DONE:
- PR #18, fafdf67: commit tier FAIL (activation, read_text без encoding на cp1251); шаги B и C PASS; шпаргалка по тексту PASS.
- PR #18, 854a840: activation PASS, commit tier FAIL на mutation-guard (201 pass, 3 fail); пошагово 27 шагов, 14 PASS, 13 FAIL.
- Диагностика og-0pu на b04b21c: опубликована в PR #18.
- Утренний отчёт Супервизору: .overgate-runtime/morning-report-supervisor.md (локальный файл).
IN PROGRESS: ничего не запущено
OPEN:
- PR #20: переключиться на SHA; проверить, что repo-local credential.helper не задан (rc 1); bash scripts/lib/bd-env.sh --diagnose push-dry-run; node scripts/lib/bd-git-environment.mjs --diagnose --probe push-dry-run; .claude/tools/run-python.sh scripts/install-overgate.py network-diagnose --probe push-dry-run; проверить отсутствие временных файлов переноса в TEMP/TMPDIR; комментарий в PR #20 «QA LIVE — og-4py B-08 (Windows native, 09dcc53)».
- PR #19: переключиться на SHA; verify.sh дважды с замером; repository-mutation-guard.test.sh (3 кейса и кириллический путь); 22 шага full-уровня по одному с логами в .overgate-runtime/perstep/ (в with-timeout ровно 5 SKIP, у publisher явный SKIP symlink-кейсов); publish-pr-comment.test.py; пробный пустой коммит в одноразовом клоне без push; комментарий «QA LIVE — rc.5.2 PR #19 (Windows native, b16128d)».

EVIDENCE (публикации в PR #18): https://github.com/komleff/overgate/pull/18#issuecomment-6745327216 ; #issuecomment-6745950771 ; #issuecomment-6746529872 ; #issuecomment-6748402588 (диагностика og-0pu). Логи: C:/work/og-pr18-qa/.overgate-runtime/{diag,perstep}
Установленные причины падений на Windows: subprocess по имени bash запускает System32\bash.exe (заглушка WSL); нет права на symlink (WinError 1314); кодировка cp1251 объясняет лишь 2 шага из 10. Не установлены: mutation-guard (3 кейса), module-resolution-closure, пустой замер в with-timeout-transparency, bd-node-path, failure tab в publish-pr-comment. Гипотеза без проверки: PATH фикстуры finalize-triage-parse не содержит git из mingw64.

BLOCKERS: задания по PR #19 и #20 пришли из сеанса PM с другим идентификатором, чем ранний PM; оператор ещё не подтвердил их выполнение. Для PR #20 это живые пробы с credential.helper (учётные данные использованы будут от имени оператора) и публикация в чужой для исходного поручения PR. Нужно явное «да» оператора по каждому поручению; для запасной пробы ls-remote нужен URL приватного репозитория.
PRODUCT GAP: нет
DECLARED LIMIT: 13 падающих шагов Windows вынесены в hotfix rc.5.2 (Beads og-5l6, og-0pu), в PR #18 записаны как заявленный предел

NEXT SAFE ACTION: спросить оператора, выполнять ли PR #20 и PR #19; до ответа только git fetch и чтение. Затем PR #20, потом PR #19 (порядок просил PM).
DO NOT:
- не править репозиторий, не коммитить в клон, не пушить, не мержить;
- не запускать bd, bd-sync-export, bd-sync-restore;
- не запускать git credential fill, не печатать токены и переменные окружения целиком;
- не ставить PYTHONUTF8 и PYTHONIOENCODING в основных прогонах (применять только для явной классификации);
- не писать в отчёте дословное имя Python-теста хука проверки готовности PR (фильтр publisher принимает его за декларацию): описывать словами; не использовать слова «CODE REVIEW», «Внутреннее ревью», «review-pass», «Внешнее ревью», колонки «Статус»/«Beads ID» и фразы готовности к merge;
- не обходить отказ publisher: остановиться и сообщить текст ошибки (вывод publisher в cp1251, читать через iconv -f cp1251 -t utf-8);
- не использовать WSL; не считать этот snapshot авторитетным источником, сверять SHA с PR.
