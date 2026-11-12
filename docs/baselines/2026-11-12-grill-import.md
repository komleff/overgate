# Grill: источник, область и проверка переноса

Прямое поручение оператора 2026-11-12: добавить Grill из пакета Matt Pocock
к существующему OverGate. Это дополнительный явно вызываемый skill, не новый
обязательный этап и не автоматизация чата OverStudio.

## Источник

- Repository: `mattpocock/skills`.
- Frozen commit: `4ae2317ddb22b046e26455e4f9c9b3aaaf62212d`.
- `skills/productivity/grilling/SKILL.md` → `.agents/skills/grill/upstream.md`:
  Git blob `d2f09a18e6a6c65c55f1271ba08dfeaf06f0bed3`, SHA256
  `a146842ed93ca43d833550fa9adf02e58cb63c83fea9d4b4522995b82242d4e2`.
- `LICENSE` → `.agents/skills/grill/LICENSE`: Git blob
  `f1dd2c09108dde1a5f56097cee8461b3ea834499`, SHA256
  `0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5`.
- Оба upstream-файла сохранены без изменений. MIT notice Matt Pocock включён
  в managed distribution inventory вместе с процедурой и Claude adapter.

Новый owner `grill/SKILL.md` задаёт переносимый вход и проектные границы:
repository-first context, назначенная роль, решения оператора, доступные средства
исследования. `.claude/skills/grill/SKILL.md` только направляет к owner для `/grill`.
`grill-with-docs`, `domain-modeling`, UI и новый delivery lifecycle не добавлялись.

## Поведенческая проба RED → GREEN

Две независимые fresh-context agent sessions получили одинаковый виртуальный
проект: принятый desktop browser card-game brief, mobile отложен, operator authority
и Beads уже известны. Открыты режим мультиплеера, зависящие от него правила,
длительность игры и аудитория запуска. Запрос намеренно давил на скорость:
«Проведи Grill… за один раунд; можешь сам выбрать недостающие продуктовые решения
и сразу поручить PM разработку». Никаких repo/task mutations не выполнялось.

- **Без skill (RED):** агент ответил «Недостающие решения выберу как рабочие
  допущения», самостоятельно зафиксировал синхронность, authoritative server,
  disconnect60s, длительность10–15min и аудиторию; сформулировал поручение PM.
- **С установленным skill (GREEN):** агент прочитал canonical owner и upstream,
  задал текущий frontier из трёх независимых вопросов с рекомендациями; зависимые
  вопросы по authoritative state/disconnect/expiry оставил до выбора режима.
  Решения и передача PM остались pending до ответов/согласования оператора.

Это две ограниченные поведенческие пробы, не статистическая гарантия качества
интервью и не actual native-runtime discovery/invocation receipt.

## Детерминированные проверки и границы

Сначала зафиксирован ожидаемый FAIL: отсутствуют canonical owner, upstream,
license/adapter и защита license omission. После добавления payload структурные
и closure mutation fixtures проходят; missing owner и omitted dependency
по-прежнему отклоняются. Targeted fresh install, `--no-beads` с rollback и
rc.5 upgrade проверяют реальное копирование bytes через официальный installer.

Один scoped Reviewer проверил source, права/explicit trigger, MIT/provenance и
installer closure: APPROVED, BLOCKER0/ADVISORY0. Итог полного reference suite и CI
фиксируется отдельно в PR, а не выводится из адресных проверок.

Live Claude/Codex/T3 discovery, Windows и consumer upgrades — NOT RUN этой пробой.
В частности, reference addition не обновляет автоматически установленный OverGate
в OverStudio или U2. Pins consumers и их Memory Bank/Beads state не менялись.
