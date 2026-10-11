# GitHub portfolio preparation handoff

## Goal

Reconcile PodcastScraper's remote-ahead branch and dirty local work, separate source from generated podcast data, and prepare a tested public portfolio commit without losing files. The repo is already public; do not pin it until preparation is verified.

## Read first

- `/home/dan/.codex/AGENTS.md`, especially SymDex safety.
- Repository instruction files, root `README.md`, `.gitignore`, and weekly workflow.
- `/home/dan/.agent/diagrams/github-data-engineering-portfolio-audit.html`.
- Inspect `origin/main` before integrating; local `main` was observed 13 commits behind.

## In scope

- Preserve the dirty tree, classify code/workflow changes separately from manifests, screenshots, transcripts, and other generated data.
- Reconcile with `origin/main` without reset, force-push, or silently overwriting local output.
- Decide and document a clean source/data boundary; keep only small representative fixtures if they improve reproducibility and are legally safe.
- Add meaningful automated tests around feed discovery/parsing, idempotency, configuration, cleanup, and failure handling.
- Improve README/CI to explain the ingestion pipeline, scheduling, deduplication/state, outputs, and reproducible local use.
- Prepare and push only a reviewed branch if repository instructions allow; do not pin or make unrelated visibility changes.

## Out of scope

- Do not delete generated local transcripts/screenshots or publish copyrighted/private content without review.
- Do not force-push, rewrite shared history, or treat `compileall` as sufficient testing.
- Do not run SymDex directly.

## Verification and report-back

- Report ahead/behind counts before and after, number of local files preserved, and generated files excluded from Git.
- Report exact tests passed/failed/skipped plus compile/static-check results.
- Report secret-risk findings, files over 10 MiB, final branch, commit SHA, and push status.
- Confirm `git status --short` and enumerate any intentionally preserved dirty paths.

## Suggested skills

- `superpowers:using-git-worktrees` for safe remote reconciliation.
- `superpowers:test-driven-development` for the new pipeline tests.
- `superpowers:systematic-debugging` for conflicts/failures.
- `superpowers:verification-before-completion` before hand-back.

