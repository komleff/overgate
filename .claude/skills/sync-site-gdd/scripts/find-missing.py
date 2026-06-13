#!/usr/bin/env python3
"""find-missing.py — поиск ГД-релевантных документов, отсутствующих в manifest сайта.

⚙️ EXAMPLE (U2-специфичный). Конфигурационные константы ниже
(DEFAULT_MANIFEST, GDD_RELEVANT_DIRS, EXCLUDE_* и т.п.) — пример из U2 doc-структуры
(docs.u2game.space). В другом проекте без публичного сайта этот скилл удаляется
вместе с sync-site-gdd; иначе — адаптируй каталоги/manifest-путь под свою структуру docs/.

Использование:
    python scripts/find-missing.py [--manifest PATH] [--repo PATH]

По умолчанию:
    --manifest <SITE_MANIFEST>  (EXAMPLE: docs/gdd/site/content/manifest.json)
    --repo     . (текущий каталог = корень репозитория)

Вывод (stdout): список путей-кандидатов относительно docs/, по одному на строку,
с короткой меткой раздела (по эвристике). Пустой вывод = всё актуально.

Эвристика классификации совпадает с таблицей в SKILL.md §«Куда какой документ идёт».
Скилл всё равно должен прочитать frontmatter каждого кандидата и подтвердить
раздел перед записью в manifest — скрипт даёт только первичный отбор.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# EXAMPLE-константа (U2): путь к manifest по умолчанию. Адаптируй под свой проект
# или передавай явно через --manifest.
DEFAULT_MANIFEST = "docs/gdd/site/content/manifest.json"

# EXAMPLE (U2): каталоги, чьё содержимое в принципе кандидаты на публичный сайт.
# Hint раздела — slug из manifest.json (см. <SITE_MANIFEST>).
# Для путей с неоднозначной классификацией возвращается "?ambiguous" —
# скилл обязан подтвердить раздел через frontmatter и/или AskUserQuestion.
GDD_RELEVANT_DIRS = {
    "architecture/": "architecture",
    "brand/": "brand",
    "gdd/": "?ambiguous",       # gdd_overview → vision; gdd_monetization → economy; решает скилл
    "pve/": "pve",
    "marketing/": "vision",
    "specs/audit/": "audit",
    "specs/gameplay/": "gameplay-systems",
    "specs/fa/": "gameplay-systems",
    "specs/ui/": "ui-ux",
    "specs/economy/": "economy",
}

# Каталоги-исключения внутри ГД-релевантных (служебное / технические).
EXCLUDE_DIRS = {
    "archive/",      # архив — отдельное решение оператора
    "incidents/",
    "plans/",
    "research/",
    "specs/tech/",
    "specs/network/",
    "gdd/site/",     # сам сайт в себя не добавляется
}

# Префиксы имён файлов, которые исключаются как служебные/инфраструктурные.
# Шаблон `gdd_site_*` покрывает creation/deploy/maintenance/plan для сайта —
# это руководства для операторов и агентов, не публичный GDD-контент.
EXCLUDE_FILENAME_PREFIXES = (
    "gdd_site_",
)

# Файлы-исключения (индексы, шаблоны, README).
EXCLUDE_FILENAMES = {
    "ADR-INDEX.md",
    "ADR-TEMPLATE.md",
    "ADR-INDEX-ADDENDUM-2026-05-22.md",  # исторический след по решению оператора
    "ARCHIVE.md",
    "INDEX.md",
    "README.md",
    "STYLE.md",
}


def section_for(path: str) -> str:
    """Hint раздела по пути относительно docs/.

    Возвращает slug раздела из manifest.json, либо "?ambiguous" если каталог
    содержит документы из нескольких разделов — скилл обязан подтвердить выбор
    через frontmatter и/или AskUserQuestion к оператору.
    """
    for prefix, section in GDD_RELEVANT_DIRS.items():
        if path.startswith(prefix):
            return section
    return "?"


def is_excluded(rel_path: str) -> bool:
    """True если файл явно не идёт на сайт."""
    if any(rel_path.startswith(ex) for ex in EXCLUDE_DIRS):
        return True
    filename = rel_path.rsplit("/", 1)[-1]
    if filename in EXCLUDE_FILENAMES:
        return True
    if filename.startswith(EXCLUDE_FILENAME_PREFIXES):
        return True
    if not filename.endswith(".md"):
        return True
    return False


def collect_candidates(docs_root: Path) -> list[str]:
    """Все ГД-релевантные .md под docs/, относительные пути от docs/."""
    candidates = []
    for prefix in GDD_RELEVANT_DIRS:
        base = docs_root / prefix
        if not base.exists():
            continue
        for md in base.rglob("*.md"):
            rel = md.relative_to(docs_root).as_posix()
            if is_excluded(rel):
                continue
            candidates.append(rel)
    return sorted(candidates)


def collect_manifest_sources(manifest_path: Path) -> set[str]:
    """Все source-пути из manifest (относительные docs/)."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = set()
    for section in data.get("sections", []):
        for item in section.get("items", []):
            src = item.get("source")
            if src:
                sources.add(src)
        # Кураторская страница раздела не считается источником в смысле manifest items.
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    docs_root = repo / "docs"
    manifest_path = repo / args.manifest

    if not docs_root.is_dir():
        print(f"ОШИБКА: docs/ не найден относительно {repo}", file=sys.stderr)
        return 2
    if not manifest_path.is_file():
        print(f"ОШИБКА: manifest не найден: {manifest_path}", file=sys.stderr)
        return 2

    candidates = collect_candidates(docs_root)
    in_manifest = collect_manifest_sources(manifest_path)

    missing = [c for c in candidates if c not in in_manifest]

    if not missing:
        print("# Пропусков нет — все ГД-релевантные документы учтены в manifest.", file=sys.stderr)
        return 0

    print(f"# Найдено {len(missing)} пропусков. Раздел — первичная эвристика, скилл подтверждает по frontmatter.", file=sys.stderr)
    print(f"# Формат: <section_hint>\\t<path>", file=sys.stderr)
    for path in missing:
        print(f"{section_for(path)}\t{path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
