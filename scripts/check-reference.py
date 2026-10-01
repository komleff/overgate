#!/usr/bin/env python3
"""Проверка generic owner/skill closure; U2 product checks сюда не входят."""
import argparse
from collections import Counter
import json
import re
from pathlib import Path

SKILLS = {'canon-router', 'product-gap', 'product-handoff', 'diagnose', 'handoff'}
ROLES = {'PM', 'SV', 'PL', 'DEV', 'QA', 'RV'}
ADAPTERS = {'developer': 'DEV', 'planner': 'PL', 'reviewer': 'RV', 'tester': 'QA'}
RUNTIME = {
    '.claude/hooks/' + name for name in (
        'check-repository-mutation.py', 'check-tests-before-commit.sh', 'check-merge-ready.py',
        'commit_command_classifier.py', 'shell_grammar.py', 'shell_comment_parser.py', 'readiness_policy.py')
} | {'.claude/tools/' + name for name in ('run-python.sh', 'with-timeout.sh', 'publish-pr-comment.py')} | {
    '.claude/settings.json', '.codex/hooks.json', 'scripts/bd-read.sh', 'scripts/bd-wt.sh',
    'scripts/lib/bd-env.sh', 'scripts/lib/bd-read-engine.mjs', '.agents/project/verify.sh',
    'scripts/install-overgate.py', 'scripts/check-reference.py'}


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
    if {p.name for p in (root / '.agents').glob('*_ROLE.md')} != {r + '_ROLE.md' for r in ROLES}:
        fail('ROLE-002', 'delivery owner set must be exactly PM/SV/PL/DEV/QA/RV')
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


def closure(root):
    errors = []
    try:
        manifest = json.loads((root / '.agents/distribution-manifest.json').read_text())
        entries = manifest['files']
        targets = [x['target'] for x in entries]
        if len(targets) != len(set(targets)) or not RUNTIME <= set(targets):
            errors.append('CLOSURE-001: missing/duplicate runtime inventory')
        for entry in entries:
            path = root / entry['target']
            if not path.is_file() or path.is_symlink():
                errors.append('CLOSURE-002: missing dependency: ' + entry['target'])
            elif entry['target'].endswith('.sh') and entry['policy'] != 'preserve' and not path.stat().st_mode & 0o111:
                errors.append('CLOSURE-003: helper is not executable: ' + entry['target'])
        for config in ('.claude/settings.json', '.codex/hooks.json'):
            settings = json.loads((root / config).read_text())
            entries = settings['hooks']['PreToolUse']
            for handler in ('check-repository-mutation.py', 'check-tests-before-commit.sh', 'check-merge-ready.py'):
                if not any(re.fullmatch(e['matcher'], 'Bash') and handler in json.dumps(e['hooks']) for e in entries):
                    errors.append(f'CLOSURE-004: missing whole-Bash adapter: {config}: {handler}')
    except (OSError, ValueError, KeyError, TypeError) as error:
        errors.append('CLOSURE-001: invalid/missing manifest or adapter: ' + str(error))
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--structure-only', action='store_true')
    args = parser.parse_args()
    errors = check(args.root.resolve())
    if not args.structure_only:
        errors += closure(args.root.resolve())
    for error in errors:
        print(error)
    print(f'reference structure: {"FAIL" if errors else "PASS"}')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
