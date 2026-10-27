#!/usr/bin/env python3
"""Детерминированно извлечь trusted bootstrap: PR_NUMBER OUTPUT.

Запуск готового файла: OG159_BODY_FILE=<проверенное тело> OG159_BODY_SHA256=<attested digest> bash <OUTPUT>.
Извлекатель не обращается к сети и не принимает иной source blob.
"""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess

SOURCE_BLOB = 'b7e7ed132df17643ebf5b2d52af0b284ba3ce93e'
TRUSTED_COMMIT = 'b830d5ed7ed31e597b45f7f3c18b8fb6baad6b29'
CLOSURE = (
    '.claude/tools/with-timeout.sh',
    '.claude/tools/run-python.sh',
    '.claude/tools/publish-pr-comment.py',
    '.claude/hooks/readiness_policy.py',
    'scripts/lib/bd-env.sh',
    'scripts/bd-wt.sh',
    'scripts/bd-read.sh',
    'scripts/lib/bd-read-engine.mjs',
)

# Capture зафиксирован здесь: его байты не зависят от candidate script или BODY_FILE.
CAPTURE = 'MODE=--publish\nBODY_FILE="${OG159_BODY_FILE-}"\nWORK_TREE="$PREFLIGHT_REPO_ROOT"\nif [ "$MODE" = "--publish" ]; then\n  if [ ! -f "$BODY_FILE" ] || [ -L "$BODY_FILE" ]; then\n    echo "СТОП: BODY_FILE должен быть regular file, не symlink." >&2\n    exit 1\n  fi\n  mkdir -p "$WORK_TREE/.overgate-runtime"\n  body_runtime_rc=$?\n  if [ "$body_runtime_rc" -ne 0 ]; then\n    echo "СТОП: каталог snapshot не создан — отказ mkdir." >&2\n    exit 1\n  fi\n  BODY_PRIVATE_DIR=$(\n    umask 077\n    mktemp -d "$WORK_TREE/.overgate-runtime/finalize.XXXXXX"\n  )\n  body_private_rc=$?\n  if [ "$body_private_rc" -ne 0 ] || [ -z "$BODY_PRIVATE_DIR" ]; then\n    echo "СТОП: private каталог snapshot не создан — отказ mktemp." >&2\n    exit 1\n  fi\n  # Ошибка очистки не отменяет публикацию и не должна превращаться в успешный выход гейта.\n  cleanup_body_snapshot() {\n    local body_gate_rc="$1"\n    rm -rf "$BODY_PRIVATE_DIR"\n    body_cleanup_rc=$?\n    if [ "$body_cleanup_rc" -ne 0 ]; then\n      echo "СТОП: private snapshot не удалён — rm завершился с кодом ${body_cleanup_rc} ($BODY_PRIVATE_DIR)." >&2\n      exit 1\n    fi\n    exit "$body_gate_rc"\n  }\n  trap \'cleanup_body_snapshot "$?"\' EXIT\n  BODY_SNAPSHOT="$BODY_PRIVATE_DIR/body"\n  (\n    umask 077\n    run_with_timeout 10 cp "$BODY_FILE" "$BODY_SNAPSHOT"\n  )\n  body_capture_rc=$?\n  if [ "$body_capture_rc" -ne 0 ]; then\n    echo "СТОП: capture BODY_FILE не выполнен — cp/timeout завершился с кодом ${body_capture_rc}." >&2\n    exit 1\n  fi\n  chmod 600 "$BODY_SNAPSHOT"\n  body_mode_rc=$?\n  if [ "$body_mode_rc" -ne 0 ] || [ ! -s "$BODY_SNAPSHOT" ]; then\n    echo "СТОП: snapshot пуст или private mode не установлен." >&2\n    exit 1\n  fi\n  BODY_HEADER=$(head -n 1 "$BODY_SNAPSHOT")\n  body_header_rc=$?\n  if [ "$body_header_rc" -ne 0 ] || [ "$BODY_HEADER" != "## ✅ Готов к merge" ]; then\n    echo "СТОП: snapshot не содержит заголовок readiness первой строкой." >&2\n    exit 1\n  fi\n  grep -Fx \'Unresolved findings: 0\' "$BODY_SNAPSHOT" >/dev/null\n  body_unresolved_rc=$?\n  if [ "$body_unresolved_rc" -ne 0 ]; then\n    echo "СТОП: snapshot не содержит Unresolved findings: 0 или отказ grep." >&2\n    exit 1\n  fi\nfi\n'
DIGEST_CHECK = r'''BOOTSTRAP_BODY_SHA=$(run_with_timeout 10 "$PREFLIGHT_REPO_ROOT/.claude/tools/run-python.sh" -I -c '
import hashlib, os, pathlib, re, sys
expected = os.environ.get("OG159_BODY_SHA256", "")
if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
    print("СТОП: OG159_BODY_SHA256 отсутствует или не содержит ровно 64 lowercase hex.", file=sys.stderr)
    sys.exit(2)
actual = hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()
if actual != expected:
    print("СТОП: digest snapshot не совпадает с предоставленным attested digest.", file=sys.stderr)
    sys.exit(3)
print(actual)
' "$BODY_SNAPSHOT")
bootstrap_body_sha_rc=$?
if [ "$bootstrap_body_sha_rc" -ne 0 ] || [ -z "$BOOTSTRAP_BODY_SHA" ]; then
  echo "СТОП: digest snapshot не подтверждён — runtime digest/Python launcher/timeout (код ${bootstrap_body_sha_rc})." >&2
  exit 1
fi
'''

