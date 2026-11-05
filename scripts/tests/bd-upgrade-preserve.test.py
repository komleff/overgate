#!/usr/bin/env python3
"""Disposable native legacy packet; no project or shared Beads database is opened."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
BINARY=Path('/opt/homebrew/bin/bd').resolve()
MAC_SHA='cd6827a3b3ec5b212131337201df1e623e028bce15065903fb70291e0ac4a355'
ACTOR='agent-2ad0342a-81a5-4cb8-bd17-3f38b279f2f2'

def run(args,cwd,env=None):
    result=subprocess.run([str(item) for item in args],cwd=cwd,env=env,capture_output=True,text=True,timeout=90)
    if result.returncode:raise AssertionError(f'{args[:3]} failed: {result.stderr[-700:]}')
    return result.stdout.strip()

def git(root,*args):return run(['git','-C',root,*args],root)

class PreserveTests(unittest.TestCase):
    def test_native_two_writer_clean_packet_and_pending_negative(self):
        if sys.platform!='darwin' or not BINARY.is_file() or hashlib.sha256(BINARY.read_bytes()).hexdigest()!=MAC_SHA:
            self.skipTest('qualified native macOS bd 1.2.2 unavailable')
        with tempfile.TemporaryDirectory(prefix='overgate-upgrade-preserve-') as name:
            root=Path(name).resolve();remote=root/'remote.git';primary=root/'primary';second=root/'second';seed=root/'seed'
            git(root,'init','-q','--bare',remote)
            git(root,'init','-q','-b','main',primary)
            git(primary,'config','user.name','fixture');git(primary,'config','user.email','fixture@example.invalid')
            git(primary,'remote','add','origin',remote)
            (primary/'.overgate').mkdir()
            (primary/'.overgate/install-state.json').write_text(json.dumps({'format':2,'beads':True,'source_sha':'0'*40,
                                                                            'manifest_version':'4.0.0-rc.4','installed':{}}))
            (primary/'README.md').write_text('legacy project\n')
            helpers=('scripts/bd-wt.sh','scripts/bd-sync-common.sh','scripts/bd-sync-export.sh',
                     'scripts/bd-sync-restore.sh','scripts/bd-bootstrap.sh','scripts/lib/bd-env.sh')
            manifest=json.loads((ROOT/'.agents/distribution-manifest.json').read_bytes())
            runtime={item['source'] for item in manifest['files'] if item.get('component')=='beads'
                     and item['source'].startswith('scripts/')}
            for relative in runtime | {'scripts/install-overgate.py'}:
                file=primary/relative;file.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/relative,file)
            git(primary,'add','README.md','.overgate/install-state.json','scripts');git(primary,'commit','-qm','legacy main')
            git(primary,'push','-q','origin','main');git(remote,'symbolic-ref','HEAD','refs/heads/main')
            git(root,'clone','-q',remote,second)
            for clone in (primary,second):
                env={**os.environ,'GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_NOSYSTEM':'1',
                     'DOLT_ROOT_PATH':str(root/(clone.name+'-dolt-global')),'BD_DISABLE_METRICS':'1','DOLT_METRICS_DISABLED':'1'}
                run([BINARY,'--db',clone/'.beads/dolt','--actor',ACTOR,'init','--prefix','big-heroes',
                     '--non-interactive','--skip-agents','--skip-hooks','--stealth'],clone,env)
            env={**os.environ,'GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_NOSYSTEM':'1',
                 'DOLT_ROOT_PATH':str(root/'primary-dolt-global'),'BD_DISABLE_METRICS':'1','DOLT_METRICS_DISABLED':'1'}
            run([BINARY,'--db',primary/'.beads/dolt','--actor',ACTOR,'create','--title','Retained task','--json'],primary,env)
            snapshot=root/'legacy.jsonl'
            run([BINARY,'--db',primary/'.beads/dolt','--readonly','export','--all','-o',snapshot],primary,env)
            legacy_id=json.loads(snapshot.read_text().splitlines()[0])['id']
            run([BINARY,'--db',second/'.beads/dolt','--actor',ACTOR,'import',snapshot,'--json'],second,
                {**env,'DOLT_ROOT_PATH':str(root/'second-dolt-global')})
            git(root,'clone','-q',remote,seed)
            git(seed,'config','user.name','fixture');git(seed,'config','user.email','fixture@example.invalid')
            git(seed,'switch','-q','-c','beads-backup')
            (seed/'.beads').mkdir();(seed/'.beads/issues.jsonl').write_bytes(snapshot.read_bytes())
            git(seed,'add','.beads/issues.jsonl');git(seed,'commit','-qm','legacy snapshot')
            git(seed,'push','-q','origin','beads-backup')
            hook=primary/'.git/hooks/pre-push';hook.write_text('#!/bin/sh\nexit 0\n');hook.chmod(0o755)
            packet=root/'packet.json';cmd=[sys.executable,ROOT/'scripts/bd-upgrade-preserve.py','--target',primary,
                '--writer-root',primary,'--writer-root',second,'--bd-bin',BINARY,'--actor',ACTOR,
                '--outcome','verified-clean','--output',packet]
            divergent=root/'divergent-push.git';git(root,'clone','-q','--bare',remote,divergent)
            git(divergent,'update-ref','refs/heads/beads-backup',git(primary,'rev-parse','HEAD'))
            for clone in (primary,second):
                git(clone,'remote','set-url','--push','origin',divergent)
                git(clone,'config','--local','--add','remote.origin.pushurl',remote)
            diverged=root/'diverged.json'
            no_push=subprocess.run([str(item) for item in [*cmd[:-1],diverged]],cwd=ROOT,
                                   capture_output=True,text=True,timeout=90)
            self.assertNotEqual(no_push.returncode,0,'different push task R must stop packet before publication')
            self.assertFalse(diverged.exists())
            self.assertEqual(git(primary,'ls-remote','--heads','origin','refs/heads/beads-backup').split()[0],
                             git(seed,'rev-parse','HEAD'))
            git(divergent,'update-ref','refs/heads/beads-backup',git(seed,'rev-parse','HEAD'))
            git(divergent,'update-ref','refs/heads/main',git(seed,'rev-parse','HEAD'))
            bad_main=root/'diverged-main.json'
            no_main=subprocess.run([str(item) for item in [*cmd[:-1],bad_main]],cwd=ROOT,
                                   capture_output=True,text=True,timeout=90)
            self.assertNotEqual(no_main.returncode,0,'different push main must stop packet')
            self.assertFalse(bad_main.exists())
            for clone in (primary,second):git(clone,'config','--local','--unset-all','remote.origin.pushurl')
            head=git(primary,'rev-parse','HEAD');index=(primary/'.git/index').read_bytes()
            receipt=json.loads(run(cmd,ROOT))
            self.assertEqual(receipt['writers'],2)
            value=json.loads(packet.read_bytes())
            self.assertEqual(value['R'],git(seed,'rev-parse','HEAD'))
            self.assertEqual(value['snapshot_sha256'],hashlib.sha256(snapshot.read_bytes()).hexdigest())
            self.assertEqual(value['outcome'],'verified-clean')
            if os.name!='nt':
                self.assertEqual(packet.stat().st_mode & 0o077,0,'private packet permissions')
                self.assertEqual(Path(value['snapshot_path']).stat().st_mode & 0o077,0,'private snapshot permissions')
            self.assertEqual(git(primary,'rev-parse','HEAD'),head)
            self.assertEqual((primary/'.git/index').read_bytes(),index)
            spec=importlib.util.spec_from_file_location('installer_under_test',ROOT/'scripts/install-overgate.py')
            installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
            original_packet=packet.read_bytes();original_snapshot=Path(value['snapshot_path']).read_bytes()
            forged_rows=[json.loads(line) for line in original_snapshot.decode().splitlines()]
            forged_rows[0]['title']='Forged legacy task'
            forged_bytes=('\n'.join(json.dumps(row,ensure_ascii=False) for row in forged_rows)+'\n').encode()
            Path(value['snapshot_path']).write_bytes(forged_bytes)
            forged_value=json.loads(original_packet);forged_value['snapshot_sha256']=hashlib.sha256(forged_bytes).hexdigest()
            packet.write_bytes(installer.json_bytes(forged_value))
            with self.assertRaisesRegex(installer.InstallError,'frozen.*snapshot'):
                installer.preservation_packet(primary,installer.beads_inventory(primary),packet)
            packet.write_bytes(original_packet);Path(value['snapshot_path']).write_bytes(original_snapshot)
            hook.chmod(0o644)
            with self.assertRaisesRegex(installer.InstallError,'hook'):
                installer.preservation_packet(primary,installer.beads_inventory(primary),packet)
            hook.chmod(0o755)
            (primary/'.bd-intents').mkdir();(primary/'.bd-intents/pending.jsonl').write_text('{}\n')
            pending_packet=root/'pending-packet.json';pending_cmd=[*cmd]
            pending_cmd[pending_cmd.index('verified-clean')]='pending-retained';pending_cmd[-1]=pending_packet
            run(pending_cmd,ROOT)
            forged_pending=json.loads(pending_packet.read_bytes());forged_pending['outcome']='verified-clean'
            pending_packet.write_bytes(installer.json_bytes(forged_pending))
            with self.assertRaisesRegex(installer.InstallError,'clean outcome'):
                installer.preservation_packet(primary,installer.beads_inventory(primary),pending_packet)
            shutil.rmtree(primary/'.bd-intents')
            fence_command=[sys.executable,primary/'scripts/bd-upgrade-fence.py','--packet']
            rejected=subprocess.run([*map(str,fence_command),str(packet)],cwd=primary,capture_output=True,text=True)
            self.assertNotEqual(rejected.returncode,0)
            self.assertIn('installed legacy writer closure',rejected.stderr)
            self.assertFalse((primary/'.git/overgate-bd-legacy-fence.json').exists())
            self.assertFalse((second/'.git/overgate-bd-legacy-fence.json').exists())
            self.assertEqual(git(primary,'ls-remote','--heads','origin','refs/heads/beads-backup').split()[0],value['R'])
            state_file=primary/'.overgate/install-state.json';state=json.loads(state_file.read_bytes())
            state['beads_protocol']='legacy-v0'
            state['installed']={name:{'sha256':hashlib.sha256((primary/name).read_bytes()).hexdigest()}
                                for name in (*helpers,'scripts/bd-upgrade-fence.py','scripts/bd-upgrade-preserve.py',
                                             'scripts/install-overgate.py')}
            state_file.write_text(json.dumps(state))
            git(primary,'add','.overgate/install-state.json');git(primary,'commit','-qm','reviewed legacy helper upgrade')
            git(primary,'push','-q','origin','main');git(second,'pull','-q','--ff-only')
            packet=root/'upgraded-packet.json';cmd[-1]=packet
            value=json.loads(run(cmd,ROOT))
            frozen=json.loads(packet.read_bytes())
            spoof_push=root/'spoof-push.git';git(root,'clone','-q','--bare',remote,spoof_push)
            before_local={clone.name:installer.beads_inventory(clone) for clone in (primary,second)}
            before_git={clone.name:(git(clone,'rev-parse','HEAD'),(clone/'.git/index').read_bytes())
                        for clone in (primary,second)}
            git(primary,'remote','set-url','--push','origin',spoof_push)
            drift=subprocess.run([*map(str,fence_command),str(packet)],cwd=primary,capture_output=True,text=True)
            self.assertNotEqual(drift.returncode,0,'push destination drift must stop before fencing')
            self.assertIn('origin',drift.stderr)
            self.assertFalse((primary/'.git/overgate-bd-legacy-fence.json').exists())
            self.assertFalse((second/'.git/overgate-bd-legacy-fence.json').exists())
            self.assertEqual({clone.name:installer.beads_inventory(clone) for clone in (primary,second)},before_local)
            self.assertEqual({clone.name:(git(clone,'rev-parse','HEAD'),(clone/'.git/index').read_bytes())
                              for clone in (primary,second)},before_git)
            self.assertEqual(git(primary,'ls-remote','--heads','origin','refs/heads/beads-backup').split()[0],frozen['R'])
            git(primary,'config','--local','--unset-all','remote.origin.pushurl')
            fence=json.loads(run([*fence_command,packet],primary))
            self.assertEqual(fence['status'],'fenced')
            self.assertEqual(fence['writers'],2)
            for clone in (primary,second):
                self.assertEqual(git(clone,'config','--local','--get','overgate.beadsLegacyFence'),fence['packet_sha256'])
                self.assertTrue((clone/'.git/overgate-bd-legacy-fence.json').is_file())
                for script,arguments in (('bd-wt.sh',['update','big-heroes-1','--claim']),
                                         ('bd-sync-export.sh',[]),('bd-sync-restore.sh',[]),('bd-bootstrap.sh',[])):
                    blocked=subprocess.run(['bash','scripts/'+script,*arguments],cwd=clone,capture_output=True,text=True,timeout=45)
                    self.assertNotEqual(blocked.returncode,0,script)
                    self.assertIn('legacy writer fenced',blocked.stderr,script)
            self.assertEqual(git(primary,'ls-remote','--heads','origin','refs/heads/beads-backup').split()[0],frozen['R'])
            post_fence=root/'post-fence.json'
            self.assertEqual(json.loads(run([*cmd[:-1],post_fence],ROOT))['R'],frozen['R'])
            self.assertEqual(json.loads(post_fence.read_bytes())['fence_packet_sha256'],fence['packet_sha256'])
            marker=second/'.git/overgate-bd-legacy-fence.json';original_marker=marker.read_bytes()
            truncated=json.loads(original_marker);truncated['helper_sha256'].pop('scripts/bd-bootstrap.sh')
            marker.write_bytes(installer.json_bytes(truncated))
            with self.assertRaisesRegex(installer.InstallError,'legacy writer helper fence incomplete'):
                installer.verified_legacy_fences(post_fence)
            marker.write_bytes(original_marker)
            forged_marker=json.loads(original_marker);forged_marker['packet_sha256']='f'*64
            marker.write_bytes(installer.json_bytes(forged_marker))
            git(second,'config','--local','--replace-all','overgate.beadsLegacyFence','f'*64)
            with self.assertRaisesRegex(installer.InstallError,'legacy writer fence config changed'):
                installer.verified_legacy_fences(post_fence)
            marker.write_bytes(original_marker)
            git(second,'config','--local','--replace-all','overgate.beadsLegacyFence',fence['packet_sha256'])
            source=root/'overgate-source';source.mkdir()
            git(source,'init','-q','-b','main');git(source,'config','user.name','fixture')
            git(source,'config','user.email','fixture@example.invalid')
            source_manifest=json.loads((ROOT/'.agents/distribution-manifest.json').read_bytes())
            for relative in {item['source'] for item in source_manifest['files']} | \
                            {'.agents/distribution-manifest.json','scripts/install-overgate.py'}:
                copied=source/relative;copied.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/relative,copied)
            git(source,'add','-A');git(source,'commit','-qm','trusted upgrade source')
            source_head=git(source,'rev-parse','HEAD')
            contract=root/'contract.md';contract.write_text('Reviewed legacy managed switch fixture\n')
            git(primary,'switch','-q','-c','upgrade-switch')
            pr='https://github.com/example/project/pull/17'
            legacy=installer.make_plan(source,source_head,primary,contract,pr,preservation=post_fence)
            self.assertEqual(legacy['beads_protocol'],'legacy-v0','preservation alone must never switch protocol')
            switched=installer.make_plan(source,source_head,primary,contract,pr,preservation=post_fence,
                                         switch_managed=True)
            self.assertEqual(switched['beads_protocol'],'managed-v1')
            self.assertTrue(switched['switch_managed'])
            old_state=(primary/'.overgate/install-state.json').read_bytes()
            before_db=installer.beads_inventory(primary)['local']['.beads']
            plan_file=root/'switch-plan.json';plan_file.write_bytes(installer.json_bytes(switched))
            approval=root/'approval.json';approval.write_bytes(installer.json_bytes({
                'verdict':'PLAN_READY','plan_sha256':hashlib.sha256(plan_file.read_bytes()).hexdigest(),
                'evidence':pr+'#issuecomment-reviewed'}))
            installer.apply(plan_file,approval)
            state=json.loads((primary/'.overgate/install-state.json').read_bytes())
            self.assertEqual(state['beads_protocol'],'managed-v1')
            self.assertEqual(installer.beads_inventory(primary)['local']['.beads'],before_db)
            backup=sorted((primary/'.overgate-backups').glob('*/rollback.json'))[-1]
            installer.rollback(primary,backup)
            self.assertEqual((primary/'.overgate/install-state.json').read_bytes(),old_state)
            self.assertEqual(installer.beads_inventory(primary)['local']['.beads'],before_db)
            attacker=root/'attacker.git';attacker_seed=root/'attacker-seed'
            git(root,'clone','-q','--bare',remote,attacker)
            git(root,'clone','-q',attacker,attacker_seed)
            git(attacker_seed,'config','user.name','fixture');git(attacker_seed,'config','user.email','fixture@example.invalid')
            git(attacker_seed,'switch','-q','beads-backup')
            (attacker_seed/'.beads/issues.jsonl').write_text('{}\n')
            git(attacker_seed,'add','.beads/issues.jsonl');git(attacker_seed,'commit','-qm','attacker snapshot')
            git(attacker_seed,'push','-q','origin','beads-backup')
            spoof={**os.environ,'GIT_CONFIG_COUNT':'2','GIT_CONFIG_KEY_0':'remote.origin.url','GIT_CONFIG_VALUE_0':str(attacker),
                   'GIT_CONFIG_KEY_1':'remote.origin.pushurl','GIT_CONFIG_VALUE_1':str(attacker)}
            spoofed=root/'spoofed.json'
            spoof_result=subprocess.run([str(item) for item in [*cmd[:-1],spoofed]],cwd=ROOT,env=spoof,
                                        capture_output=True,text=True,timeout=90)
            self.assertEqual(spoof_result.returncode,0,spoof_result.stderr)
            self.assertEqual(json.loads(spoofed.read_bytes())['R'],value['R'])
            linked=root/'packet-link.json';linked.symlink_to(packet)
            with self.assertRaises(installer.InstallError):
                installer.preservation_packet(primary,installer.beads_inventory(primary),linked)
            (primary/'.bd-intents').mkdir();(primary/'.bd-intents/pending.jsonl').write_text('{}\n')
            bad=subprocess.run([str(item) for item in [*cmd[:-1],root/'bad.json']],cwd=ROOT,capture_output=True,text=True)
            self.assertNotEqual(bad.returncode,0)
            self.assertIn('clean outcome contradicts pending',bad.stderr)
            self.assertEqual((primary/'.bd-intents/pending.jsonl').read_bytes(),b'{}\n')
            # The pending fixture is isolated; remove it to replay the reviewed
            # clean plan and prove rollback closes after first managed publish.
            shutil.rmtree(primary/'.bd-intents')
            prior_backups=set((primary/'.overgate-backups').glob('*/rollback.json'))
            installer.apply(plan_file,approval)
            published_backup=(set((primary/'.overgate-backups').glob('*/rollback.json'))-prior_backups).pop()
            git(primary,'add','--',*[item['target'] for item in switched['operations']],'.overgate/install-state.json')
            git(primary,'commit','-qm','reviewed managed protocol switch')
            git(primary,'switch','-q','main');git(primary,'merge','-q','--ff-only','upgrade-switch')
            git(primary,'push','-q','origin','main');git(second,'pull','-q','--ff-only')
            git(second,'config','--local','user.name','fixture publisher')
            git(second,'config','--local','user.email','publisher@example.invalid')
            setup=root/'publisher-setup.json'
            run(['node','scripts/bd-publisher-setup.mjs','--primary-root',primary,'--publisher-root',second,
                 '--qualified-cli',BINARY,'--output',setup],second)
            run(['node','scripts/bd-publisher-setup.mjs','--install',setup],second)
            preservation=second/'.git/overgate-bd-managed/preservation';preservation.mkdir(parents=True)
            legacy_bytes=Path(frozen['snapshot_path']).read_bytes()
            (preservation/'legacy-snapshot.jsonl').write_bytes(legacy_bytes)
            bootstrap=preservation/'preservation.json'
            bootstrap.write_text(json.dumps({'version':1,'base':frozen['R'],'actor':ACTOR,'outcome':'verified-clean',
                                             'artifacts':{'legacy_snapshot':{'name':'legacy-snapshot.jsonl',
                                                                           'sha256':hashlib.sha256(legacy_bytes).hexdigest()}}})+'\n')
            self.assertEqual(json.loads(run(['bash','scripts/bd-apply-intents.sh','--bootstrap',bootstrap],second))['status'],'bootstrapped')
            raw=root/'managed-cutover-raw.jsonl';prepared=root/'managed-cutover.v2.jsonl'
            raw.write_text(json.dumps({'intent_id':'cutover-create','op':'create','handle':'tmp:cutover',
                                       'title':'Managed after reviewed cutover'})+'\n'+
                           json.dumps({'intent_id':'cutover-claim','op':'claim','ref':'tmp:cutover'})+'\n')
            self.assertEqual(json.loads(run(['bash','scripts/bd-apply-intents.sh','--prepare','--base',frozen['R'],
                                             '--actor',ACTOR,'--output',prepared,raw],second))['status'],'prepared')
            published=json.loads(run(['bash','scripts/bd-apply-intents.sh',prepared],second,
                                   {**os.environ,'BD_BIN':str(BINARY)}))
            self.assertEqual(published['status'],'published')
            self.assertTrue(published['claims'][0]['confirmed'])
            task_id=published['claims'][0]['id']
            read=json.loads(run(['bash','scripts/bd-read.sh','show',task_id,'--json'],primary))
            self.assertEqual((read['id'],read['status'],read['assignee']),(task_id,'in_progress',ACTOR))
            published_rows=[json.loads(line) for line in git(primary,'show',
                published['published_sha']+':.beads/issues.jsonl').splitlines()]
            self.assertEqual(read,next(row for row in published_rows if row['id']==task_id))
            legacy_read=json.loads(run(['bash','scripts/bd-read.sh','show',legacy_id,'--json'],primary))
            self.assertEqual(legacy_read,next(row for row in published_rows if row['id']==legacy_id))
            self.assertEqual(git(primary,'rev-parse','refs/remotes/origin/beads-backup'),published['published_sha'])
            with self.assertRaisesRegex(installer.InstallError,'rollback after published/unknown'):
                installer.rollback(primary,published_backup)
            self.assertEqual(json.loads((primary/'.overgate/install-state.json').read_bytes())['beads_protocol'],'managed-v1')
            retained=json.loads(run([BINARY,'--db',primary/'.beads/dolt','--readonly','show',legacy_id,'--json'],primary,env))
            self.assertEqual(retained[0]['id'],legacy_id)
            for clone in (primary,second):
                for script,arguments in (('bd-wt.sh',['update',legacy_id,'--claim']),
                                         ('bd-sync-export.sh',[]),('bd-sync-restore.sh',[]),
                                         ('bd-bootstrap.sh',[])):
                    old=subprocess.run(['bash','scripts/'+script,*arguments],cwd=clone,
                                       capture_output=True,text=True,timeout=45)
                    self.assertNotEqual(old.returncode,0,script)
                    if script=='bd-wt.sh':
                        self.assertTrue('legacy writer fenced' in old.stderr or
                                        'прямой bd-wt write запрещён' in old.stderr,old.stderr)
                    else:self.assertIn('legacy writer fenced',old.stderr,script)
            self.assertEqual(git(primary,'ls-remote','--heads','origin','refs/heads/beads-backup').split()[0],
                             published['published_sha'])
            # An adversarial change inside the managed segment must not be
            # accepted merely because its marker hash was recomputed.
            git(seed,'fetch','-q','origin','beads-backup')
            git(seed,'reset','--hard','FETCH_HEAD')
            issue_file=seed/'.beads/issues.jsonl'
            lines=issue_file.read_text().splitlines()
            changed=json.loads(lines[0]);changed['title']='Forged after activation'
            lines[0]=json.dumps(changed,ensure_ascii=False)
            issue_file.write_text('\n'.join(lines)+'\n')
            marker_file=seed/'.beads/overgate-managed-v1.json'
            marker=json.loads(marker_file.read_bytes())
            marker['snapshot_sha256']=hashlib.sha256(issue_file.read_bytes()).hexdigest()
            marker_file.write_text(json.dumps(marker,sort_keys=True,separators=(',',':'))+'\n')
            git(seed,'add','.beads/issues.jsonl','.beads/overgate-managed-v1.json')
            git(seed,'commit','-qm','forged managed snapshot without outcome')
            git(seed,'push','-q','origin','HEAD:beads-backup')
            forged=subprocess.run(['bash','scripts/bd-read.sh','show',task_id,'--json'],cwd=primary,
                                  capture_output=True,text=True,timeout=45)
            self.assertNotEqual(forged.returncode,0,'reader must reject unbacked managed transition')
            self.assertIn('fail-closed',forged.stderr)
            git(seed,'rm','-q','.beads/issues.jsonl')
            git(seed,'commit','-qm','missing managed snapshot')
            git(seed,'push','-q','origin','HEAD:beads-backup')
            missing=subprocess.run(['bash','scripts/bd-read.sh','show',task_id,'--json'],cwd=primary,
                                   capture_output=True,text=True,timeout=45)
            self.assertNotEqual(missing.returncode,0,'reader must reject missing managed snapshot')
            self.assertIn('снимок',missing.stderr)

if __name__=='__main__':unittest.main()
