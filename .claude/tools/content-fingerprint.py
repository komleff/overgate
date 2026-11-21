#!/usr/bin/env python3
"""Состав reviewed package из машинных Git records, без display quoting/fallback."""
import argparse
from hashlib import sha256
import json
import re
import subprocess
import sys


def package(base, head):
    if base.startswith('-') or head.startswith('-'):
        raise ValueError('revision не может быть опцией Git')
    result = subprocess.run(['git', 'diff', '--raw', '--no-abbrev', '-z', '--no-color',
        '--no-ext-diff', '--no-textconv', base + '...' + head], check=True, stdout=subprocess.PIPE)
    parts = result.stdout.split(b'\0')
    if result.stdout and not result.stdout.endswith(b'\0'):
        raise ValueError('оборванный Git raw output')
    records = []
    cursor = 0
    while cursor < len(parts) - 1:
        header = parts[cursor].split()
        cursor += 1
        if (len(header) != 5 or not header[0].startswith(b':')
                or not re.fullmatch(b'[0-9a-f]{40,64}', header[3])):
            raise ValueError('невалидный Git raw record')
        status = header[4][:1]
        if status not in (b'A', b'M', b'D', b'T', b'R', b'C'):
            raise ValueError('неподдержанный Git status')
        if status in (b'R', b'C'):
            cursor += 1
        if cursor >= len(parts) - 1:
            raise ValueError('оборванный Git path record')
        path = parts[cursor]
        cursor += 1
        if not path or b'\n' in path or b'\r' in path:
            raise ValueError('line-based fingerprint не поддерживает CR/LF в имени файла')
        blob = b'DELETED' if status == b'D' else header[3]
        if status != b'D' and not blob.strip(b'0'):
            raise ValueError('Git не вернул blob ID существующего пути')
        records.append((path, blob))
    return b''.join(path + b' ' + blob + b'\n' for path, blob in sorted(records))


def contract_bytes(metadata):
    body = metadata.get('body') if isinstance(metadata, dict) else None
    if not isinstance(body, str):
        raise ValueError('body PR должен быть строкой')
    lines = body.replace('\r\n', '\n').split('\n')
    begins = [i for i, line in enumerate(lines) if line == '<!-- CONTRACT-BEGIN -->']
    ends = [i for i, line in enumerate(lines) if line == '<!-- CONTRACT-END -->']
    if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
        raise ValueError('Нужна одна упорядоченная пара CONTRACT-BEGIN/CONTRACT-END')
    contract = '\n'.join(lines[begins[0] + 1:ends[0]]) + '\n'
    if not contract.strip():
        raise ValueError('Контракт PR пуст')
    return contract.encode('utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--package', nargs=2, metavar=('BASE', 'HEAD'))
    modes.add_argument('--content-digest', nargs=2, metavar=('BASE', 'HEAD'))
    modes.add_argument('--contract-digest', action='store_true')
    args = parser.parse_args()
    try:
        if args.package:
            result = package(*args.package)
        else:
            contract = contract_bytes(json.load(sys.stdin.buffer))
            payload = package(*args.content_digest) + contract if args.content_digest else contract
            result = (sha256(payload).hexdigest() + '\n').encode('ascii')
        sys.stdout.buffer.write(result)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('FINGERPRINT FAILED: ' + str(error), file=sys.stderr)
        sys.exit(1)
