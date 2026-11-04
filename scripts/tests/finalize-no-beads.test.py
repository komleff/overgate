#!/usr/bin/env python3
"""AC11: выполняется настоящий triage parser, data и code в разных деревьях."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent/'lib'))
from claude_hooks import native_bash
ROOT=Path(__file__).resolve().parents[2]
BASH=native_bash()
class TrackerTriage(unittest.TestCase):
    def test_issue_forms_and_fail_closed(self):
        source=(ROOT/'.claude/skills/finalize-pr/finalize-gate.sh').read_text(encoding='utf-8')
        start=source.index('SEP=$(printf');tail=source.index('if [ "$TRIAGE_FAILED" = "1" ]; then',start)
        block=source[start:source.index('\nfi',tail)+3]
        a=block.index('# triage-fetch:start');b=block.index('# triage-fetch:end',a)
        block=block[:a]+block[b+len('# triage-fetch:end'):]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);work=root/'work';work.mkdir();(work/'.overgate').mkdir()
            code=root/'trusted';(code/'.claude/tools').mkdir(parents=True)
            import shutil
            shutil.copy2(ROOT/'.claude/tools/run-python.sh',code/'.claude/tools/run-python.sh')
            env=dict(os.environ)
            shell=root/'run.sh'
            # Функция gh не вызывает сеть, но actual shell validation/parsing идёт без подмены.
            stub='''
gh() {
  printf '%s\\n' "$*" >> "$CALLS"
  case "$1 $2" in
    "pr view") printf '{"url":"https://github.com/example/project/pull/12"}' ;;
    "issue view")
      case "$3" in
        404) return 1 ;;
        8) printf '{"url":"https://github.com/example/project/issues/8","state":"CLOSED","number":8,"__typename":"Issue"}' ;;
        9) printf '{"url":"https://github.com/example/project/pull/9","state":"OPEN","number":9,"__typename":"PullRequest"}' ;;
        *) printf '{"url":"https://github.com/example/project/issues/7","state":"OPEN","number":7,"__typename":"Issue"}' ;;
      esac ;;
    *) return 12 ;;
  esac
}
run_with_timeout() { shift; "$@"; }
'''
            cases=[('#7',False,True),('https://github.com/example/project/issues/7',False,True),('#0',False,False),('#abc',False,False),('-1',False,False),('--help',False,False),('https://github.com/other/project/issues/7',False,False),('https://github.com/example/project/pull/7',False,False),('#404',False,False),('#8',False,False),('#9',False,False),('',False,False),('#7',True,False),('#7','missing',False),('#7','broken',False),('#7',False,False,'missing-gh')]
            for entry in cases:
                value,state,wanted=entry[:3];missing_gh=len(entry)>3
                with self.subTest(value=value,state=state,missing_gh=missing_gh):
                    statepath=work/'.overgate/install-state.json';statepath.unlink(missing_ok=True)
                    if state=='broken':statepath.write_text('{')
                    elif state!='missing':statepath.write_text(json.dumps({'beads':state}))
                    body='| # | Severity | Finding | Status | Beads ID / Rationale |\n|---|---|---|---|---|\n| 1 | WARNING | x | defer to Beads | '+value+' |\n'
                    setup='set -u\nGATE_TREE='+shlex.quote(code.as_posix())+'\nWORK_TREE='+shlex.quote(work.as_posix())+'\nPR_NUMBER=12\nHEAD_COMMIT=deadbeef\nCALLS='+shlex.quote((root/'calls').as_posix())+'\nREVIEW_BODIES='+shlex.quote(body)+'\n'
                    shell.write_text(setup+stub+('\nunset -f gh\ngh() { return 127; }\n' if missing_gh else '')+block+'\n',encoding='utf-8')
                    run=subprocess.run([BASH,str(shell)],cwd=work,env=env,capture_output=True,text=True,encoding='utf-8')
                    self.assertEqual(run.returncode==0,wanted,run.stdout+run.stderr)
if __name__=='__main__':unittest.main()
