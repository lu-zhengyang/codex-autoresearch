# Pi → Codex feature parity

This port was reviewed against `pi-autoresearch` **v1.8.1** at commit
`703a8f1` (September 8, 2026). The upstream checkout used for the review is
`../pi-autoresearch`.

The invariant being ported is not Pi's TypeScript extension API. It is the
research protocol:

1. define a fixed workload, primary metric, direction, scope, and constraints;
2. capture a clean candidate base before editing;
3. measure the candidate and retain complete raw evidence;
4. run correctness checks outside the primary measurement;
5. keep improvements as Git commits and restore rejected candidates;
6. preserve structured learnings, including conditions that can invalidate an
   earlier discard;
7. reconstruct state after restarts/compaction and continue only while the user
   authorization, budget, and safety guards permit it;
8. expose the same journal through compact, full, live, and terminal reports;
9. finalize useful changes into reviewable, independently verified branches.

## Portable behavior

| Upstream behavior | Native Codex implementation | Evidence |
| --- | --- | --- |
| `init_experiment` session name, metric, unit, direction, and re-init segments | `scripts/autoresearch.py init`, `--new-segment`, `.auto/codex.json`, config entries in `.auto/log.jsonl` | `test_new_segment_preserves_history_and_resets_baseline`, `test_higher_direction_zero_and_budget` |
| Configurable `maxIterations` and `workingDir` | CLI/config budget and `parity.project_root` | `test_unlimited_and_config_budget`, `test_workingdir_configuration_and_current_layout_precedence` |
| `.auto/` layout with legacy flat-file fallback | Shared current/legacy path resolver; current artifacts take precedence over stale peers | `test_legacy_flat_session_layout_runs_in_place_and_current_layout_wins` |
| Fixed benchmark script and arbitrary command when no script exists | `.auto/measure.sh`; `run --command` is rejected when the fixed script exists | `test_custom_command_only_without_fixed_benchmark` |
| Wall time, timeout, combined output capture, compact tail, full output | process-group execution and `.auto/runs/<id>/*.log` | `test_benchmark_and_checks_timeouts`, `test_metric_outside_output_tail_is_parsed`, `test_termination_stops_benchmark_children_and_retains_journal` |
| Structured primary/secondary metrics | strict finite, unique `METRIC name=number` parser and schema checks | `test_missing_primary_nonfinite_and_duplicate_metrics_are_crashes`, `test_secondary_schema_requires_complete_metrics_and_explicit_addition` |
| Optional correctness checks with a separate timeout | `.auto/checks.sh`; failed checks cannot be kept | `test_correctness_failure_blocks_keep_and_reverts`, `test_manual_metrics_require_opt_in_and_checks_still_block_keep` |
| Keep/discard/crash/checks-failed journal entries | `log --status`; evidence-derived status gate | core transaction tests in `test_autoresearch.py` |
| Keep commits; rejected runs restore source but preserve session files | recorded-path Git transaction, without broad `git clean` | `test_baseline_and_keep_are_persistent_and_exclude_session_files`, `test_discard_restores_tracked_and_removes_only_captured_new_files`, deletion/literal-path tests |
| ASI and advisory MAD confidence | `--asi-file`, standard hypothesis/learning fields, `parity.confidence` | `test_freeform_asi_survives`, `test_confidence_is_stable_and_resets_for_segment` |
| Assumption-aware revisiting of discards (v1.8) | skill revisit checkpoint plus validated `--revisits-run N`; terminal and browser labels | `test_assumption_aware_revisit_is_validated_and_displayed`, `test_skill_and_full_dashboard_include_revisit_protocol` |
| Optional before/after iteration scripts | opt-in `.auto/hooks/*.sh` with the upstream payload contract, timeout, evidence, and no replay on recovery | `test_hooks_opt_in_and_contract` |
| Persistent off/clear/resume | stop marker, archived clear by default, explicit resume | `test_off_resume_and_clear_preserve_history`, `test_off_blocks_an_already_begun_experiment` |
| Auto-resume ceilings and compaction state | owning-task Codex lifecycle hooks, 200-turn cap, >20 discard/crash cap, no-progress gate, durable summary | native hook tests and `tests/evidence/` |
| Inline/fullscreen/browser dashboards | offline compact/full HTML, token-protected loopback server, and terminal view | `test_dashboard.py`, full-report and escaping tests |
| Finalize kept work into independent branches | deletion/binary/mode-aware patch groups in separate worktrees, independent checks, union verification | finalization tests |

The Codex runner intentionally strengthens several mechanics without narrowing the
workflow. It uses `begin` before editing, branch binding, literal scopes, durable
pending transactions, source/protocol fingerprints, and explicit recovery. Those
adaptations prevent a failed commit, interrupted process, hook mutation, or concurrent
writer from creating false evidence or overwriting unrelated work.

## Pi-specific surfaces not ported literally

These features are inherently coupled to Pi and therefore have native Codex
replacements rather than line-for-line implementations:

- Pi extension registration and TypeBox tool schemas → a deterministic CLI invoked
  through Codex's normal shell tool.
- `/autoresearch` command parsing and Pi prompt-template expansion → the
  `autoresearch` Codex skill.
- Pi composer widget, custom transcript renderer, and fullscreen TUI overlay → local
  HTML/live/terminal dashboards and structured command JSON.
- Pi keybindings and `<agent-dir>/extensions/pi-autoresearch.json` → omitted; Codex
  plugin skills and commands do not use Pi's keymap.
- Pi session-tree activation entries and `ctx.sendUserMessage` scheduling → Codex
  lifecycle hooks bound to the owning task ID.
- Pi's extension-specific streaming renderer and temporary output UI → saved raw logs
  plus the shell tool's ordinary streaming/session behavior.

The upstream static marketing site and npm publishing workflows describe and ship the
Pi package; they are not runtime functionality of the research loop and are not copied.
The adapted upstream dashboard asset remains MIT licensed; see
`assets/UPSTREAM-LICENSE`.

## Deliberate native additions

The native port also supports safer or broader workflows that do not remove parity:
manual externally extracted metrics, justified equal/worse tradeoff keeps,
repository-wide literal scope, archived clear, explicit abort/recover, a secure live
loopback dashboard, and deletion-aware independent finalization that never switches
the source checkout.
