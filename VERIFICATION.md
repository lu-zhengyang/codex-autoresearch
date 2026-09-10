# Functional verification

The portable research capabilities are implemented in this repository; see
FEATURES.md for the command and capability guide.

## Automated checks

The automated suite covers measured Git transactions, keep/discard/check failure,
timeouts, recovery, metric schema and confidence, arbitrary ASI, manual metrics,
justified tradeoff keeps, repository scope, session/segment controls, dashboards,
finalization, lifecycle guards, and long compaction context. Plugin manifest
validation also passes.

## Real host checks

The dedicated Codex task tested baseline/improvement/regression/failed correctness, rollback, budget exhaustion, native context injection, two native Stop continuations, final budget deactivation, and a real user interruption. Seven total experiments were run across two explicit budgets; no extra experiment was used for compaction.

The final compaction test used the installed Codex app-server protocol and an ephemeral session over a copy of the completed fixture. Native receipts show SessionStart(startup), UserPromptSubmit, SessionStart(compact), and UserPromptSubmit. The pre-compaction model reported the compact label absent; the post-compaction model reported it visible and correctly restored goal, zero remaining budget, and no pending experiment. No hook handler was called directly, no trust bypass was used, and the original research task was left unchanged. Reduced evidence is in tests/evidence/compaction.json.

## End-to-end optimization exercise

On September 10, 2026, the committed plugin at `c1f091e` optimized a real
disposable Python workload through four runner-managed experiments. It replaced an
O(n²) equal-pair counter with `collections.Counter`, reducing the median runtime from
602.030292 ms to 0.322875 ms (**1,864.6× faster; 99.9464% lower**). An intermediate
sort-based improvement was kept; a plausible one-pass Python dictionary alternative
measured 0.869875 ms and was discarded. The runner restored the Counter implementation,
all correctness checks passed, the Git tree remained clean, the four-run budget
deactivated the session, no transaction remained pending, and a full dashboard was
exported. Reduced evidence is in `tests/evidence/optimization-e2e.json`.

## Scope of the conclusion

This verifies the key workflow on the tested local Codex host. It is not a
certification of every Codex version, external notification service, OS, or every
possible benchmark.

Manual compaction delivery was observed. The handler treats source=compact identically regardless of trigger; automatic threshold compaction was not separately forced. Longer rules/ideas are retained and use host overflow handling instead of silent plugin truncation.