def extract(pr_number):
    source = subprocess.check_output(['git', 'cat-file', 'blob', SOURCE_BLOB])
    # Проверяется identity самого объекта, а не только наличие ожидаемых строк.
    identity = hashlib.sha1(b'blob ' + str(len(source)).encode() + b'\0' + source).hexdigest()
    if identity != SOURCE_BLOB:
        raise ValueError('source blob identity mismatch')
    lines = source.decode('utf-8').splitlines(keepends=True)
    def block(number):
        if lines[number - 1] != '```bash\n':
            raise ValueError('frozen fence mismatch: ' + str(number))
        return ''.join(lines[number:lines.index('```\n', number)])
    closure = '#!/usr/bin/env bash\n# До сети сверяются HEAD blobs всего trusted closure.\n'
    for name in CLOSURE:
        closure += f'''CLOSURE_HEAD=$(git rev-parse 'HEAD:{name}')
closure_head_rc=$?
if [ "$closure_head_rc" -ne 0 ] || [ -z "$CLOSURE_HEAD" ]; then
  echo "СТОП: HEAD closure blob не прочитан: {name}." >&2
  exit 1
fi
CLOSURE_TRUSTED=$(git rev-parse '{TRUSTED_COMMIT}:{name}')
closure_trusted_rc=$?
if [ "$closure_trusted_rc" -ne 0 ] || [ -z "$CLOSURE_TRUSTED" ] || [ "$CLOSURE_HEAD" != "$CLOSURE_TRUSTED" ]; then
  echo "СТОП: trusted closure mismatch: {name}." >&2
  exit 1
fi
'''
    publication = block(2041)
    publication = publication[publication.index('REPO_ROOT=$(git rev-parse --show-toplevel)'):]
    if publication.count('<<< "$BODY"') != 1:
        raise ValueError('frozen publication mismatch')
    publication = publication.replace('<<< "$BODY"', '< "$BODY_SNAPSHOT"')
    result = closure + block(57) + CAPTURE + DIGEST_CHECK
    result += ''.join(block(n) for n in (187, 215, 243, 512, 1946)) + publication
    # Колляция должна различать русские ключи; нормализуется только этот процесс.
    locale_target = 'TRIAGE_ROWS=$(awk'
    if result.count(locale_target) != 1:
        raise ValueError('frozen triage locale target must occur exactly once')
    result = result.replace(locale_target, 'TRIAGE_ROWS=$(LC_ALL=C awk', 1)
    return result.replace('<PR_NUMBER>', pr_number).encode('utf-8')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pr_number')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9]+', args.pr_number):
        parser.error('PR_NUMBER: digits only')
    try:
        result = extract(args.pr_number)
        args.output.write_bytes(result)
        args.output.chmod(0o700)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, 'СТОП: bootstrap extraction failed: ' + str(error) + '\n')
    print(hashlib.sha256(result).hexdigest())

if __name__ == '__main__':
    main()
