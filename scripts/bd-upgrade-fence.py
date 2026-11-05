#!/usr/bin/env python3
"""Fence every explicitly listed legacy OverGate writer before a reviewed switch."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

SCRIPT=Path(__file__).resolve()
spec=importlib.util.spec_from_file_location('overgate_installer',SCRIPT.with_name('install-overgate.py'))
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class FenceError(Exception):pass

def sha(data):return hashlib.sha256(data).hexdigest()
def git(root,*args):return installer.git(root,*args).decode().strip()
def marker(root):return root/'.git/overgate-bd-legacy-fence.json'

def main(packet_name):
    packet_path=Path(packet_name)
    if not packet_path.is_absolute() or packet_path.is_symlink() or not packet_path.is_file():
        raise FenceError('private preservation packet must be an absolute regular file')
    raw=packet_path.read_bytes();packet=json.loads(raw)
    target=Path(packet['target'])
    if not target.is_absolute() or target.is_symlink() or target.resolve()!=target:
        raise FenceError('packet target must be a canonical checkout')
    if SCRIPT!=target/'scripts/bd-upgrade-fence.py':
        raise FenceError('fence helper must run from the packet target main')
    verified=installer.preservation_packet(target,installer.beads_inventory(target),packet_path)
    if verified['outcome']!='verified-clean':
        raise FenceError('unresolved pending legacy work cannot be fenced for switch')
    if packet.get('fence_packet_sha256') is not None:
        raise FenceError('fence requires the original pre-fence preservation packet')
    writers=[Path(item['root']) for item in packet['writers']]
    if not writers or target not in writers or len(set(writers))!=len(writers):
        raise FenceError('explicit writer list invalid')
    head=packet['target_head'];pins={}
    for root in writers:
        if root.is_symlink() or root.resolve()!=root or (root/'.git').is_symlink() or not (root/'.git').is_dir():
            raise FenceError('legacy writer standalone checkout required')
        if Path(git(root,'rev-parse','--show-toplevel')).resolve()!=root:
            raise FenceError('legacy writer root mismatch')
        if Path(git(root,'rev-parse','--path-format=absolute','--git-common-dir')).resolve()!=root/'.git' \
           or Path(git(root,'rev-parse','--path-format=absolute','--git-dir')).resolve()!=root/'.git':
            raise FenceError('legacy writer linked checkout denied')
        if git(root,'symbolic-ref','--quiet','--short','HEAD')!='main' or git(root,'rev-parse','HEAD')!=head:
            raise FenceError('all legacy writer clones require the same trusted main')
        if git(root,'ls-remote','--heads','origin','refs/heads/main').split()!=[head,'refs/heads/main']:
            raise FenceError('legacy writer main is not exact origin/main')
        if git(root,'status','--porcelain','--untracked-files=no'):
            raise FenceError('legacy writer tracked source/index changed')
        if marker(root).exists() or marker(root).is_symlink():
            raise FenceError('legacy fence collision; preserve partial state for review')
        existing=subprocess.run(['git','-C',str(root),'config','--local','--get-all','overgate.beadsLegacyFence'],
                                capture_output=True,env=installer.git_environment())
        if existing.returncode!=1:raise FenceError('legacy fence config collision/unknown')
        local=installer.beads_inventory(root)['local']
        if any(name in local for name in ('git/overgate-bd-managed','git/overgate-bd-publisher-control')):
            raise FenceError('managed control already exists in old writer clone')
        state_path=root/installer.STATE
        if not state_path.is_file() or state_path.is_symlink() \
           or state_path.read_bytes()!=installer.git(root,'show','HEAD:'+installer.STATE):
            raise FenceError('installed legacy writer closure state missing/unsafe')
        state=json.loads(state_path.read_bytes())
        if state.get('beads') is not True or state.get('beads_protocol')!='legacy-v0':
            raise FenceError('installed legacy writer closure protocol mismatch')
        installed=state.get('installed',{})
        if not isinstance(installed,dict):raise FenceError('installed legacy writer closure incomplete')
        for name in installer.LEGACY_FENCE_CLOSURE:
            file=root/name
            if not file.is_file() or file.is_symlink():raise FenceError('installed legacy writer closure missing/unsafe: '+name)
            committed=installer.git(root,'show','HEAD:'+name)
            if file.read_bytes()!=committed:raise FenceError('installed legacy writer closure differs from trusted main: '+name)
            digest=sha(committed)
            if installed.get(name,{}).get('sha256')!=digest:
                raise FenceError('installed legacy writer closure receipt differs: '+name)
            if name in installer.LEGACY_FENCE_HELPERS:
                if name in pins and pins[name]!=digest:raise FenceError('legacy writer helper bytes differ between clones: '+name)
                pins[name]=digest
    # The marker is written first. An interrupted operation therefore leaves
    # already processed clones safely fenced; no task DB, queue or remote is edited.
    packet_sha=sha(raw)
    for root in writers:
        content=installer.json_bytes({'version':1,'packet_sha256':packet_sha,'R':packet['R'],
                                      'actor':packet['actor'],'target':str(target),
                                      'writers':[str(item) for item in writers],
                                      'head':head,'helper_sha256':pins})
        destination=marker(root);temporary=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
        with temporary.open('xb') as output:
            output.write(content);output.flush();os.fsync(output.fileno())
        os.replace(temporary,destination)
        installer.git(root,'config','--local','--replace-all','overgate.beadsLegacyFence',packet_sha)
        if git(root,'config','--local','--get','overgate.beadsLegacyFence')!=packet_sha \
           or destination.read_bytes()!=content or installer.beads_inventory(root)['remote']!={'status':'present','R':packet['R']}:
            raise FenceError('legacy fence read-back/remote drift; partial fences retained')
        installer.assert_legacy_origin_heads(root,head,packet['R'])
    return {'status':'fenced','writers':len(writers),'R':packet['R'],'packet_sha256':packet_sha}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--packet',required=True)
    try:print(json.dumps(main(parser.parse_args().packet),sort_keys=True))
    except (FenceError,installer.InstallError,OSError,ValueError,KeyError,subprocess.TimeoutExpired) as error:
        print('STOP: '+str(error),file=sys.stderr);raise SystemExit(1)
