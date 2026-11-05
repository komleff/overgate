#!/usr/bin/env python3
"""Old OverGate writer routes stop before native Beads work when a clone is fenced."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
FILES=('bd-wt.sh','bd-sync-common.sh','bd-sync-export.sh','bd-sync-restore.sh','bd-bootstrap.sh')

def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL).decode().strip()

class LegacyFence(unittest.TestCase):
    def test_each_old_writer_refuses_before_bd_or_remote_write(self):
        for script,args in (('bd-wt.sh',['update','legacy-a','--claim']),
                            ('bd-sync-export.sh',[]),('bd-sync-restore.sh',[]),('bd-bootstrap.sh',[])):
            with self.subTest(script=script), tempfile.TemporaryDirectory(prefix='overgate-legacy-fence-') as holder:
                base=Path(holder).resolve();target=base/'target';remote=base/'remote.git';target.mkdir()
                git(target,'init','-q','-b','main');git(target,'config','user.name','fixture')
                git(target,'config','user.email','fixture@example.invalid')
                git(base,'init','-q','--bare',remote);git(target,'remote','add','origin',remote)
                (target/'README.md').write_text('fixture\n')
                git(target,'add','README.md');git(target,'commit','-qm','fixture main')
                git(target,'push','-q','origin','main');git(remote,'symbolic-ref','HEAD','refs/heads/main')
                (target/'scripts/lib').mkdir(parents=True)
                for name in FILES:shutil.copy2(ROOT/'scripts'/name,target/'scripts'/name)
                shutil.copy2(ROOT/'scripts/lib/bd-env.sh',target/'scripts/lib/bd-env.sh')
                (target/'.claude/tools').mkdir(parents=True)
                shutil.copy2(ROOT/'.claude/tools/run-python.sh',target/'.claude/tools/run-python.sh')
                git(target,'config','--local','overgate.beadsLegacyFence','a'*64)
                log=base/'bd-calls';binary=base/'bd'
                binary.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$BD_LOG"\nexit 0\n')
                binary.chmod(0o755)
                env={**os.environ,'PATH':str(base)+os.pathsep+os.environ['PATH'],'BD_BIN':str(binary),'BD_LOG':str(log)}
                before=(git(target,'rev-parse','HEAD'),(target/'.git/index').read_bytes())
                result=subprocess.run(['bash','scripts/'+script,*args],cwd=target,env=env,
                                      capture_output=True,text=True,timeout=45)
                self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('legacy writer fenced',result.stderr)
                self.assertFalse(log.exists(),'native bd must not run after fence')
                self.assertEqual((git(target,'rev-parse','HEAD'),(target/'.git/index').read_bytes()),before)
                self.assertEqual(git(target,'ls-remote','--heads','origin','refs/heads/beads-backup'),'')

if __name__=='__main__':unittest.main()
