"""Behavioral tests using real disposable Git repositories and subprocesses."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

RUNNER = Path(__file__).resolve().parents[1] / 'scripts' / 'autoresearch.py'
spec = importlib.util.spec_from_file_location('autoresearch', RUNNER)
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='codex-autoresearch-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.git('init', '-b', 'codex/test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Autoresearch Test')
        # Keep disposable test repositories independent of the developer's
        # global signing policy and unavailable GPG agents in sandboxes/CI.
        self.git('config', 'commit.gpgSign', 'false')
        self.git('config', 'tag.gpgSign', 'false')
        self.write('value.txt', '10\n')
        self.write('other.txt', 'preserve\n')
        self.write('.gitignore', '*.cache\n')
        self.git('add', '.')
        self.git('commit', '-m', 'base')
        self.write('.auto/measure.sh', 'set -euo pipefail\nprintf "METRIC ms=%s\\n" "$(cat value.txt)"\n')
        self.init()

    def write(self, name, text):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def git(self, *args):
        result = subprocess.run(['git', *args], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(RUNNER), '--project', str(self.root), *args],
                                capture_output=True, text=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return json.loads(result.stderr)['error']

    def init(self, *args):
        return self.cli('init', '--name', 'test', '--metric', 'ms', '--scope', 'value.txt',
                        '--scope', 'new file.txt', '--max-iterations', '20', *args)

    def begin(self):
        return self.cli('begin', '--hypothesis', 'less work')

    def log(self, status='keep', **kwargs):
        return self.cli('log', '--status', status, '--description', 'candidate',
                        '--learned', 'use measurement', '--next-action', 'different algorithm', **kwargs)

    def baseline(self):
        self.begin()
        self.cli('run')
        self.log()

    def test_baseline_and_keep_are_persistent_and_exclude_session_files(self):
        old_head = self.git('rev-parse', 'HEAD')
        self.baseline()
        self.assertEqual(old_head, self.git('rev-parse', 'HEAD'))
        self.begin()
        self.write('value.txt', '8\n')
        self.assertEqual(self.cli('run')['metrics']['ms'], 8)
        self.log()
        status = self.cli('status')
        self.assertEqual((status['baseline'], status['best'], status['run_count']), (10, 8, 2))
        self.assertEqual(self.git('show', '--format=', '--name-only', 'HEAD'), 'value.txt')
        self.assertEqual(self.git('ls-files', '.auto'), '')

    def test_discard_restores_tracked_and_removes_only_captured_new_files(self):
        self.baseline()
        self.begin()
        self.write('value.txt', '12\n')
        self.write('new file.txt', 'experiment\n')
        self.write('valuable.cache', 'ignored artifact\n')
        self.cli('run')
        self.log('discard')
        self.assertEqual((self.root / 'value.txt').read_text(), '10\n')
        self.assertFalse((self.root / 'new file.txt').exists())
        self.assertTrue((self.root / 'valuable.cache').exists())
        self.assertTrue((self.root / '.auto/log.jsonl').exists())

    def test_missing_primary_nonfinite_and_duplicate_metrics_are_crashes(self):
        for output in ['METRIC other=2', 'METRIC ms=nan', 'METRIC ms=Infinity', 'METRIC ms=1\\nMETRIC ms=2']:
            with self.subTest(output=output):
                self.write('.auto/measure.sh', "printf '" + output + "\\n'\n")
                self.begin()
                evidence = self.cli('run')
                self.assertEqual(evidence['outcome'], 'crash')
                self.assertIn('evidence', self.log(ok=False))
                self.log('crash')

    def test_correctness_failure_blocks_keep_and_reverts(self):
        self.baseline()
        self.write('.auto/checks.sh', 'exit 1\n')
        self.begin()
        self.write('value.txt', '1\n')
        self.assertEqual(self.cli('run')['outcome'], 'checks_failed')
        self.assertIn('checks_failed', self.log(ok=False))
        self.log('checks_failed')
        self.assertEqual(self.cli('status')['best'], 10)
        self.assertEqual((self.root / 'value.txt').read_text(), '10\n')

    def test_metric_outside_output_tail_is_parsed(self):
        self.write('.auto/measure.sh', 'echo "METRIC ms=3"\nfor i in {1..3000}; do echo padding; done\n')
        self.begin()
        result = self.cli('run')
        self.assertEqual(result['metrics']['ms'], 3)
        self.assertNotIn('METRIC', result['benchmark']['tail'])

    def test_nonzero_exit_even_with_valid_metric_cannot_keep(self):
        self.write('.auto/measure.sh', 'echo "METRIC ms=1"\nexit 2\n')
        self.begin()
        self.assertEqual(self.cli('run')['outcome'], 'crash')
        self.assertIn('crash', self.log(ok=False))
        self.log('crash')

    def test_benchmark_and_checks_timeouts(self):
        self.write('.auto/measure.sh', 'sleep 10\necho "METRIC ms=1"\n')
        self.begin()
        result = self.cli('run', '--timeout', '0.05')
        self.assertTrue(result['benchmark']['timed_out'])
        self.log('crash')
        self.write('.auto/measure.sh', 'echo "METRIC ms=1"\n')
        self.write('.auto/checks.sh', 'sleep 10\n')
        self.begin()
        result = self.cli('run', '--checks-timeout', '0.05')
        self.assertTrue(result['checks']['timed_out'])
        self.log('checks_failed')

    def test_dirty_or_staged_user_work_prevents_begin(self):
        self.write('other.txt', 'user work\n')
        self.assertIn('clean', self.cli('begin', '--hypothesis', 'test', ok=False))
        self.git('add', 'other.txt')
        self.assertIn('Index', self.cli('begin', '--hypothesis', 'test', ok=False))
        self.assertEqual((self.root / 'other.txt').read_text(), 'user work\n')

    def test_out_of_scope_prevents_run(self):
        self.begin()
        self.write('other.txt', 'out of scope\n')
        self.assertIn('Out-of-scope', self.cli('run', ok=False))
        self.assertEqual((self.root / 'other.txt').read_text(), 'out of scope\n')

    def test_post_measurement_edits_and_protocol_changes_prevent_log(self):
        self.begin()
        self.cli('run')
        self.write('value.txt', '7\n')
        self.assertIn('changed since', self.log(ok=False))
        self.write('value.txt', '10\n')
        self.write('.auto/checks.sh', 'exit 0\n')
        self.assertIn('protocol changed', self.log(ok=False))

    def test_benchmark_mutation_fails_closed(self):
        self.write('.auto/measure.sh', 'echo 1 > value.txt\necho "METRIC ms=1"\n')
        self.begin()
        self.assertFalse(self.cli('run')['tree_unchanged'])
        self.assertIn('changed since', self.log('crash', ok=False))
        self.cli('abort', '--reason', 'source mutation')
        self.assertEqual((self.root / 'value.txt').read_text(), '1\n')

    def test_higher_direction_zero_and_budget(self):
        self.cli('init', '--new-segment', '--name', 'higher', '--metric', 'ms', '--direction', 'higher',
                 '--scope', 'value.txt', '--max-iterations', '2')
        self.write('.auto/measure.sh', 'echo "METRIC ms=0"\n')
        self.baseline()
        self.write('.auto/measure.sh', 'echo "METRIC ms=1"\n')
        self.begin()
        self.cli('run')
        result = self.log()
        self.assertEqual(result['stop_reason'], 'Iteration budget exhausted')
        status = self.cli('status')
        self.assertEqual(status['best'], 1)
        self.assertFalse(status['active'])
        self.assertIn('budget', self.cli('begin', '--hypothesis', 'test', ok=False))

    def test_equal_or_worse_cannot_keep(self):
        self.baseline()
        self.begin()
        self.cli('run')
        self.assertIn('improvement', self.log(ok=False))
        self.cli('log', '--status', 'keep', '--description', 'simpler', '--learned', 'equal cost', '--allow-equal')

    def test_branch_switch_is_rejected(self):
        self.git('switch', '-c', 'codex/other')
        self.assertIn('another branch', self.cli('status', ok=False))

    def test_abort_retains_edits_and_intent(self):
        experiment = self.begin()
        self.write('value.txt', '9\n')
        self.cli('abort', '--reason', 'user interrupted')
        self.assertTrue((self.root / '.auto/runs' / experiment['id'] / 'aborted.json').exists())
        self.assertEqual((self.root / 'value.txt').read_text(), '9\n')
        self.assertIsNone(self.cli('status')['pending'])

    def test_concurrent_writer_is_rejected(self):
        session = ar.Session(self.root)
        with session.lock():
            self.assertIn('Another autoresearch', self.cli('status', ok=False))

    def test_commit_failure_never_logs_keep(self):
        self.baseline()
        self.begin()
        self.write('value.txt', '9\n')
        self.cli('run')
        hook = self.root / '.git/hooks/pre-commit'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        self.log(ok=False)
        status = self.cli('status')
        self.assertEqual(status['run_count'], 1)
        self.assertEqual(status['pending']['phase'], 'finalizing')
        self.assertIn('staged', self.cli('recover', ok=False))
        hook.unlink()
        self.git('commit', '-m', 'candidate', '-m', 'Autoresearch: ' + status['pending']['id'])
        self.cli('recover')
        self.assertEqual(self.cli('status')['best'], 9)

    def test_recover_after_append_failure_and_no_duplicate_records(self):
        self.baseline()
        self.begin()
        self.write('value.txt', '9\n')
        self.cli('run')
        session = ar.Session(self.root)
        args = type('Args', (), dict(status='keep', description='candidate', learned='faster', next_action=None, allow_equal=False))()
        with mock.patch.object(session, 'append', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                session.log_result(args)
        pending = (self.root / '.auto/pending.json').read_bytes()
        self.cli('recover')
        self.assertEqual(self.cli('status')['run_count'], 2)
        (self.root / '.auto/pending.json').write_bytes(pending)
        self.cli('recover')
        self.assertEqual(self.cli('status')['run_count'], 2)

    def test_hooks_opt_in_and_contract(self):
        self.write('.auto/hooks/before.sh', 'cat > .auto/payload.json\necho context\n')
        (self.root / '.auto/hooks/before.sh').chmod(0o755)
        self.begin()
        self.assertFalse((self.root / '.auto/payload.json').exists())
        self.cli('abort', '--reason', 'enable hooks')
        self.init('--new-segment', '--hooks')
        result = self.begin()
        self.assertIn('context', result['hook']['tail'])
        payload = json.loads((self.root / '.auto/payload.json').read_text())
        self.assertEqual(payload['event'], 'before')
        self.assertIsNone(payload['last_run'])

    def test_symlink_session_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            (self.root / '.auto/unsafe').symlink_to(other, target_is_directory=True)
            self.assertIn('symlinks', self.cli('status', ok=False))

    def test_malformed_log_stops_writes(self):
        with (self.root / '.auto/log.jsonl').open('a') as stream:
            stream.write('{broken\n')
        self.assertIn('Malformed log', self.cli('begin', '--hypothesis', 'test', ok=False))

    def test_deleted_file_is_restored_on_discard(self):
        self.write('.auto/measure.sh', 'echo "METRIC ms=10"\n')
        self.baseline()
        self.begin()
        (self.root / 'value.txt').unlink()
        self.cli('run')
        self.log('discard')
        self.assertEqual((self.root / 'value.txt').read_text(), '10\n')

    def test_literal_pathspec_filenames_are_not_expanded(self):
        self.cli('init', '--new-segment', '--name', 'literal paths', '--metric', 'ms',
                 '--scope', ':special name.txt', '--max-iterations', '2')
        self.begin()
        self.write(':special name.txt', 'literal\n')
        self.cli('run')
        self.log()
        self.assertEqual(self.git('show', '--format=', '--name-only', 'HEAD'), ':special name.txt')
        self.assertEqual((self.root / 'other.txt').read_text(), 'preserve\n')

    def test_recovery_completes_discard_after_log_failure(self):
        self.baseline()
        self.begin()
        self.write('value.txt', '12\n')
        self.cli('run')
        session = ar.Session(self.root)
        args = type('Args', (), dict(status='discard', description='slower', learned='overhead', next_action='cache', allow_equal=False))()
        with mock.patch.object(session, 'append', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                session.log_result(args)
        self.assertEqual((self.root / 'value.txt').read_text(), '10\n')
        self.cli('recover')
        self.assertEqual(self.cli('status')['run_count'], 2)

    def test_termination_stops_benchmark_children_and_retains_journal(self):
        self.write('.auto/measure.sh', 'echo started > .auto/started\nsleep 1\necho leaked > .auto/leaked\n')
        self.begin()
        process = subprocess.Popen([sys.executable, str(RUNNER), '--project', str(self.root), 'run'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not (self.root / '.auto/started').exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue((self.root / '.auto/started').exists())
            process.terminate()
            process.communicate(timeout=5)
            time.sleep(1.1)
            self.assertFalse((self.root / '.auto/leaked').exists())
            self.assertEqual(self.cli('status')['pending']['phase'], 'running')
            self.cli('abort', '--reason', 'terminated')
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_new_segment_preserves_history_and_resets_baseline(self):
        self.baseline()
        self.init('--new-segment')
        status = self.cli('status')
        self.assertEqual(status['run_count'], 0)
        self.assertIsNone(status['baseline'])
        self.assertIn('"run": 1', (self.root / '.auto/log.jsonl').read_text())


if __name__ == '__main__':
    unittest.main()
