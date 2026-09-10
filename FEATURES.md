# Feature guide

The plugin provides a durable, branch-bound optimization workflow for Codex.

| Capability | Implementation |
| --- | --- |
| Session initialization and metric direction/unit | `init` with persistent `.auto/codex.json` configuration. |
| New measurement segments | `init --new-segment`, retaining prior journal entries. |
| Fixed or arbitrary benchmarks | `run` and `run --command`, with wall time, output capture, and timeouts. |
| Primary and secondary metrics | Strict finite `METRIC name=number` parsing and schema validation. |
| Agent-supplied measurements | `run --manual-metrics` with `log --metrics-file`. |
| Correctness backpressure | Optional `.auto/checks.sh`; failed checks cannot be kept. |
| Keep, discard, crash, and failed-check results | `log --status` with guarded Git commits and rollback. |
| Tradeoff keeps | `log --keep-reason` records why an equal or worse result is retained. |
| Structured annotations | `log --asi-file` stores arbitrary JSON side information. |
| Assumption-aware revisits | `log --revisits-run N` validates and labels targeted retries of earlier discards; the skill prompts a revisit check after every result. |
| Advisory confidence | Improvement divided by median absolute deviation after sufficient positive measurements. |
| Current and legacy session layouts | New sessions use `.auto/`; existing flat `autoresearch.*` sessions continue in place unless a current-layout protocol exists. |
| Session controls | `resume`, `off`, `clear`, and `clear --delete-history`. |
| Native lifecycle hooks | Session start, prompt submission, stop, interrupt, and compaction context restoration. |
| Dashboards | Offline HTML, token-protected live loopback server, terminal view, filters, charts, JSON, and PNG share cards. |
| Independent finalization | `scripts/finalize.py` creates disjoint review branches and verifies their union. |
| Recovery | Durable pending intent and `recover`/`abort` handling for interrupted Git actions. |

The dashboard is local and read-only. It makes no external calls and does not publish
session data. Lifecycle hooks are opt-in and cannot approve tools or expand permissions.

## Verification

The automated suite covers measurement parsing, Git transactions, rollback, checks,
timeouts, recovery, dashboards, finalization, lifecycle guards, and long context.
Native hook delivery is additionally documented in [VERIFICATION.md](VERIFICATION.md).
