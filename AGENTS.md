# AI Study Autopilot: Codex development rules

This repository contains the **Windows Autopilot update distribution**, not the complete
Windows installation or the mobile AI Study PWA. Read `CODEX_BACKLOG.md` before changing code.

## Project objective

Ship a trustworthy AWS SAA-C03 practice application and a safe, auditable content pipeline.
The learner's job is to take practice questions and report wrong answers, repeats, and weak explanations.
Codex's job is to implement fixes, run tests, and produce reviewed, working pull requests.

Prioritize **quality over number of generated questions**. A Gemini PASS is *not* AWS source
verification and **must not automatically approve content**.

## Current facts (2026-10-21)

- Released version on main: v0.5.6 (check `release_files/VERSION.json` again).
- Last user-reported local counts: 150 `AI_PASS`, 81 `REVISE_UNRESOLVED`,
  14 `QUALITY_HOLD`. These counts live in the user's private `work/state.json`;
  they are **not live GitHub values**, and may have changed.
- `revision-preview`, `revision-status`, `revision-one`, and `revision-batch`
  are implemented in `release_files/update_watchdog.py`.
- Their offline tests pass on GitHub Actions. **Real provider calls and processing the
  user's 81 entries have NOT been verified**. Never claim otherwise.
- The study-bank sync to Netlify/mobile has previously failed. Do not assume it works.
- Campaign: user consented to at most JPY 1000 of *additional* API use for the one-time
  batch. Current local 5-JPY-per-call reservations and 150-call cap are **proxies, not
  a true billing limit**. Gemini costs and foreign exchange vary.
- Generation cutoff in current code is October 28, 2026, before SAA study deadline.

## Operating procedure

1. Inspect the repo, workflow results, outstanding work, and `CODEX_BACKLOG.md`.
2. Choose the smallest highest-value unfinished work item. Work autonomously to a PR
   with reproducible tests, including regression tests for past defects.
3. On every change, run:
   ```sh
   python3 -m py_compile release_files/update_watchdog.py
   python3 tests/test_release.py
   python3 tests/test_campaign.py
   python3 tests/test_campaign_budget.py
   python3 tests/test_revision_pipeline.py
   python3 tests/test_revision_batch.py
   python3 tests/test_revision_http.py
   python3 tests/test_revision_status.py
   python3 tests/test_mobile.py
   python3 tests/test_trophies.py
   ```
   Run equivalent test steps through GitHub Actions and inspect errors.
4. Document results and any untested assumptions in the PR. Merge only if tests are green
   and risk is bounded. For high-risk content, costs, data migrations, or release
   operations, seek the user's authorization for the *specific action* when necessary.
5. Releases: the release workflow runs on `release_files/VERSION.json` changes on
   `main`. Do not increment the version just to demonstrate activity. Preserve updater
   allowlist compatibility and update manifest checksums through the existing workflow.
6. Repeat on subsequent scheduled sessions, selecting the next priority from the
   backlog. **A repository file does not schedule or launch Codex by itself.**

## Non-negotiable safety

- Never upload or commit API keys, `work/`, `AI_Study/`, local learning history,
  credentials, private questions, or `.env` files. Do not print secrets in logs.
- Never overwrite, truncate, delete, or reset a user's `work/state.json`, problem bank,
  trophy state, PWA local storage, or history. Back up and make migrations reversible.
- Do not silently promote `QUALITY_HOLD`, `REVISE_UNRESOLVED`, or AI-only passes to
  published/verified content. Preserve original candidate and reviews, keep trials
  separately, and require explicit independent verification before release.
- Do not add unattended paid provider calls, exceed the user's authorized spending, or
  represent a request-count proxy as a hard JPY budget. Abort if billing confidence is
  insufficient. Provider-side spend should be checked separately.
- Real-provider tests require a secured local/approved runtime; no credentials exist in
  this public distribution repository. Use mocks and fixtures on GitHub.
- No force-push to main, no destructive git commands, and no bypassing release tests.
- Do not assume internet, network access, Windows UI access, or live GitHub write
  privileges unless tools actually provide them.
- Do not claim code changes alone are deployed to the user's PC or mobile phone.

## When blocked

Make progress on independent tests, CI reliability, documentation, safe validation and
reviewing stale code. Leave a precise blocker (commands, error, unavailable credential
or infrastructure) in `CODEX_BACKLOG.md` or the PR. Don't repeatedly ask the user to
run one command at a time; bundle any necessary one-time setup and clearly mark it.
