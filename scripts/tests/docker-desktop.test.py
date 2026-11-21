"""Проверка владения Docker Desktop на заглушках и временном каталоге."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

desktop = load('docker_desktop', ROOT / '.claude/tools/docker_desktop.py')


class DesktopTests(unittest.TestCase):
    owned_running_id = 'a' * 64
    owned_exited_id = 'b' * 64
    owned_created_id = 'c' * 64
    foreign_running_id = 'd' * 64
    foreign_stopped_id = 'e' * 64

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='og-desktop-')
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        self.running = False
        self.engine_ready = True
        self.status_unknown = False
        self.stop_lies = False
        self.cold_status_error = ''
        self.status_timeout = False
        self.windows_probe_result = (0, 'desktop-absent', '')
        self.endpoint = 'npipe:////./pipe/dockerDesktopLinuxEngine'
        self.macos_home = Path('/Users/slipstream-qa')
        self.macos_host = 'unix:///Users/slipstream-qa/.docker/run/docker.sock'
        self.process_table = (0, '/sbin/launchd\n/bin/ps', '')
        home_patch = patch.object(desktop.Path, 'home', return_value=self.macos_home)
        home_patch.start()
        self.addCleanup(home_patch.stop)
        if not hasattr(desktop.socket, 'AF_UNIX'):
            unix_family = patch.object(desktop.socket, 'AF_UNIX', 1, create=True)
            unix_family.start()
            self.addCleanup(unix_family.stop)
        socket_patch = patch.object(desktop.socket, 'socket')
        self.connect = socket_patch.start().return_value.__enter__.return_value.connect
        self.connect.side_effect = FileNotFoundError
        self.addCleanup(socket_patch.stop)
        self.desktop_session = 'test-desktop-session'
        self.start_statuses = []
        self.start_already_running = False
        self.info_failures = 0
        self.calls = []
        self.stop_fails = False
        self.foreign = False
        self.owned_container = False
        self.owned_stopped = []
        self.foreign_stopped = False
        self.scope_query_rc = 0
        self.drain_query_rc = 0
        self.removal_rc = 0
        self.removed = []
        self.old_scope = os.environ.pop('OVERGATE_DOCKER_SCOPE', None)
        self.addCleanup(self.restore_env)
        system_root = patch.dict(os.environ, {'SystemRoot': 'C:/Windows'})
        system_root.start()
        self.addCleanup(system_root.stop)

    def restore_env(self):
        os.environ.pop('OVERGATE_DOCKER_SCOPE', None)
        if self.old_scope:
            os.environ['OVERGATE_DOCKER_SCOPE'] = self.old_scope

    def command(self, args, **kwargs):
        args = list(args)
        self.calls.append(args)
        code, out = 0, ''
        if args[0] == '/bin/ps':
            return subprocess.CompletedProcess(args, *self.process_table)
        if args[0].endswith('powershell.exe'):
            return subprocess.CompletedProcess(args, *self.windows_probe_result)
        if args[1:3] == ['desktop', 'status']:
            if self.status_timeout or (self.cold_status_error and not self.running and kwargs['timeout'] < 17):
                raise subprocess.TimeoutExpired(args, kwargs['timeout'])
            if self.cold_status_error and not self.running:
                return subprocess.CompletedProcess(args, 1, '', self.cold_status_error)
            status = 'unknown' if self.status_unknown else 'running' if self.running else 'stopped'
            if self.running and self.start_statuses:
                status, self.desktop_session = self.start_statuses.pop(0)
            out = json.dumps({'Status': status, 'SessionID': self.desktop_session})
        elif args[1:3] == ['context', 'inspect']:
            out = self.endpoint
        elif args[1:2] == ['info']:
            code = 0 if self.running and self.engine_ready and not self.info_failures else 1
            if self.info_failures:
                self.info_failures -= 1
            out = 'Docker Desktop' if code == 0 else ''
        elif args[1:] == ['desktop', 'start']:
            self.running = True
            out = ('Docker Desktop is already running' if self.start_already_running
                   else '\N{CHECK MARK} Starting Docker Desktop')
        elif args[1:] == ['desktop', 'stop']:
            if self.stop_fails:
                code = 7
            elif not self.stop_lies:
                self.running = False
        elif args[1:2] == ['ps']:
            own_running = [self.owned_running_id] if self.owned_container else []
            if '--filter' in args:
                journal = json.loads((self.state / 'owner.json').read_text(encoding='utf-8'))
                self.assertEqual(args[-1], 'label=overgate.desktop.scope=' + journal['token'])
                code = self.drain_query_rc if self.removed else self.scope_query_rc
                ids = own_running + (self.owned_stopped if '-a' in args else [])
            else:
                ids = own_running + ([self.foreign_running_id] if self.foreign else [])
                if '-a' in args:
                    ids += self.owned_stopped + ([self.foreign_stopped_id] if self.foreign_stopped else [])
            out = '\n'.join(ids)
        elif args[1:3] == ['rm', '-f']:
            code = self.removal_rc
            if not code:
                self.removed.extend(args[3:])
                self.owned_container = self.owned_container and self.owned_running_id not in self.removed
                self.owned_stopped = [i for i in self.owned_stopped if i not in self.removed]
                self.foreign_stopped = self.foreign_stopped and self.foreign_stopped_id not in self.removed
        return subprocess.CompletedProcess(args, code, out, '')

    def context(self, platform='win32', **kwargs):
        if platform == 'darwin':
            self.endpoint = self.macos_host
        return desktop.Desktop(state_dir=self.state, run=self.command, platform=platform, **kwargs)

    def test_owned_lifecycle_starts_and_stops(self):
        with self.context():
            self.assertTrue(self.running)
        self.assertFalse(self.running)

    def test_windows_cold_cli_error_starts_and_stops_after_native_absence_proof(self):
        self.cold_status_error = ('Could not retrieve status. Is Docker Desktop running?\n'
                                  "You can start Docker Desktop by running 'docker desktop start'.")
        with self.context():
            self.assertTrue(self.running)
        self.assertFalse(self.running)
        self.assertFalse((self.state / 'owner.json').exists())
        self.assertEqual(sum(call[0].endswith('powershell.exe') for call in self.calls), 2)
        self.assertEqual(self.calls.count(['docker', 'desktop', 'start']), 1)
        self.assertEqual(self.calls.count(['docker', 'desktop', 'stop']), 1)

    def test_windows_cold_error_requires_successful_native_absence_proof(self):
        self.cold_status_error = 'Could not retrieve status. Is Docker Desktop running?'
        for result in ((0, 'desktop-present', ''), (1, 'desktop-absent', 'error'), (0, '', '')):
            with self.subTest(result=result):
                self.windows_probe_result = result
                self.calls.clear()
                with self.assertRaises(desktop.DesktopError):
                    with self.context():
                        self.fail('uncertain Desktop was acquired')
                self.assertTrue(any(call[0].endswith('powershell.exe') for call in self.calls))
                self.assertNotIn(['docker', 'desktop', 'start'], self.calls)
                self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)
                self.assertFalse((self.state / 'owner.json').exists())

    def test_windows_status_timeout_and_unrelated_failure_stay_unknown(self):
        for timeout, error in ((True, ''), (False, 'unknown command')):
            with self.subTest(timeout=timeout):
                self.status_timeout, self.cold_status_error = timeout, error
                self.calls.clear()
                with self.assertRaises(desktop.DesktopError):
                    with self.context():
                        self.fail('uncertain Desktop was acquired')
                self.assertEqual(self.calls, [['docker', 'desktop', 'status', '--format', 'json']])
                self.assertFalse((self.state / 'owner.json').exists())

    def test_windows_start_waits_for_same_session_and_ready_engine(self):
        self.start_statuses = [('starting', self.desktop_session), ('running', self.desktop_session)]
        self.info_failures = 1
        with self.context():
            saved = json.loads((self.state / 'owner.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['session_id'], self.desktop_session)
            self.assertEqual(self.calls.count(['docker', 'info', '--format', '{{.OperatingSystem}}']), 2)
        self.assertFalse(self.running)

    def test_windows_replaced_starting_session_preserves_owner(self):
        original = self.desktop_session
        self.start_statuses = [('starting', original), ('running', 'replacement-session')]
        with self.assertRaises(desktop.DesktopError):
            with self.context():
                self.fail('foreign Desktop was acquired during startup')
        saved = json.loads((self.state / 'owner.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['session_id'], original)
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)
        self.assertTrue(self.running)

    def test_windows_start_report_already_running_never_claims_or_stops_session(self):
        self.start_already_running = True
        with self.assertRaises(desktop.DesktopError):
            with self.context():
                self.fail('foreign Desktop was acquired after start')
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)
        self.assertTrue(self.running)
        saved = json.loads((self.state / 'owner.json').read_text(encoding='utf-8'))
        self.assertNotIn('session_id', saved)

    def test_failed_body_still_stops(self):
        with self.assertRaisesRegex(RuntimeError, 'test failed'):
            with self.context():
                raise RuntimeError('test failed')
        self.assertFalse(self.running)

    def test_nested_scope_does_not_stop_outer_owner(self):
        with self.context():
            with self.context():
                pass
            self.assertTrue(self.running)
        self.assertEqual(self.calls.count(['docker', 'desktop', 'start']), 1)
        self.assertEqual(self.calls.count(['docker', 'desktop', 'stop']), 1)

    def test_unknown_running_desktop_is_not_adopted(self):
        self.running = True
        with self.assertRaises(desktop.DesktopError):
            with self.context():
                pass
        self.assertTrue(self.running)
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)

    def test_unready_foreign_engine_does_not_mean_desktop_is_off(self):
        self.running, self.engine_ready = True, False
        with self.assertRaises(desktop.DesktopError):
            with self.context():
                pass
        self.assertNotIn(['docker', 'desktop', 'start'], self.calls)
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)

    def test_indeterminate_cleanup_preserves_ownership_and_fails(self):
        with self.assertRaises(desktop.DesktopError):
            with self.context():
                self.status_unknown = True
        self.assertTrue((self.state / 'owner.json').exists())

    def test_stop_must_prove_desktop_stopped(self):
        self.stop_lies = True
        with self.assertRaises(desktop.DesktopError):
            with self.context():
                pass
        self.assertTrue((self.state / 'owner.json').exists())

    def test_acquire_lock_is_released_after_process_kill(self):
        bootstrap = '''import importlib.util,sys,time
spec=importlib.util.spec_from_file_location('desktop',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with m.Desktop(state_dir=sys.argv[2],platform='win32').lock():
 print('locked',flush=True);time.sleep(30)
'''
        child = subprocess.Popen([sys.executable, '-c', bootstrap,
            str(ROOT / '.claude/tools/docker_desktop.py'), str(self.state)],
            stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'locked')
            with self.assertRaises(desktop.DesktopError):
                with self.context().lock():
                    pass
        finally:
            child.kill()
            child.wait(timeout=5)
            child.stdout.close()
        with self.context():
            pass

    def test_cleanup_failure_is_not_green(self):
        self.stop_fails = True
        with self.assertRaises(desktop.DesktopError):
            with self.context():
                pass

    def test_foreign_work_is_not_stopped(self):
        with self.assertRaises(desktop.DesktopError):
            with self.context():
                self.foreign = True
        self.assertTrue(self.running)
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)

    def test_recover_removes_exited_and_created_owned_ids_and_preserves_foreign_stopped(self):
        self.context().prepare()
        self.owned_stopped = [self.owned_exited_id, self.owned_created_id]
        self.foreign_stopped = True
        self.context().recover()
        self.assertEqual(self.removed, [self.owned_exited_id, self.owned_created_id])
        self.assertTrue(self.foreign_stopped)
        self.assertFalse(self.running)
        self.assertFalse((self.state / 'owner.json').exists())

    def test_recover_with_foreign_running_keeps_desktop_and_journal(self):
        self.context().prepare()
        self.owned_stopped = [self.owned_exited_id]
        self.foreign = True
        with self.assertRaises(desktop.DesktopError):
            self.context().recover()
        self.assertEqual(self.removed, [self.owned_exited_id])
        self.assertTrue(self.foreign)
        self.assertTrue(self.running)
        self.assertTrue((self.state / 'owner.json').is_file())
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)

    def test_cleanup_query_failure_preserves_journal(self):
        with self.assertRaises(desktop.DesktopError):
            with self.context():
                self.scope_query_rc = 1
        self.assertEqual(self.removed, [])
        self.assertTrue((self.state / 'owner.json').is_file())
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)

    def test_cleanup_unconfirmed_removal_preserves_journal(self):
        with self.assertRaises(desktop.DesktopError):
            with self.context():
                self.owned_stopped = [self.owned_exited_id]
                self.removal_rc = 1
        self.assertEqual(self.owned_stopped, [self.owned_exited_id])
        self.assertTrue((self.state / 'owner.json').is_file())
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)

    def test_cleanup_rechecks_owned_scope_before_discarding_journal(self):
        with self.assertRaises(desktop.DesktopError):
            with self.context():
                self.owned_stopped = [self.owned_created_id]
                self.drain_query_rc = 1
        self.assertEqual(self.removed, [self.owned_created_id])
        self.assertTrue((self.state / 'owner.json').is_file())
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)

    def test_cleanup_does_not_accept_truncated_container_ids(self):
        with self.assertRaises(desktop.DesktopError):
            with self.context():
                self.owned_stopped = ['abc123']
        self.assertEqual(self.removed, [])
        self.assertTrue((self.state / 'owner.json').is_file())
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)

    def test_orphan_container_in_owned_scope_is_removed_before_stop(self):
        with self.context():
            self.owned_container = True
        self.assertFalse(self.owned_container)
        self.assertFalse(self.running)

    def test_cold_hook_requires_preparation_without_starting(self):
        with self.assertRaises(desktop.DesktopError):
            with self.context(hook=True):
                pass
        self.assertNotIn(['docker', 'desktop', 'start'], self.calls)

    def test_replaced_prepared_desktop_cannot_be_consumed_or_stopped(self):
        self.context().prepare()
        self.desktop_session = 'replacement-session'
        state_file = self.state / 'owner.json'
        saved_owner = state_file.read_bytes()
        with self.assertRaises(desktop.DesktopError):
            with self.context(hook=True):
                self.fail('foreign Desktop was acquired')
        with self.assertRaises(desktop.DesktopError):
            self.context().recover()
        self.assertEqual(state_file.read_bytes(), saved_owner)
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)
        self.assertTrue(self.running)

    def test_missing_windows_session_id_preserves_owner_and_prevents_stop(self):
        with self.assertRaises(desktop.DesktopError):
            with self.context():
                self.desktop_session = None
        self.assertTrue((self.state / 'owner.json').exists())
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)

    def test_prepared_hook_keeps_long_status_only_for_post_stop_confirmation(self):
        self.context().prepare()
        self.cold_status_error = 'Could not retrieve status. Is Docker Desktop running?'
        scope = self.context(hook=True)
        status_timeouts = []

        def record_timeouts(args, **kwargs):
            if args[1:3] == ['desktop', 'status']:
                status_timeouts.append(kwargs['timeout'])
            return self.command(args, **kwargs)

        scope.run = record_timeouts
        with scope:
            self.assertTrue(self.running)
        self.assertEqual(status_timeouts, [5, 5, 5, 5, 25])
        self.assertFalse((self.state / 'owner.json').exists())

    def test_prepared_hook_cleanup_deadline_retains_owner_on_unconfirmed_stop(self):
        self.context().prepare()
        self.cold_status_error = 'Could not retrieve status. Is Docker Desktop running?'
        self.owned_container = True
        scope = self.context(hook=True)
        now = 0
        cleanup_started = None

        def consume_timeout(args, **kwargs):
            nonlocal now
            now += kwargs['timeout']
            return self.command(args, **kwargs)

        scope.run = consume_timeout
        with patch.object(desktop.time, 'monotonic', lambda: now):
            with self.assertRaises(desktop.DesktopError):
                with scope:
                    cleanup_started = now
        self.assertEqual(cleanup_started, 20)
        self.assertLessEqual(now - cleanup_started, 85)
        self.assertIn(['docker', 'desktop', 'stop'], self.calls)
        self.assertTrue((self.state / 'owner.json').exists())
        self.assertNotIn('OVERGATE_DOCKER_SCOPE', os.environ)

    def test_macos_stopped_with_live_engine_keeps_existing_work(self):
        self.connect.side_effect = None
        scope = self.context(platform='darwin')
        with self.assertRaisesRegex(desktop.DesktopError, 'Engine'):
            scope.prepare()
        self.assertFalse(scope.state_file.exists())
        self.assertNotIn(['docker', 'desktop', 'start'], self.calls)
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)

    def test_macos_uncertain_cold_probe_cannot_start(self):
        for host, connect_error, processes in [
                ('ssh://remote', FileNotFoundError, self.process_table),
                ('unix:///tmp/other.sock', FileNotFoundError, self.process_table),
                (self.macos_host, TimeoutError, self.process_table),
                (self.macos_host, PermissionError, self.process_table),
                (self.macos_host, FileNotFoundError, (1, '', 'failed')),
                (self.macos_host, ConnectionRefusedError, (0, '/Applications/Docker.app/Contents/MacOS/com.docker.backend', ''))]:
            with self.subTest(host=host, connect_error=connect_error, processes=processes):
                scope = self.context(platform='darwin')
                self.endpoint, self.connect.side_effect, self.process_table = host, connect_error, processes
                with self.assertRaises(desktop.DesktopError):
                    scope.prepare()
                self.assertFalse(scope.state_file.exists())
        self.assertNotIn(['docker', 'desktop', 'start'], self.calls)

    def test_macos_accepts_known_status_error_only_after_native_cold_proof(self):
        self.cold_status_error = 'Could not retrieve status. Is Docker Desktop running?'
        self.connect.side_effect = ConnectionRefusedError
        with self.context(platform='darwin'):
            self.assertTrue(self.running)
        self.assertEqual(self.connect.call_count, 2)
        self.assertFalse((self.state / 'owner.json').exists())

    def test_macos_live_socket_after_stop_preserves_journal_through_recovery(self):
        scope = self.context(platform='darwin')
        with patch.object(desktop.time, 'sleep') as sleep, patch.object(desktop.time, 'monotonic', return_value=0) as clock:
            sleep.side_effect = lambda duration: setattr(clock, 'return_value', clock.return_value + duration)
            with self.assertRaises(desktop.DesktopError):
                with scope:
                    original = scope.state_file.read_bytes()
                    self.connect.side_effect = None
            self.assertEqual(clock.return_value, 35)
        self.assertEqual(scope.state_file.read_bytes(), original)
        with patch.object(desktop, 'alive', return_value=False):
            with self.assertRaisesRegex(desktop.DesktopError, 'Engine'):
                scope.recover()
            self.assertEqual(scope.state_file.read_bytes(), original)
            self.connect.side_effect = FileNotFoundError
            scope.recover()
        self.assertFalse(scope.state_file.exists())
        self.assertEqual(self.calls.count(['docker', 'desktop', 'stop']), 1)

    def test_macos_waits_for_socket_to_close_after_owned_stop(self):
        with patch.object(desktop.time, 'sleep') as sleep:
            with self.context(platform='darwin'):
                self.connect.side_effect = [None, ConnectionRefusedError]
            sleep.assert_called_once()
        self.assertFalse((self.state / 'owner.json').exists())
        self.assertEqual(self.calls.count(['docker', 'desktop', 'stop']), 1)

    def test_macos_start_requires_evidence_beyond_rc_zero(self):
        self.start_already_running = True
        with self.assertRaises(desktop.DesktopError):
            with self.context(platform='darwin'):
                pass
        self.assertTrue(self.running)
        self.assertTrue((self.state / 'owner.json').is_file())
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)

    def test_macos_valid_session_is_handed_from_prepare_to_cleanup(self):
        self.context(platform='darwin').prepare()
        journal = json.loads((self.state / 'owner.json').read_text(encoding='utf-8'))
        self.assertEqual(journal['session_id'], self.desktop_session)
        with self.context(platform='darwin', hook=True):
            with self.context(platform='darwin'):
                self.assertTrue(self.running)
        self.assertFalse(self.running)
        self.assertFalse((self.state / 'owner.json').exists())

    def test_macos_stale_prepared_session_cannot_be_consumed_or_stopped(self):
        self.context(platform='darwin').prepare()
        state_file = self.state / 'owner.json'
        journal = state_file.read_bytes()
        self.desktop_session = 'replacement-session'
        with self.assertRaises(desktop.DesktopError):
            with self.context(platform='darwin', hook=True):
                pass
        with self.assertRaises(desktop.DesktopError):
            self.context(platform='darwin').recover()
        self.assertEqual(state_file.read_bytes(), journal)
        self.assertTrue(self.running)
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)

    def test_macos_active_owner_cannot_stop_replacement_or_join_nested(self):
        with self.assertRaises(desktop.DesktopError):
            with self.context(platform='darwin'):
                self.desktop_session = 'replacement-session'
                with self.assertRaises(desktop.DesktopError):
                    with self.context(platform='darwin'):
                        pass
        self.assertTrue(self.running)
        self.assertTrue((self.state / 'owner.json').is_file())
        self.assertNotIn(['docker', 'desktop', 'stop'], self.calls)

    def test_prepared_desktop_is_consumed_and_closed(self):
        self.context().prepare()
        self.assertTrue(self.running)
        with self.context(hook=True):
            pass
        self.assertFalse(self.running)


if __name__ == '__main__':
    unittest.main(verbosity=2)
