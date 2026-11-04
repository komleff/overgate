# OverGate RC4 consumer findings: Toon Heroes

Date: 2026-11-04. Reference release: `v4.0.0-rc.4@8680c8b468ee6322f35470b4a2ac01cd988ddae7`. Consumer: [Toon Heroes Draft PR #1](https://github.com/komleff/toon-heroes/pull/1). This is a defect report, not a change to the published RC4 tag or a claim of full runtime acceptance.

## 1. Fresh Beads init commits pre-staged project changes

**Observed:** After reviewed `install-overgate.py apply` and `og-init-memory-bank.sh`, `bash scripts/bd-bootstrap.sh` succeeded, but `bd init` created local Toon Heroes commit `ef5991c3ce4cdaad0bcb0c633096ae7e0912be86` (`bd init: initialize beads issue tracking`). That commit included 39 paths: Beads metadata and a subset of the uncommitted OverGate installation (`.agents/**`, `.claude/settings.json`, `.codex/hooks.json`, `.gitignore`). The remaining installed files stayed untracked. This commit was not part of the reviewed inventory plan's explicit commit sequence.

**Independent minimal reproduction with real `bd 1.2.2`:** In a disposable Git repo with an initial commit, stage `staged-sentinel.txt` and leave `untracked-sentinel.txt` untracked. Run `bd --sandbox init --skip-agents --skip-hooks --non-interactive --remote ''`. Beads prints `Committed beads files to git`. `git show --format= --name-only HEAD` includes `staged-sentinel.txt` alongside `.beads/**` and `.gitignore`; the untracked sentinel remains untracked. Thus `bd init` commits the entire pre-existing index, not only its own generated files. The OverGate bootstrap helper does not check for staged user changes before invoking it.

**Impact:** A user-staged file can be silently included in an automatic commit during installation. If the file contains private material, the later normal branch push could disclose it. Even with a clean index, Beads commits a subset of installed payload before the project verifier and commit gate run, making the PR history harder to audit.

**Expected fix/verification:** Define and enforce an index/commit boundary before invoking `bd init`; preserve existing staged bytes and fail closed rather than committing them. Add a regression fixture with a pre-staged sentinel and verify no Beads invocation, new commit, or remote publication occurs. Document the expected automatic Beads commit for a clean install. Product PRs must not work around this by rewriting the published RC4 tag.

## 2. Installed `HOW_TO_USE.md` has an unresolved local QUICKSTART link

**Observed:** The RC4 inventory copies `.agents/HOW_TO_USE.md` but does not copy root `QUICKSTART.md`. The installed document contains `[QUICKSTART](../QUICKSTART.md)`. Toon Heroes' existing Markdown validator consequently failed at `.agents/HOW_TO_USE.md` with `AssertionError: (..., '../QUICKSTART.md')`. A project-owned root QUICKSTART in Toon Heroes restores its validator without changing managed source bytes.

**Expected fix/verification:** In a fresh consumer without a root QUICKSTART, installed Markdown links should resolve. Point to the release's stable online QUICKSTART or include an intentional local entrypoint in the inventory, and add a fresh-install link-closure test.

## 3. Preserved Beads rule names an obsolete version

The installed `.claude/rules/beads.md` has an informational note headed `bd 1.0.2` while the RC4 manifest and bootstrap strictly require `bd 1.2.2`. Toon Heroes corrected its project-owned rule to 1.2.2. Align the reference note in a future release and test version references across manifest, helper, and rules.

## 4. Published Beads metadata prevents bootstrap in a fresh clone

**Observed:** The Toon Heroes branch tracks `.beads/metadata.json` but ignores the local `.beads/embeddeddolt/` database. In a disposable fresh clone of `2558fcf93c42655096b21eae2faaebe6edbf9bb9`, metadata exists and the database does not. `bash scripts/bd-bootstrap.sh` exits 1 before mutation with `ERROR: основная база Beads не найдена: .../.beads/embeddeddolt` and `STOP: existing Beads database unavailable; no auto-start/overwrite.` The bootstrap helper treats existing metadata as an initialized workspace and calls `bd_env_resolve_main_db`. The documented other-machine `bash scripts/bd-sync-restore.sh` also exits 1: `не удалось снять локальный снапшот (bd export) ... restore прерван`. Thus a published install cannot be used from another primary checkout by following the documented bootstrap or restore routes, despite a valid `beads-backup` snapshot.

**Expected fix/verification:** Provide a guarded fresh-clone initialization and restore path for a branch with published metadata but no local database. Preserve the remote snapshot and refuse divergence or destructive overwrite. Add an integration fixture that clones a published install into a new directory, bootstraps Beads, reads the exported task and dependency, and proves no extra Dolt remote or force publication.

## Evidence boundaries

- OverGate `bash scripts/verify-reference.sh` passed on the pinned release checkout; this report does not modify release code.
- Toon Heroes project verifier and `scripts/check-reference.py` pass after adding its project-owned QUICKSTART; the fresh-link failure was observed first.
- The two real Toon Heroes Beads tasks were exported and read back from `beads-backup@45eefc9aeac544d6b555df16760f77c210fcc402`; no task data was discarded.
- The fresh-clone failure was reproduced in an auto-cleaned disposable directory; the working Toon Heroes checkout and its local database were not modified by that test.
- Windows, Claude, and live Codex hook activation are separate checks. A successful static fixture or ordinary Codex CLI command is not proof of activation.
