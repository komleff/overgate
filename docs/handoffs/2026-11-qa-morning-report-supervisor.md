# Утренний отчёт QA (Windows native) — для Супервизора

Роль: QA, Claude Sonnet 5.5. Клон: C:/work/og-pr18-qa (сейчас detached на b04b21c). В репозитории ничего не правила, не коммитила, не пушила.

## Сделано
| PR / задача | Коммит | Итог | Где отчёт |
|---|---|---|---|
| PR #18, commit tier (AC-08) | fafdf67 | FAIL: шаг activation, UnicodeDecodeError cp1251 (read_text без encoding), 162.9 с до падения | комментарий в PR #18 |
| PR #18, повтор после фикса | 854a840 | FAIL: activation теперь PASS, упал mutation-guard (201 pass, 3 fail), 217.7 с до падения | комментарий в PR #18 (issuecomment-6745950771) |
| PR #18, пошагово | 854a840 | 27 шагов: 14 PASS, 13 FAIL | issuecomment-6746529872 |
| PR #18, шаги B, C, D | fafdf67 | B PASS, C PASS (4 теста, 1m43s), D PASS по тексту; меню Проводника не проверено | в первом отчёте |
| og-0pu, диагностика причин | b04b21c | опубликована | issuecomment-6748402588 |

PR #18 влит оператором; 13 падающих шагов вынесены в отдельный hotfix rc.5.2 (Beads og-5l6, og-0pu).

## Установленные причины (Windows)
- Python `subprocess` по имени `bash` запускает System32\bash.exe (заглушка WSL), а не Git Bash: commit-gate.test.py падает 9 из 9.
- Кодировка cp1251: объясняет только 2 шага из 10 (хук-тест и merge-gate-parse-budget); остальные падают и с PYTHONUTF8=1.
- Нет права на symlink (WinError 1314, ln: Permission denied): publish-pr-comment (error) и, вероятно, with-timeout.
- Не установлены: mutation-guard (3 кейса), module-resolution-closure, пустой замер в with-timeout-transparency, bd-node-path, failure tab в publish-pr-comment. Гипотеза без проверки: PATH фикстуры finalize-triage-parse не содержит git из mingw64.

## Ожидает решения оператора (НЕ выполнено)
- Поручение PM по PR #20 (og-4py, B-08): живые пробы push-dry-run с credential.helper и комментарий в PR #20.
- Поручение PM по PR #19 (rc.5.2, b16128d): двойной verify.sh, mutation-guard, 22 шага full-уровня, publisher-тест, пробный коммит в одноразовом клоне, комментарий в PR #19.
Причина паузы: оба выходят за исходное поручение (PR #18), одно использует учётные данные. Запрошены решения оператора.

## Замечания
- Поручения по #20 и #19 пришли от сеанса с другим идентификатором, чем ранний PM; ссылку на og-0pu этому сеансу отправить не удалось (SendMessage вернул ошибку).
- Publisher отклонил один отчёт из-за имени файла хук-теста (ложное срабатывание фильтра готовности); имя заменено описанием с разрешения оператора.

## Not tested
Проводник Windows 10/11 (оператору), полное время commit tier до PASS, WSL, Windows 10, живые пробы PR #20 и приёмка PR #19.
