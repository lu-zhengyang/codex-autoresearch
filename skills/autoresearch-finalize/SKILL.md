---
name: autoresearch-finalize
description: Turn completed autoresearch experiments into reviewable Git changes with measured results, optionally splitting independent changes into branches. Use when asked to finalize, package, or prepare autoresearch results for review.
---

# Finalize autoresearch in Codex

Read `.auto/prompt.md`, `.auto/log.jsonl`, `.auto/codex.json`, pending state, Git
status, and actual diffs. Resolve an unfinished experiment before finalizing.
Keep/discard labels alone are insufficient: inspect the source commits and checks.
Do not rerun experiments unless validation or the request requires it.

Default to a clear summary and reviewable diff on the existing experiment branch.
Include baseline → best, direction/unit, correctness checks, benchmark protocol,
known variability, and remaining tradeoffs. Preserve the journal. Do not push,
merge, publish, or delete the research branch unless requested.

If the user requests separate branches, group changes by logical purpose and file
dependencies. Files changed in multiple groups make them dependent: merge overlapping
groups or explicitly use a requested stacked structure. Disjoint files alone do not
prove runtime independence; inspect imports, interfaces, and shared assumptions.

For independent branches, determine the actual target branch and merge-base from Git
and context. Create each `codex/<goal>-<group>` in its own temporary worktree starting
from that base. Apply the base-to-final patch for that group's **exact files**, including
additions, deletions, executable bits, and binary files (`git diff --binary` and
`git apply --index` can preserve them). Exclude `.auto/**` session artifacts. Avoid
copying file contents with `git checkout <commit> -- <file>` because
that does not represent file deletions.

Commit with the concrete change and supporting measured evidence. Validate each
branch independently with relevant correctness checks. Do not attribute the entire
session's speedup to an individual group without an isolated measurement. Verify
that applying the union of group patches reproduces the final source tree, excluding
session artifacts. If verification fails, retain created worktrees for inspection
and report the exact difference; never claim independent mergeability prematurely.

Choose routine grouping from evidence and proceed within the request's authorization.
Ask only when an unresolved grouping/target choice changes the intended outcome.

## Deterministic finalization helper

Resolve `../../scripts/finalize.py` relative to this skill directory. Write a plan
inside the session folder (so it does not enter source changes):

```json
{
  "base": "actual-merge-base-sha",
  "goal": "parser-speed",
  "groups": [
    {"slug": "cache", "title": "Cache parser metadata", "body": "Measured evidence and checks", "files": ["src/cache.py"]}
  ]
}
```

Use actual commit hashes and exact changed filenames, never these example values.
An ordered plan using `last_commit` endpoints instead of `files` is also accepted.
Run `python3 "$FINALIZER" --project "$PROJECT" --plan "$PLAN"` for a preflight result.
Then add `--apply` to create the independent branches. Add `--check-command "..."`
for a correctness command runnable independently in every resulting worktree.

The helper rejects overlapping/incomplete groups before changing branches. It preserves
binary patches, deletions, and file modes. It creates worktrees under `.auto/finalize/`,
verifies the union of actual branch patches against the final tree with an isolated Git
index, and never switches the source checkout. Failures retain branches/worktrees and
a report for inspection. Source correctness validation is still necessary: a matching
union alone does not prove each group's runtime independence. No push or merge occurs.
