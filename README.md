# Autoresearch for Codex

A native Codex plugin for autonomous code optimization: form a hypothesis, edit,
benchmark, check correctness, keep improvements, discard regressions, and persist
what was learned. MIT licensed.

The plugin provides Codex skills, native lifecycle hooks, a deterministic Python
runner, live browser/terminal dashboards, and independent-branch finalization.
It requires Python 3.9+, Git 2.23+, and Bash on macOS/Linux. No external service,
separate API key, or Python packages are required for the core workflow.
Optional example hooks may require jq or the service/tool named in their headers.

See the [feature guide](FEATURES.md) for supported behavior, the [Pi parity audit](PARITY.md)
for the v1.8.1 mapping and exclusions, and the [architecture notes](ARCHITECTURE.md)
for the design and implementation decisions.

## Installation

The installable root contains `.codex-plugin/plugin.json`. Its registered personal
marketplace source is conventionally `~/plugins/autoresearch`, separate from this
Git repository. After the source copy and personal marketplace have been registered:

```bash
codex plugin add autoresearch@personal
```

Start a new task to load updated skills/hooks. **Review and trust the new hooks** in
Codex's `/hooks` CLI interface to enable automatic continuation and compaction context.
Codex skips untrusted hooks; direct runner commands still work. The plugin never
modifies trust records or approval policy. [Official hook requirements](https://learn.chatgpt.com/docs/hooks).

Example requests:

- “Use autoresearch to reduce parser runtime for 10 experiments. Keep tests passing.”
- “Resume autoresearch and continue until I interrupt it.”
- “Show the live experiment dashboard.”
- “Finalize the kept experiments into independent review branches.”

Skills: `autoresearch`, `autoresearch-finalize`, `autoresearch-hooks`.

## Runner

Resolve paths explicitly:

```text
python3 /absolute/plugin/scripts/autoresearch.py --project /absolute/session-root COMMAND
```

| Command | Purpose |
| --- | --- |
| `init --name GOAL --metric NAME --scope PATH [--max-iterations N]` | Configure primary metric and editable literal paths; repeat --scope as needed. Use --direction higher/lower and --unit. |
| `begin --hypothesis TEXT` | Record a clean base before editing. |
| `run [--timeout 600] [--checks-timeout 300]` | Measure the candidate and run optional correctness checks. |
| `run --command TEXT` | Run a command only when no fixed measure.sh exists. |
| `log --status STATUS --description TEXT --learned TEXT` | Commit or roll back captured paths and append evidence; rejected results need --next-action. Add `--revisits-run N` when a changed assumption justifies retrying discard N. |
| `status` / `summary` | Inspect metrics/state or generate a durable research checkpoint. |
| `off` / `resume` | Persistently stop or explicitly reactivate research. |
| `clear` | Archive log/config/control and reset; retain benchmark, ideas, and source. |
| `abort --reason TEXT` / `recover` | Preserve interrupted evidence or verify and finish a Git transaction. |
| `export [--output PATH]` | Write self-contained HTML. |
| `dashboard --serve [--port N]` | Serve a live, read-only, token-protected loopback dashboard. |
| `dashboard --terminal` | Open a live scrolling fullscreen terminal view. |

`init --new-segment` changes the workload/measurement target without erasing history.
`log --asi-file PATH` adds arbitrary JSON insights. `log --revisits-run N` marks an
intentional retry of an earlier discard after its rollback assumption changed; the
runner validates the reference and dashboards display it. `log --force` permits a newly
introduced secondary metric; established names must remain present for valid runs.
The runner parses metrics itself; agents cannot override measurements.

Budget includes baseline. Omitting --max-iterations uses `.auto/config.json`'s
maxIterations, or unlimited when neither supplies a cap. A session root's workingDir
redirects experiment files, execution, and Git to that resolved project. The `.auto/` directory is the default source of truth. Existing flat
`autoresearch.*` sessions are read and updated in place when no current-layout
session artifact exists; once any current `.auto/` protocol file exists, stale legacy
peers are ignored.

`run` returns JSON even for a failed benchmark: inspect `outcome` (`ok`, `crash`, or
`checks_failed`), not only the CLI exit code. Validation errors return nonzero.

## Session files

- `.auto/prompt.md`: objective, fixed workload, metrics, scope, constraints, findings.
- `.auto/measure.sh`: Bash with `set -euo pipefail`; emits unique `METRIC name=number` lines.
- `.auto/checks.sh`: optional correctness gate with real propagated exit status.
- `.auto/ideas.md`: hypotheses and dead ends.
- `.auto/log.jsonl`: append-only configs, results, and lifecycle events.
- `.auto/codex.json`, `control.json`, `pending.json`: branch/config, activation, transaction state.
- `.auto/runs/`: raw measurement/check output and interrupted-attempt evidence.
- `.auto/hooks/before.sh`, `after.sh`: optional reviewed per-iteration scripts.

Keep session files out of source commits. Establish a clean experiment worktree and
branch; the runner refuses dirty initial source/index. Scope paths are literal files
or directories. A rejected experiment restores only its recorded paths; ignored build
products and external datasets remain outside rollback and must be controlled by the
measurement protocol. Submodules and symlinked session artifacts are unsupported.

The confidence field is an improvement/MAD heuristic after sufficient positive
measurements. It is advisory, **not a statistical confidence interval**.
Repeat noisy benchmarks to validate marginal gains.

## Native continuation

For an authorized autonomous loop, add `--auto-resume --session-id "$CODEX_THREAD_ID"`
to init or resume (the CLI also reads CODEX_THREAD_ID by default). If the host does not
provide this environment variable, pass its actual task/session ID explicitly.

Bundled hooks restore context at SessionStart, including after compaction, and at
UserPromptSubmit. Stop requests continuation only for the owning task and only after
experiment progress. Interrupt writes an immediate persistent stop marker. Guards
stop at the budget, 200 continuations, >20 consecutive rejected/failed results, recovery
states, or no progress. Nothing runs automatically just because a project has a log.

The hooks do not execute experiments or start a separate agent; Codex continues the
active task using the skills. Terminal/browser dashboards are standalone views, not
widgets inserted into Codex's composer. [Recovery details](skills/autoresearch/references/recovery.md).

## Finalization

Write `.auto/groups.json` with a base commit, goal slug, and groups containing title,
body, slug, and exact files. Ordered `last_commit` group endpoints are also accepted.

```text
python3 /absolute/plugin/scripts/finalize.py --project /absolute/project --plan /absolute/project/.auto/groups.json
```

Preflight is read-only. Add `--apply` to create branches; add `--check-command TEXT` to
validate each branch independently. The helper preserves binary files, deletions, and
modes; rejects overlapping/incomplete groups; and verifies that actual branch patches
combine to the final source tree. Failures retain worktrees and a report for inspection.
No source checkout switch, push, or merge occurs.

## Development

```bash
python3 -m unittest discover -s tests -v
```

Tests use disposable repositories, real commands, hook event payloads, and local HTTP.
CI runs on Linux and macOS. The implementation is self-contained.

## Additional options

- `init --scope .` covers all nonignored source paths in the repository. Session artifacts remain excluded; each iteration must begin clean.
- `log --keep-reason "tradeoff justification"` can keep an equal or worse primary metric. The journal retains the justification and the historical best remains unchanged.
- `run --manual-metrics`, followed by `log --metrics-file /absolute/metrics.json`, accepts externally extracted primary and secondary values, for example `{"latency_ms": 12, "memory_mb": 40}`. Log actual measurements; the journal marks them agent-supplied. Correctness failures still block keeping.
- Metric output is strict: each metric name must occur once and every value must be finite. Invalid or duplicate records fail the run.
- `run --timeout 0` / `--checks-timeout 0` disables the respective timeout.
- `clear --delete-history` deletes the active session history instead of creating an archive. Existing archives are untouched.
- `export --full` / `dashboard --serve --full` uses the interactive chart and PNG share-card exporter. The full view shows the current segment; the compact view includes segment/status filters and secondary metrics.

The runner does not export an active process or in-memory experiment transaction. An unfinished candidate must be resolved or remeasured in the target worktree.
