# Repository architecture

The reusable core is an experiment protocol: define a workload and metric, measure
candidates against a baseline, apply correctness backpressure, commit useful changes,
and retain lessons from discarded ones. The runner supplies deterministic mechanics;
skills supply the research strategy.

## Components

| Surface | Responsibility and relevant invariants |
| --- | --- |
| `scripts/autoresearch.py` | CLI, runtime state, benchmark execution, result logging, Git effects, dashboards, and guarded continuation. |
| `scripts/parity.py` | Shared session state, controls, summaries, path resolution, and confidence calculations. |
| `hooks/dispatch.sh` | Native lifecycle hook entrypoint and event dispatch. |
| `skills/autoresearch` | Infer domain, establish branch and benchmark, maintain prompt/ideas, annotate results with actionable side information (ASI), and continue the loop. |
| `skills/autoresearch-finalize` | Group results into independent branches using a shell helper and reject shared-file groups. |
| `skills/autoresearch-hooks` | Author optional lifecycle scripts; examples include research, reflection, journaling, and notifications. |
| `assets/full-dashboard.html` | Adapted upstream interactive report used by the full offline/live dashboard. |
| `tests/` | Disposable-repository tests for measurement, Git transactions, recovery, lifecycle guards, dashboards, security boundaries, finalization, and the Pi parity contract. |

### Execution and persistence

`init_experiment` appends metric configuration; reinitialization resets the baseline
without erasing history. `run_experiment` invokes the benchmark script when present,
parses structured `METRIC` output, records wall time, and optionally runs checks with
a separate timeout. `log_experiment` enforces the check gate, tracks secondary metrics
and ASI, commits on keep, appends the log, and reverts rejected code changes while
preserving session artifacts. Hooks fire around iteration boundaries.

Runtime state is per Codex task. An activation record distinguishes entering a loop
from merely finding a log in another working directory. Explicit off persists. Resume
scheduling waits for Codex to settle, avoids pending user input, and has turn/failure
ceilings; it is more involved than a simple “loop forever” instruction. Compaction
reconstructs context from durable files.

Terminal widgets/fullscreen views and a browser dashboard present the same results.
The optional workingDir configuration redirects experiment files, shell, and Git to
a different project while configuration is anchored to the Codex task directory.

### Design decisions

The existing code's broad `git add -A` and checkout/clean rollback assume exclusive
ownership of the working tree. That is a poor default for a shared Codex workspace.
The runner uses durable pending transactions and gates successful logging on completed
Git actions, so interrupted commits cannot silently produce false journal entries.

The confidence score divides best improvement by median absolute deviation across
experiments. Those samples combine implementation changes and noise; they are not
repeated measurements of a fixed implementation. The score is advisory, and repeated
fixed-workload measurements are recommended rather than treating it as statistical
confidence.

The implementation keeps Git ownership inside `log`, uses durable transaction state,
and keeps optional shortcuts out of the core workflow. Documentation follows those
transaction semantics.

The finalization helper checks out files from group endpoints. A deletion-aware patch
workflow is more appropriate for the native finalization skill. Disjoint file groups
still need independent correctness validation because code dependencies can cross files.

## Codex architecture

```text
Codex autoresearch skill (hypotheses, edits, interpretation, stopping)
    -> normal sandboxed shell execution
        -> Python runner (measurement + evidence + guarded Git transaction)
            -> .auto/prompt.md, ideas.md, measure.sh, checks.sh
            -> codex.json, pending.json, log.jsonl, runs/<id>/*.log
Codex finalization skill -> native Git/worktrees + reviewable measured changes
Codex hooks skill -> opt-in project scripts called by the runner
```

Native Codex plugins can package skills and lifecycle hooks; an MCP server is
unnecessary when the workflow is local and already has shell execution. The plugin manifest follows the
bundled plugin-creator schema. Official background on the packaging model:
[OpenAI plugin documentation](https://learn.chatgpt.com/docs/plugins) and
[skill documentation](https://learn.chatgpt.com/docs/build-skills).

`begin` persists a clean base before source edits. `run` fingerprints the measured
source and protocol, executes the fixed benchmark, validates finite unique metrics,
and checks correctness. `log` verifies unchanged source, scope, HEAD, index, and
protocol; it records its intent, commits or restores only recorded files, then
appends the result. `recover` verifies an interrupted finalization before completing
its log once; `abort` archives an interrupted attempt without changing source.

Using explicit `--project` avoids accidental execution from an installed plugin
cache. Binding the session to its branch prevents applying state to another branch.
The OS lock serializes helper invocations; it does not claim to serialize user edits.

### Feature scope

The implementation supplies native lifecycle hooks for owning-task continuation,
interruption, and context restoration after compaction; secondary schema validation and
free-form ASI; advisory confidence; workingDir; session off/resume/archived clear;
HTML/live/terminal dashboards; and deterministic independent-branch finalization.

The dashboard is local and read-only, with token-protected loopback HTTP and no external
assets. It reads atomic pending-state updates without holding the runner's experiment lock.
The native Interrupt hook uses a separate persistent stop marker, so it can stop further
work without waiting for a long benchmark to release its lock. Only an explicit init/resume
clears that marker. Continuation hooks cannot approve tools or expand filesystem permissions.

This standalone repository contains the plugin manifest, skills, runner, hooks, and tests
at its root. CI runs on Linux and macOS. `PARITY.md` records the reviewed upstream
version, portable feature mapping, native adaptations, and intentionally Pi-specific exclusions.

Additional options permit explicit tradeoff keeps, agent-supplied measured metrics, and
repository-wide source scope. See README for flags; strict metric validation remains the default.
