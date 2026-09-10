#!/usr/bin/env python3
"""Durable experiment transactions for Codex. Python 3.9+, Git, Bash; POSIX only."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid


sys.path.insert(0, str(Path(__file__).resolve().parent))
from parity import (ParitySession, confidence, finite, hook_path, options, project_root, reconstruct,
                    secondary_definitions, session_artifact, session_layout, session_path)


class ResearchError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ResearchError(message)


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, allow_nan=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def git(root, *args):
    env = dict(os.environ, GIT_LITERAL_PATHSPECS='1')
    result = subprocess.run(['git', *args], cwd=root, env=env, capture_output=True)
    require(result.returncode == 0, result.stderr.decode(errors='replace').strip() or 'Git command failed')
    return result.stdout


def names(data):
    return [os.fsdecode(item) for item in data.split(b'\0') if item]


def session_file(name):
    return session_artifact(name)


def snapshot(root):
    """Fingerprint tracked and nonignored untracked files, including mode and symlink target."""
    tracked = names(git(root, 'ls-files', '-z'))
    untracked = names(git(root, 'ls-files', '--others', '--exclude-standard', '-z'))
    result = {}
    for name in sorted(set(tracked + untracked)):
        if session_file(name):
            continue
        path = root / name
        if path.is_symlink():
            result[name] = ['symlink', os.readlink(path)]
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            result[name] = [path.stat().st_mode & 0o111, digest.hexdigest()]
        elif path.exists():
            raise ResearchError('Submodules and non-file tracked paths are unsupported: ' + name)
    return result


def changed(before, after):
    return sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))


def parse_metrics(path):
    metrics = {}
    # Full raw output is on disk; only strict finite numeric records become measurements.
    pattern = re.compile(r'^METRIC\s+([\w.µ]+)=([^\s]+)\s*$')
    with path.open(errors='replace') as stream:
        for line in stream:
            match = pattern.fullmatch(line)
            if not match:
                continue
            name, raw = match.groups()
            if name in ('__proto__', 'constructor', 'prototype'):
                continue
            require(name not in metrics, 'Duplicate metric: ' + name)
            try:
                value = float(raw)
            except ValueError:
                raise ResearchError('Invalid metric: ' + name)
            require(math.isfinite(value), 'Non-finite metric: ' + name)
            metrics[name] = value
    return metrics


def execute(root, script, output, timeout, payload=None):
    start = time.monotonic()
    timed_out = False
    with output.open('wb') as stream:
        process = subprocess.Popen(['bash', str(script)], cwd=root, stdout=stream,
                                   stderr=subprocess.STDOUT, stdin=subprocess.PIPE if payload else subprocess.DEVNULL,
                                   start_new_session=True)
        try:
            process.communicate(json.dumps(payload).encode() if payload else None, timeout=timeout or None)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        except BaseException:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
        finally:
            # Do not leave background children writing output after their parent exits.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
    with output.open('rb') as stream:
        stream.seek(max(0, output.stat().st_size - 8192))
        tail = stream.read().decode(errors='replace')
    return {'exit_code': process.returncode, 'timed_out': timed_out,
            'duration_seconds': time.monotonic() - start, 'output': str(output), 'tail': tail}


class Session(ParitySession):
    def __init__(self, root):
        self.root = Path(root).resolve()
        require(self.root.is_dir(), 'Project directory does not exist')
        actual = Path(os.fsdecode(git(self.root, 'rev-parse', '--show-toplevel')).strip()).resolve()
        require(actual == self.root, '--project must be the Git working-tree root')
        self.layout = session_layout(self.root)
        self.auto = self.root / '.auto'
        require(not self.auto.is_symlink(), '.auto cannot be a symlink')
        if self.auto.exists():
            require(not any(p.is_symlink() for p in self.auto.rglob('*')), '.auto must not contain symlinks')
        self.auto.mkdir(exist_ok=True)
        self.config_path = self.auto / 'codex.json'
        self.pending_path = self.auto / 'pending.json'
        self.log = session_path(self.root, 'log', self.layout)
        self.prompt_path = session_path(self.root, 'prompt', self.layout)
        self.ideas_path = session_path(self.root, 'ideas', self.layout)
        self.measure_path = session_path(self.root, 'measure', self.layout)
        self.checks_path = session_path(self.root, 'checks', self.layout)

    @contextlib.contextmanager
    def lock(self):
        with (self.auto / 'lock').open('a') as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ResearchError('Another autoresearch command is active in this project')
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def append(self, entry):
        with self.log.open('a') as stream:
            stream.write(json.dumps(entry, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def entries(self):
        if not self.log.exists():
            return []
        entries = []
        for number, line in enumerate(self.log.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                raise ResearchError(f'Malformed log line {number}; preserve and repair it before continuing')
            require(isinstance(entry, dict), f'Invalid log line {number}')
            entries.append(entry)
        return reconstruct(entries)

    def config(self):
        require(self.config_path.exists(), 'No Codex session. Run init first')
        config = read_json(self.config_path)
        require(config['branch'] == self.branch(), 'Session belongs to another branch')
        return config

    def branch(self):
        return os.fsdecode(git(self.root, 'symbolic-ref', '--quiet', '--short', 'HEAD')).strip()

    def head(self):
        return os.fsdecode(git(self.root, 'rev-parse', 'HEAD')).strip()

    def clean(self):
        require(not git(self.root, 'diff', '--cached', '--name-only'), 'Index must be empty; preserve staged work')
        dirty = names(git(self.root, 'diff', '--name-only', '-z', 'HEAD'))
        dirty += names(git(self.root, 'ls-files', '--others', '--exclude-standard', '-z'))
        require(not [name for name in dirty if not session_file(name)],
                'Working tree must be clean outside .auto; use an isolated worktree for existing work')

    def runs(self, config):
        return [e for e in self.entries() if 'run' in e and (e.get('session_id') == config['session_id'] or
                (config.get('imported') and e.get('session_id') is None and e.get('segment') == config['segment']))]

    def status(self):
        config = self.config()
        runs = self.runs(config)
        kept = [e for e in runs if e['status'] == 'keep' and finite(e.get('metric'))]
        best = (min if config['bestDirection'] == 'lower' else max)([e['metric'] for e in kept], default=None)
        return {'config': config, 'run_count': len(runs), 'baseline': kept[0]['metric'] if kept else None,
                'best': best, 'remaining': max(0, config['maxIterations'] - len(runs)) if config['maxIterations'] is not None else None,
                'confidence': confidence(runs, config['bestDirection']),
                'secondaryMetrics': secondary_definitions(runs), 'active': self.control()['active'],
                'pending': {k: v for k, v in read_json(self.pending_path).items()
                            if k not in ('base_snapshot', 'measured_snapshot')} if self.pending_path.exists() else None,
                'recent_runs': runs[-20:]}

    def init(self, args):
        require(not getattr(args, 'auto_resume', False) or getattr(args, 'session_id', None), 'Automatic continuation requires --session-id for the owning Codex task')
        require(not self.pending_path.exists(), 'Resolve pending experiment before initializing')
        require(not self.config_path.exists() or args.new_segment, 'Session exists; use status/resume or explicit --new-segment')
        self.clean()
        tracked_session = [name for name in names(git(self.root, 'ls-files', '-z')) if session_file(name)]
        require(not tracked_session, 'Autoresearch session files must be untracked; move tracked artifacts out of Git first')
        require(not any(line.startswith(b'160000 ') for line in git(self.root, 'ls-files', '--stage').splitlines()),
                'Submodules are unsupported; select a standalone repository')
        limit = args.max_iterations if args.max_iterations is not None else options(self.root).get('maxIterations')
        require(limit is None or (type(limit) is int and limit > 0), '--max-iterations must be positive')
        require(re.fullmatch(r'[\w.µ]+', args.metric), 'Invalid metric name')
        scope = []
        for name in args.scope:
            path = Path(name)
            require(not path.is_absolute() and '..' not in path.parts and name != '', 'Scope must name relative files or directories')
            require((not path.parts or path.parts[0] not in ('.git', '.auto')), '.git and .auto are not experiment scope')
            require(not any(c in name for c in '*?['), 'Use literal scope paths, not globs')
            scope.append(path.as_posix().rstrip('/'))
        branch = self.branch()
        require(branch not in ('main', 'master'), 'Create an experiment branch first (codex/autoresearch-...)')
        entries = self.entries()
        config = {'type': 'config', 'name': args.name, 'metricName': args.metric, 'metricUnit': args.unit,
                  'bestDirection': args.direction, 'maxIterations': limit, 'scope': scope,
                  'hooks': args.hooks, 'branch': branch, 'base_commit': self.head(),
                  'session_id': uuid.uuid4().hex, 'segment': sum(e.get('type') == 'config' for e in entries)}
        self.append(config)
        write_json(self.config_path, config)
        (self.auto / 'stopped').unlink(missing_ok=True)
        self.set_control(active=True, autoResume=getattr(args, 'auto_resume', False), resumeTurns=0,
                         owner_session=getattr(args, 'session_id', None), reason=None)
        return self.status()

    def hook(self, stage, config, entry=None):
        script = hook_path(self.root, stage, self.layout)
        if not config['hooks'] or not script.is_file() or not os.access(script, os.X_OK):
            return None
        status = self.status()
        payload = {'event': stage, 'cwd': str(self.root), 'session': {
            'metric_name': config['metricName'], 'metric_unit': config['metricUnit'],
            'direction': config['bestDirection'], 'baseline_metric': status['baseline'],
            'best_metric': status['best'], 'run_count': status['run_count'], 'goal': config['name']}}
        if stage == 'before':
            payload.update(next_run=1 + max((e.get('run', 0) for e in self.entries()), default=0),
                           last_run=status['recent_runs'][-1] if status['recent_runs'] else None)
        else:
            payload['run_entry'] = entry
        result = execute(self.root, script, self.auto / ('hook-' + stage + '.output.log'), 30, payload)
        self.append({'type': 'hook', 'stage': stage, **result})
        return result

    def begin(self, args):
        config = self.config()
        require(not self.pending_path.exists(), 'An experiment is pending; inspect status and finish it first')
        require(config['maxIterations'] is None or len(self.runs(config)) < config['maxIterations'], 'Iteration budget exhausted; stop and summarize')
        require(self.control()['active'], 'Autoresearch is off; use resume to explicitly activate')
        self.clean()
        hook = self.hook('before', config)
        self.clean()
        pending = {'id': uuid.uuid4().hex, 'phase': 'editing', 'head': self.head(),
                   'base_snapshot': snapshot(self.root), 'hypothesis': args.hypothesis,
                   'session_id': config['session_id'], 'started_at': time.time()}
        write_json(self.pending_path, pending)
        return {'id': pending['id'], 'phase': 'editing', 'hook': hook}

    def pending(self):
        require(self.pending_path.exists(), 'No pending experiment; call begin before editing')
        pending = read_json(self.pending_path)
        require(pending['session_id'] == self.config()['session_id'], 'Pending experiment belongs to another session')
        return pending

    def check_head(self, pending):
        require(self.head() == pending['head'], 'HEAD changed during experiment; inspect status before recovery')
        require(not git(self.root, 'diff', '--cached', '--name-only'), 'Index changed during experiment; preserve staged work')

    def check_scope(self, pending, current, config):
        paths = changed(pending['base_snapshot'], current)
        outside = [p for p in paths if not any(s == '.' or p == s or p.startswith(s + '/') for s in config['scope'])]
        require(not outside, 'Out-of-scope changes: ' + ', '.join(outside))
        return paths

    def protocol(self):
        paths = {
            'measure': self.measure_path,
            'command': self.auto / 'command.sh',
            'checks': self.checks_path,
            'codex': self.config_path,
        }
        return {name: hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                for name, path in paths.items()}

    def run(self, args):
        config, pending = self.config(), self.pending()
        require(self.control()['active'], 'Autoresearch is off; use resume before running')
        require(pending['phase'] == 'editing', 'Experiment already measured or interrupted; inspect status')
        self.check_head(pending)
        before = snapshot(self.root)
        self.check_scope(pending, before, config)
        measure = self.measure_path
        command = getattr(args, 'shell_command', None)
        if command:
            require(not measure.exists(), 'Use the fixed .auto/measure.sh when it exists')
            measure = self.auto / 'command.sh'
            measure.write_text('set -euo pipefail\n' + command + '\n')
        require(measure.is_file(), 'Write .auto/measure.sh or provide --command before measuring')
        require(all(math.isfinite(t) and t >= 0 for t in (args.timeout, args.checks_timeout)), 'Timeouts must be finite and nonnegative (zero disables timeout)')
        folder = self.auto / 'runs' / pending['id']
        folder.mkdir(parents=True, exist_ok=True)
        pending.update(phase='running', measured_snapshot=before, protocol=self.protocol())
        write_json(self.pending_path, pending)
        benchmark = execute(self.root, measure, folder / 'benchmark.log', args.timeout)
        metrics, error = {}, None
        try:
            metrics = parse_metrics(folder / 'benchmark.log')
            require(getattr(args, 'manual_metrics', False) or config['metricName'] in metrics, 'Missing primary METRIC ' + config['metricName'])
        except ResearchError as exc:
            error = str(exc)
        checks = None
        if benchmark['exit_code'] == 0 and not benchmark['timed_out'] and error is None:
            if self.checks_path.is_file():
                checks = execute(self.root, self.checks_path, folder / 'checks.log', args.checks_timeout)
        unchanged = (snapshot(self.root) == before and self.head() == pending['head']
                     and self.protocol() == pending['protocol'])
        status = 'ok'
        if benchmark['exit_code'] != 0 or benchmark['timed_out'] or error or not unchanged:
            status = 'crash'
        elif checks and (checks['exit_code'] != 0 or checks['timed_out']):
            status = 'checks_failed'
        evidence = {'benchmark': benchmark, 'checks': checks, 'metrics': metrics,
                    'metric_error': error, 'tree_unchanged': unchanged, 'outcome': status,
                    'manual_metrics': getattr(args, 'manual_metrics', False)}
        pending.update(phase='measured', evidence=evidence)
        write_json(self.pending_path, pending)
        return {'id': pending['id'], **evidence}

    def log_result(self, args):
        config, pending = self.config(), self.pending()
        require(pending['phase'] == 'measured', 'Only measured experiments can be logged; see recovery reference')
        self.check_head(pending)
        current = snapshot(self.root)
        require(self.protocol() == pending['protocol'], 'Measurement protocol changed; remeasure in a new experiment')
        require(current == pending['measured_snapshot'], 'Files changed since measurement; preserve them and inspect before recovery')
        paths = self.check_scope(pending, current, config)
        evidence = pending['evidence']
        require(evidence['tree_unchanged'], 'Benchmark changed source files; inspect and recover manually')
        evidence = dict(evidence, metrics=dict(evidence['metrics']))
        supplied = getattr(args, 'metrics_file', None)
        if supplied:
            require(evidence.get('manual_metrics'), 'Manual metrics require run --manual-metrics')
            values = read_json(Path(supplied))
            require(isinstance(values, dict) and all(isinstance(k, str) and re.fullmatch(r'[\w.µ]+', k) and k not in ('__proto__', 'constructor', 'prototype') and finite(v) for k, v in values.items()), 'Metrics must be a JSON object of finite numbers')
            evidence['metrics'].update(values)
            evidence['metric_source'] = 'agent-supplied'
        expected = evidence['outcome']
        if expected == 'ok':
            require(finite(evidence['metrics'].get(config['metricName'])), 'Supply the primary metric with --metrics-file')
        require((expected == 'ok' and args.status in ('keep', 'discard')) or args.status == expected,
                'Status conflicts with evidence: ' + expected)
        metric = evidence['metrics'].get(config['metricName'])
        previous = self.status()
        secondary = {k: v for k, v in evidence['metrics'].items() if k != config['metricName']}
        known = {d['name'] for d in previous['secondaryMetrics']}
        if expected == 'ok' and known:
            require(not known - secondary.keys(), 'Missing secondary metrics: ' + ', '.join(sorted(known - secondary.keys())))
            require(not secondary.keys() - known or getattr(args, 'force', False), 'New secondary metrics require --force')
        if args.status == 'keep' and previous['best'] is not None:
            improved = metric < previous['best'] if config['bestDirection'] == 'lower' else metric > previous['best']
            require(improved or (metric == previous['best'] and args.allow_equal) or getattr(args, 'keep_reason', None),
                    'Keep requires improvement (or --allow-equal / --keep-reason for a justified tradeoff)')
        asi = {'hypothesis': pending['hypothesis'], 'learned': args.learned}
        if getattr(args, 'keep_reason', None):
            asi['keep_reason'] = args.keep_reason
        if supplied:
            asi['metric_source'] = 'agent-supplied'
        if getattr(args, 'asi_file', None):
            extra = read_json(Path(args.asi_file))
            require(isinstance(extra, dict), '--asi-file must contain a JSON object')
            json.dumps(extra, allow_nan=False)
            asi.update(extra)
        if getattr(args, 'revisits_run', None) is not None:
            asi['revisits_run'] = args.revisits_run
        revisits_run = asi.get('revisits_run')
        if revisits_run is not None:
            require(type(revisits_run) is int and revisits_run > 0,
                    'revisits_run must be a positive integer')
            prior = next((row for row in self.runs(config) if row.get('run') == revisits_run), None)
            require(prior is not None and prior.get('status') == 'discard',
                    'revisits_run must reference an earlier discarded experiment in this segment')
        if args.status != 'keep':
            require(args.next_action, 'Rejected experiments require --next-action')
            asi.update(rollback_reason=args.description, next_action_hint=args.next_action)
        entry = {'run': 1 + max((e.get('run', 0) for e in self.entries()), default=0),
                 'id': pending['id'], 'session_id': config['session_id'], 'segment': config['segment'],
                 'metric': metric, 'metrics': {k: v for k, v in evidence['metrics'].items() if k != config['metricName']},
                 'status': args.status, 'description': args.description, 'asi': asi,
                 'timestamp': int(time.time() * 1000), 'commit': pending['head'], 'confidence': None,
                 'evidence': evidence, 'changed_files': paths}
        entry['confidence'] = confidence(self.runs(config) + [entry], config['bestDirection'])
        # Durable intent before mutating Git. Interrupted finalization fails closed, never auto-replays.
        pending.update(phase='finalizing', intended_entry=entry)
        write_json(self.pending_path, pending)
        if args.status == 'keep' and paths:
            git(self.root, 'add', '-A', '--', *paths)
            git(self.root, 'commit', '-m', args.description, '-m',
                'Autoresearch: ' + pending['id'] + '\nResult: ' + json.dumps({'metric': metric, 'status': args.status}))
            require(snapshot(self.root) == current, 'Commit hook changed measured files; recover pending transaction')
            entry['commit'] = self.head()
            require(os.fsdecode(git(self.root, 'rev-parse', 'HEAD^')).strip() == pending['head'], 'Commit changed the expected Git ancestry')
            committed = names(git(self.root, 'diff-tree', '--no-commit-id', '--name-only', '-r', '-z', 'HEAD'))
            require(set(committed) == set(paths), 'Commit contains unexpected paths; inspect pending transaction')
            self.clean()
        elif args.status != 'keep':
            tracked = set(names(git(self.root, 'ls-files', '-z')))
            restore = [p for p in paths if p in tracked]
            if restore:
                git(self.root, 'restore', '--source=' + pending['head'], '--worktree', '--', *restore)
            for name in paths:
                if name not in tracked:
                    (self.root / name).unlink()  # Only captured untracked files; never git clean.
            require(snapshot(self.root) == pending['base_snapshot'], 'Rollback differs from recorded base; inspect pending transaction')
        self.append(entry)
        self.pending_path.unlink()
        hook = self.hook('after', config, entry)
        remaining = previous['remaining'] - 1 if previous['remaining'] is not None else None
        result = {'entry': entry, 'remaining': remaining, 'hook': hook}
        if remaining == 0:
            self.set_control(active=False, reason='Iteration budget exhausted')
            result['stop_reason'] = 'Iteration budget exhausted'
        else:
            result['next_iteration_guidance'] = (
                "Before choosing the next experiment, consider whether this result or discovery "
                "invalidates a previous discard's rollback reason. If so, name the changed "
                "assumption and weigh a targeted retry against other candidates. Use "
                "--revisits-run N for an intentional retry; verification reruns for measurement "
                "noise are not revisits."
            )
        return result

    def recover(self, args):
        """Complete a journal write only after independently verifying the Git result."""
        pending = self.pending()
        require(pending['phase'] == 'finalizing', 'Recovery is only for interrupted finalization; use abort for interrupted runs')
        entry = pending['intended_entry']
        existing = [e for e in self.entries() if e.get('id') == pending['id'] and 'run' in e]
        require(not git(self.root, 'diff', '--cached', '--name-only'), 'Index is staged; inspect Git failure before recovery')
        if entry['status'] == 'keep':
            require(snapshot(self.root) == pending['measured_snapshot'], 'Kept tree differs from measurement')
            if entry['changed_files']:
                require(os.fsdecode(git(self.root, 'rev-parse', 'HEAD^')).strip() == pending['head'], 'Kept commit must directly follow recorded base')
                require('Autoresearch: ' + pending['id'] in os.fsdecode(git(self.root, 'log', '-1', '--format=%B')), 'HEAD is not the recorded experiment commit')
                committed = names(git(self.root, 'diff-tree', '--no-commit-id', '--name-only', '-r', '-z', 'HEAD'))
                require(set(committed) == set(entry['changed_files']), 'Recovered commit contains unexpected paths')
                self.clean()
            else:
                require(self.head() == pending['head'], 'Baseline HEAD changed')
            entry['commit'] = self.head()
        else:
            require(self.head() == pending['head'], 'Discard HEAD changed')
            require(snapshot(self.root) == pending['base_snapshot'], 'Rollback is incomplete; restore only recorded experiment paths before recovery')
        if not existing:
            self.append(entry)
        self.pending_path.unlink()
        return {'recovered': entry, 'message': 'After hook was not replayed; inspect hook log before any manual side effects'}

    def abort(self, args):
        """Record interruption without performing Git operations or deleting source files."""
        config, pending = self.config(), self.pending()
        require(pending['phase'] != 'finalizing', 'Finalization interrupted; inspect Git and journal manually (recovery reference)')
        self.append({'type': 'aborted', 'id': pending['id'], 'session_id': config['session_id'],
                     'reason': args.reason, 'hypothesis': pending['hypothesis'], 'timestamp': int(time.time() * 1000)})
        archive = self.auto / 'runs' / pending['id']
        archive.mkdir(parents=True, exist_ok=True)
        self.pending_path.replace(archive / 'aborted.json')
        return {'aborted': pending['id'], 'message': 'Source files retained. Restore only your experiment changes before begin.'}


def terminate(_signum, _frame):
    raise SystemExit(143)


def main():
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='Explicit Git working-tree root; never inferred from plugin location')
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--name', required=True)
    init.add_argument('--metric', required=True)
    init.add_argument('--unit', default='')
    init.add_argument('--direction', choices=['lower', 'higher'], default='lower')
    init.add_argument('--scope', action='append', required=True)
    init.add_argument('--max-iterations', type=int, help='Budget including baseline; defaults to config.json or unlimited')
    init.add_argument('--new-segment', action='store_true')
    init.add_argument('--auto-resume', action='store_true')
    init.add_argument('--session-id', default=os.environ.get('CODEX_THREAD_ID'))
    init.add_argument('--hooks', action='store_true', help='Enable reviewed project lifecycle scripts')
    begin = sub.add_parser('begin')
    begin.add_argument('--hypothesis', required=True)
    run = sub.add_parser('run')
    run.add_argument('--command', dest='shell_command', help='Shell command; accepted only without a fixed measure.sh')
    run.add_argument('--manual-metrics', action='store_true', help='Allow logging externally extracted metrics; checks still run')
    run.add_argument('--timeout', type=float, default=600)
    run.add_argument('--checks-timeout', type=float, default=300)
    log = sub.add_parser('log')
    log.add_argument('--status', required=True, choices=['keep', 'discard', 'crash', 'checks_failed'])
    log.add_argument('--description', required=True)
    log.add_argument('--learned', required=True)
    log.add_argument('--next-action')
    log.add_argument('--asi-file')
    log.add_argument('--revisits-run', type=int,
                     help='Earlier discarded run intentionally retried because its assumptions changed')
    log.add_argument('--metrics-file', help='JSON metric map for a run measured with --manual-metrics')
    log.add_argument('--keep-reason', help='Keep an equal or worse metric for this explicit tradeoff reason')
    log.add_argument('--force', action='store_true', help='Accept new secondary metric names')
    log.add_argument('--allow-equal', action='store_true')
    abort = sub.add_parser('abort')
    abort.add_argument('--reason', required=True)
    sub.add_parser('status')
    sub.add_parser('recover')
    sub.add_parser('off')
    clear = sub.add_parser('clear')
    clear.add_argument('--delete-history', action='store_true', help='Delete current session history instead of archiving')
    sub.add_parser('summary')
    resume = sub.add_parser('resume')
    resume.add_argument('--auto-resume', action='store_true')
    resume.add_argument('--session-id', default=os.environ.get('CODEX_THREAD_ID'))
    export = sub.add_parser('export')
    export.add_argument('--full', action='store_true', help='Full interactive dashboard with PNG share-card export')
    export.add_argument('--output', help='Default .auto/dashboard.html')
    dashboard = sub.add_parser('dashboard')
    dashboard.add_argument('--full', action='store_true')
    dashboard.add_argument('--port', type=int, default=0)
    display = dashboard.add_mutually_exclusive_group()
    display.add_argument('--terminal', action='store_true')
    display.add_argument('--serve', action='store_true', help='Serve an auto-refreshing loopback dashboard')
    args = parser.parse_args()
    try:
        if args.command == 'init' and args.max_iterations is None:
            args.max_iterations = options(args.project).get('maxIterations')
        session = Session(project_root(args.project))
        if args.command == 'off':
            print(json.dumps(session.off(args)))
            return 0
        if args.command == 'dashboard' and args.terminal:
            from dashboard import terminal
            terminal(session)
            return 0
        if args.command == 'dashboard' and args.serve:
            from dashboard import serve
            serve(session, args.port, full=args.full)
            return 0
        with session.lock():
            methods = {'init': session.init, 'begin': session.begin, 'run': session.run,
                       'log': session.log_result, 'abort': session.abort, 'recover': session.recover, 'off': session.off, 'resume': session.resume,
                       'clear': session.clear, 'summary': session.summary}
            if args.command in ('export', 'dashboard'):
                from dashboard import export
                result = export(session, getattr(args, 'output', None), full=args.full)
            else:
                result = session.status() if args.command == 'status' else methods[args.command](args)
        print(json.dumps(result, allow_nan=False, indent=2))
    except (ResearchError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
