#!/usr/bin/env python3
"""Create independent deletion-aware research branches; preserve the source checkout."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
from autoresearch import Session, names, session_file, write_json, execute
from parity import git, project_root, require


def prepare(session, plan):
    require(not session.pending_path.exists(), 'Resolve pending experiment before finalizing')
    base = git(session.root, 'rev-parse', '--verify', str(plan['base']) + '^{commit}').decode().strip()
    final = git(session.root, 'rev-parse', '--verify', str(plan.get('final_tree', 'HEAD')) + '^{commit}').decode().strip()
    require(final == session.head(), 'final_tree must match current experiment HEAD')
    git(session.root, 'merge-base', '--is-ancestor', base, final)
    goal = plan['goal']
    require(re.fullmatch('[a-z0-9][a-z0-9-]*', goal) is not None, 'Invalid goal slug')
    groups = plan['groups']
    require(isinstance(groups, list) and groups, 'At least one group is required')
    total = set(p for p in names(git(session.root, 'diff', '--name-only', '--no-renames', '-z', base, final)) if not session_file(p))
    seen, prepared, previous = set(), [], base
    for index, group in enumerate(groups, 1):
        slug = group['slug']
        require(re.fullmatch('[a-z0-9][a-z0-9-]*', slug) is not None, 'Invalid group slug')
        require(isinstance(group.get('title'), str) and group['title'].strip(), 'Each group needs a title')
        if 'files' in group:
            paths = group['files']
        else:
            endpoint = git(session.root, 'rev-parse', '--verify', group['last_commit'] + '^{commit}').decode().strip()
            git(session.root, 'merge-base', '--is-ancestor', previous, endpoint)
            git(session.root, 'merge-base', '--is-ancestor', endpoint, final)
            paths = [p for p in names(git(session.root, 'diff', '--no-renames', '--name-only', '-z', previous, endpoint)) if not session_file(p)]
            previous = endpoint
        require(isinstance(paths, list) and paths and all(isinstance(p, str) for p in paths), 'Group files must be a nonempty list')
        require(len(paths) == len(set(paths)), 'Duplicate file within group')
        require(not (set(paths) & seen), 'Groups overlap; merge groups sharing files')
        require(set(paths) <= total, 'Group contains unchanged paths or session artifacts')
        seen.update(paths)
        branch = f'codex/{goal}/{index:02d}-{slug}'
        exists = subprocess.run(['git', 'show-ref', '--verify', '--quiet', 'refs/heads/' + branch], cwd=session.root).returncode == 0
        require(not exists, 'Branch already exists: ' + branch)
        patch = git(session.root, 'diff', '--binary', '--no-renames', base, final, '--', *paths)
        prepared.append({'branch': branch, 'files': paths, 'patch': patch, 'title': group['title'], 'body': group.get('body', '')})
    require(seen == total, 'Groups do not cover all source changes: ' + ', '.join(sorted(total - seen)))
    return base, final, prepared


def finalize(session, plan, apply=False, check_command=None):
    with session.lock():
        base, final, groups = prepare(session, plan)
        report = {'base': base, 'final_tree': final, 'groups': [{k: v for k, v in group.items() if k != 'patch'} for group in groups]}
        if not apply:
            return dict(report, dry_run=True)
        folder = session.auto / 'finalize' / uuid.uuid4().hex
        folder.mkdir(parents=True)
        report['work_directory'] = str(folder)
        report['completed'] = []
        write_json(folder / 'report.json', report)
        try:
            for index, group in enumerate(groups):
                work = folder / str(index + 1)
                git(session.root, 'worktree', 'add', '-b', group['branch'], str(work), base)
                git(work, 'apply', '--index', '--binary', '-', data=group['patch'])
                git(work, 'commit', '-m', group['title'], '-m', group['body'])
                check_result = None
                if check_command:
                    check_script = folder / 'checks.sh'
                    check_script.write_text('set -euo pipefail\n' + check_command + '\n')
                    check_result = execute(work, check_script, folder / f'checks-{index + 1}.log', 300)
                    require(check_result['exit_code'] == 0 and not check_result['timed_out'], 'Independent branch checks failed: ' + group['branch'])
                require(not git(work, 'status', '--porcelain'), 'Validation modified a finalized worktree')
                report['completed'].append({'branch': group['branch'], 'worktree': str(work), 'checks': check_result})
                write_json(folder / 'report.json', report)
            # Verify actual created branch patches in a separate index, without switching source HEAD.
            with tempfile.TemporaryDirectory(prefix='autoresearch-union-') as temp:
                env = dict(os.environ, GIT_INDEX_FILE=str(Path(temp) / 'index'), GIT_LITERAL_PATHSPECS='1')
                def index_git(*args, data=None):
                    result = subprocess.run(['git', *args], cwd=session.root, env=env, input=data, capture_output=True)
                    require(result.returncode == 0, result.stderr.decode(errors='replace'))
                    return result.stdout
                index_git('read-tree', base)
                for group in groups:
                    actual_patch = git(session.root, 'diff', '--binary', '--no-renames', base, group['branch'])
                    index_git('apply', '--cached', '--binary', '-', data=actual_patch)
                tree = index_git('write-tree').decode().strip()
                differences = names(git(session.root, 'diff', '--name-only', '-z', tree, final))
                require(not [p for p in differences if not session_file(p)], 'Union of branches does not match research source')
            report['union_verified'] = True
        except BaseException as exc:
            report['error'] = str(exc)
            write_json(folder / 'report.json', report)
            raise ValueError(f'Finalization stopped; created branches/worktrees preserved. Inspect {folder / "report.json"}: {exc}')
        write_json(folder / 'report.json', report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--check-command')
    args = parser.parse_args()
    try:
        result = finalize(Session(project_root(args.project)), json.loads(Path(args.plan).read_text()), args.apply, args.check_command)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({'error': str(exc)})); return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
