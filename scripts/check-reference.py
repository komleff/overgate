#!/usr/bin/env python3
"""Проверка generic owner/skill closure; U2 product checks сюда не входят."""
import argparse
from collections import Counter
import re
from pathlib import Path

SKILLS = {'canon-router', 'product-gap', 'product-handoff', 'diagnose', 'handoff'}
ROLES = {'PM', 'SV', 'PL', 'DEV', 'QA', 'RV'}
ADAPTERS = {'developer': 'DEV', 'planner': 'PL', 'reviewer': 'RV', 'tester': 'QA'}


def check(root):
    errors = []
    def fail(code, message):
        errors.append(f'{code}: {message}')
    def read(path, code):
        p = root / path
        if not p.is_file() or p.is_symlink():
            fail(code, f'missing/unsafe owner: {path}')
            return ''
        return p.read_text(encoding='utf-8')
    registry = read('.agents/AGENT_ROLES.md', 'ROLE-001')
    for role in sorted(ROLES):
        path = f'.agents/{role}_ROLE.md'
        read(path, 'ROLE-001')
        if path not in registry:
            fail('ROLE-002', f'unregistered role: {path}')
    for adapter, role in ADAPTERS.items():
        body = read(f'.claude/agents/{adapter}.md', 'ROLE-003')
        pointers = re.findall(r'\.agents/[A-Z]+_ROLE\.md', body)
        if not pointers or any(p != f'.agents/{role}_ROLE.md' or not (root / p).is_file() for p in pointers):
            fail('ROLE-003', f'unresolved/wrong role pointer: {adapter}')
    registry = read('.agents/SKILLS.md', 'SKILL-001')
    entries = re.findall(r'^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`', registry, re.M)
    counts = Counter(name for name, path in entries)
    if set(counts) != SKILLS:
        fail('SKILL-001', 'registry membership must be exactly five generic skills')
    if any(count != 1 for count in counts.values()):
        fail('SKILL-005', 'duplicate registry membership')
    expected = {f'.agents/skills/{name}/SKILL.md' for name in SKILLS}
    for name, path in entries:
        if path != f'.agents/skills/{name}/SKILL.md' or path not in expected:
            fail('SKILL-002', f'dangling/noncanonical registry path: {path}')
        read(path, 'SKILL-002')
    actual = {p.relative_to(root).as_posix() for p in (root / '.agents/skills').rglob('SKILL.md')}
    for path in sorted(actual - expected):
        fail('SKILL-004' if len(Path(path).parts) != 4 else 'SKILL-003', f'nested/orphan skill: {path}')
    for path in sorted(expected - actual):
        fail('SKILL-002', f'missing skill owner: {path}')
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--structure-only', action='store_true')
    args = parser.parse_args()
    errors = check(args.root.resolve())
    for error in errors:
        print(error)
    print(f'reference structure: {"FAIL" if errors else "PASS"}')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
