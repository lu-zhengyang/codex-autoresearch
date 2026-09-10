# Recover an interrupted experiment

Always inspect `status`, `.auto/pending.json`, raw logs, and Git status first. The
runner uses a process lock; another active command must finish or be interrupted
before recovery. The lock file persists, but its OS lock is released when the
process exits. Never remove it to bypass an active process.

- **editing**: continue the hypothesis and run, or `abort --reason "..."` to archive
  the intent without modifying source. Restore only the edits belonging to that
  hypothesis if abandoning it; preserve newly arrived user edits.
- **running**: a killed process may have no complete measurement. Inspect raw logs;
  use `abort --reason "interrupted benchmark"`. It archives pending state under
  `.auto/runs/<id>/aborted.json`. Source stays untouched. Restore the experiment's
  exact paths to its recorded base, then begin and measure again.
- **measured**: if source and protocol still match, log exactly once. If code or
  measure/check scripts changed, abort and establish a clean base before rerunning.
  Never label an unmeasured edit as kept. Benchmarks that mutate tracked source fail
  closed; inspect what they changed before restoring anything.
- **finalizing**: the journal was written before Git mutation. Read
  `intended_entry`, `base_snapshot`, and `measured_snapshot`. A commit failure may
  leave the exact experiment paths staged; fix the Git error, verify those paths
  still match the measured content, and finish that specific commit with the
  `Autoresearch: <pending id>` trailer. Do not rerun `log` or create a new experiment.
  A partially completed discard needs only its recorded paths restored to the
  recorded base; verify no later user edit will be overwritten.
  Then call `recover`. It verifies HEAD, clean index, fingerprints, and the commit
  trailer/base relationship before completing the journal. If the entry was already
  appended, it does not append it twice. It never replays hooks.

If `recover` rejects the state, preserve all files and explain the concrete mismatch.
Do not force a reset or manufacture a successful result. A malformed JSONL line also
stops writes: preserve the original log before repairing a partial write. Aborted
attempts are history events, not completed measured runs, and do not consume the
runner's numeric run budget; still count their elapsed work against user time budgets.

The lock coordinates this runner, not editors or unrelated Git commands. Use one
owner per worktree. Fingerprints cover tracked and nonignored files; ignored build
outputs/external datasets remain outside rollback and must be stabilized by the
measurement method.
