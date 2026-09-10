# Changelog

## [0.3.0] - 2026-09-10

### Added

- Native Codex runner, skills, lifecycle hooks, dashboards, recovery, and independent
  finalization for the portable `pi-autoresearch` v1.8.1 workflow.
- Assumption-aware discard revisits through `--revisits-run N`, including validation,
  durable ASI, next-iteration guidance, and dashboard labels.
- Current `.auto/` session files plus in-place legacy `autoresearch.*` fallback.
- A requirement-by-requirement Pi → Codex parity audit in `PARITY.md`.

### Changed

- Git operations use recorded-path transactions and durable recovery rather than
  broad working-tree cleanup.
- Test repositories explicitly disable inherited commit/tag signing so the suite is
  hermetic in sandboxes and CI.
