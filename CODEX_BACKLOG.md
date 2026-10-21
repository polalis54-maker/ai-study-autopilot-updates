# AI Study Autopilot: Codex execution backlog

> Read [AGENTS.md](AGENTS.md) first. Repository-only development can proceed without the
> user's Windows machine. No real API calls may be fabricated, and no task is scheduled
> merely by committing these instructions.

## Active P0 handoff: 500 newly playable questions (2026-10-22)

**Read [CODEX_500_QUESTION_HANDOFF.md](CODEX_500_QUESTION_HANDOFF.md) and work its milestones as the highest priority.** The owner confirmed their Windows PC remains powered on and that the goal is unattended night-time generation, independent AI review and next-day practice. Approximately **500 additional unique playable new SAA-C03 questions** is the cumulative goal. It is **not** a request to manually draft ten questions, not a total of 500 API attempts, and not permission to spend more money.

The owner actually installed v0.5.12 and showed 14 real new daily-practice items. Their dashboard then showed 256 stored generator records, 22 quality-held, 190/200 AI PASS progress, 22/25 requests, one malformed candidate and Netlify ERROR. These are **dated local observations**, not live GitHub stats or 256 usable questions. The old goal `GOAL_TOTAL=200`, cutoff Oct 28, and campaign request/budget caps obstruct scaling.

**No extra paid API usage has been approved** beyond the existing finite 1000 JPY proxy / 150 reserved request constraints. A goal of 500 new practice items **must be bounded by explicit future consent**, and the system must report budget-exhausted rather than fabricate success. Keep public repo data separated from the user's private local PWA and Windows work dir. Deliver tested PRs and real usable results.

## Success criteria

### Issue #13 implementation under review (2026-10-22)

The opt-in controller in `update_watchdog.py` and journaled provisional delivery
in `live_progress.py` now target 100/day and 500 additional deliveries. See
`NIGHT_SUPPLY.md` for the exact private setup, unchanged caps, replay behavior,
heuristic duplicate/quality limits and outstanding real-machine verification.
`tests/test_supply_campaign.py` exercises the real controller with fake providers:
500 distinct deliveries across five dates; baseline 256/22/14 preserved; 102
reserved requests including the conservative batch warmup;
generator/reviewer/deck/in-flight crashes; budget and billing
stops; malformed replies and finite transport retries. Existing regression suite
is retained. These are synthetic tests, not real delivered AWS questions.

PR #14 review fixes: read-only supervisor eligibility and terminal/daily waiting
statuses prevent idle batch-child relaunches; per-ID least-used topics update
within each batch; token-aware startup/usage growth and persisted truncation
backoff keep the existing 9500-token ceiling. Mock tests cover supervisor ticks,
next-day resume, ten-spec topic diversity, real wire parsing with synthetic
truncation, and old pending-job splitting. No release or paid API run is implied.

Still outstanding: actual Windows deployment/provider throughput and billing,
AWS factual evaluation, durable per-question learner feedback/weak-area scoring,
actual provider-token/currency reconciliation (only existing request reservations
are available here), complete semantic duplicate evaluation, private PWA adapter
and Netlify ERROR investigation. This implementation must not be reported as
100 actual improved questions or a completed real-machine overnight campaign.

The user wants to **solve AWS SAA-C03 practice questions and complain about quality**.
Agent-led coding, regression tests, maintenance, and repeatable delivery should require
minimal user intervention, within existing authorizations.

## User-impact priority: playable new practice questions

The owner reports **three days of zero additional playable questions** despite
successful model/API development work. Source review found these blockers:

1. Generated Gemini-PASS items become `QUALITY_HOLD` and are excluded from
   automated PWA sync until individually approved. This is a conscious quality
   control, not evidence that generation succeeded in shipping learning content.
2. The operator previously created `work/stop_requested` to test revision
   commands; if still present, the Windows unattended generator will not run.
   Verify the local process state before discussing any paid API restart.
3. `v0.5.11` code (release confirmation pending) adds private zero-cost
   `live_progress.py practice-preview`, which renders structurally valid,
   Gemini-PASS `QUALITY_HOLD` candidates as **clearly unverified, isolated**
   practice. It does NOT add them to the main study bank or Netlify, and
   actual counts must be verified on Windows. Do not claim a question-count gain
   until the owner executes it.
4. Next priority is to make the main study pack increase via content actually
   checked against AWS official docs, without allowing false Gemini PASS items
   to enter verified scoring. The owner prefers practical output over version
   numbers or elaborate dashboards.

## Verified milestones and next real blocker (2026-10-21)

- **v0.5.9 published:** `revision-compare`, `revision-stage`, `revision-approve`
  and staged-candidate import for PC PWA, with offline end-to-end regression tests.
  These are release/CI results, not proof of Windows installation.
- **One real provider trial succeeded:** the owner reported `SAA-AUTO-00020`
  `REVIEWED_HOLD`, OpenAI revision + Gemini reassessment, **2 API requests**.
  The source question and learning bank remain unchanged.
- **Real user-ready gains: 0 verified adopted questions.** The owner supplied the
  full local revision comparison for SAA-AUTO-00020. Despite Gemini PASS, quality
  review identified inaccurate claims that FIFO is unsuitable at high throughput
  and insufficient distinction between SNS cross-region event fanout and native
  replication of existing SQS messages. **Decision: REVISE, not approve.**
  Do not hardcode the user's private question text in this public repository.
- **Human feedback workflow implemented in code:** `revision-request-changes`
  explicitly records a rejected Gemini PASS without API calls. `revision-retry`
  can then use operator feedback for a new, quota-limited paid trial and preserves
  prior revision history; requires local Windows update. Neither command was run
  on the owner's PC yet. Release v0.5.10 is pending/subject to checking release status.
- **Next bottleneck:** on the Windows runtime, mark SAA-AUTO-00020
  `REVISION_REQUESTED` with the identified technical corrections; only then
  attempt another paid revision when the daily cap and provider bill permit.
  Recheck the new candidate and official AWS documentation before staging/approval.
  Do not claim adoption from GitHub CI.
- **No automatic 81-item paid repair:** daily quota near exhausted in last report;
  the per-request 5-JPY ledger is not a guaranteed real 1000-JPY bill limit.

### P0: Make content revision truly safe and verifiable

- [ ] Audit the `revision-one` OpenAI JSON-schema request and Gemini review wiring against
      local stubs and mocked HTTP, including invalid API replies, 429, timeout, malformed
      JSON, crash between reservation and response, and Windows lock behavior.
- [ ] Ensure original candidate, source, audit trail, IDs, answer history, and trophies
      are preserved. Every revision remains in `revision_trials`.
- [ ] Detect semantic duplicates, not only similar question text. Use reproducible
      evaluation cases for same-correct-reason scenarios; do not publish solely based
      on fuzzy-string or model confidence.
- [ ] Give each revision attempt a clear status and original review issues.
- [ ] **Blocking acceptance:** one real OpenAI->Gemini repair succeeded on the owner's
      Windows runtime, but quality validation, approved staging, Windows PWA sync,
      and multiple-item failure behavior are **not yet verified there**. Do not auto-approve
      or silently enable paid batches.
- [ ] Check provider usage limits: the `1000 JPY / 150 calls / 5-JPY reserve` model
      is a *local proxy*, not a real maximum bill. Fail closed if usage/currency is
      unknown; do not automatically ramp up spending.

### P1: Quality-hold review and content coverage

- [ ] Build a privacy-safe export of **only** needed review information for the
      currently held problems, if the user explicitly approves such exports.
- [ ] Classify review decisions as candidate-accept, revise, reject with reasons;
      fact-check current AWS service capabilities with official AWS documentation.
- [ ] Set up an audit workflow for the 14 held candidates and the existing 81 unresolved
      (counts are from user's last known local state, not a current server snapshot).
- [ ] Track SAA domains D1-D4 and topic coverage. The target weighting from this
      project is D1 30%, D2 26%, D3 24%, D4 20%.
- [ ] A user-visible discrepancy or repeat should become a reproducible regression test.

### P2: Study app synchronization

- [ ] Trace PC question pack generation and state formats.
- [ ] Fix Netlify/mobile PWA synchronization errors **without** uploading secrets,
      full private state, or learning history.
- [ ] Test content manifests, compatibility, offline PWA caching, and upgrade history.
- [x] Offline implementation (v0.5.9): block AI-only candidates from automatic
      PC/mobile sync, stage repaired trials separately, and require an explicit
      content-hash-bound local human/official-documentation attestation.
- [ ] Verify this approved-only path with real Windows trial data and an actual
      vetted question; do not conflate green CI with live adoption.
- [ ] Verify on both PC and mobile in approved environments before marking complete.

### P3: Exam-focused learner experience

- [ ] Implement varied unseen scenarios, 65-question exam simulations,
      confidence-based weak-area review, explanations for **all** choices,
      and a meaningful trophy/progress system.
- [ ] Do not inflate scores by rephrasing identical questions. Report both
      first-seen and repeat-question accuracy.
- [ ] Keep learner progress, trophies, and settings intact across upgrades.

## Working agreement

For each work session, select the highest-priority unblocked task and produce one
bounded PR with tests, a clear summary, and truthful remaining blockers. Where
permission allows, follow the repository's standard release process only when
release-specific tests succeed. Update this backlog when progress is verified.

Do not infer app deployment from a green CI result. A green run validates repo code,
not the user's Windows installation, API secrets, mobile site, or AWS exam accuracy.

## One-time user action required for real autonomy

The owner must connect/select `polalis54-maker/ai-study-autopilot-updates` in
**Codex**, or start a suitable **Work** task with the GitHub connection, and authorize
the specific environment/repo. If available in the selected product, turn on a
scheduled recurring task or event-triggered workflow using the instruction below.

**Suggested recurring task (copy into Codex/Work after repo access is connected):**

> Continue development of the AI Study Autopilot repository autonomously.
> First read AGENTS.md and CODEX_BACKLOG.md, then choose the highest-priority
> unblocked work. Implement a limited PR with regression tests; inspect Actions,
> fix test failures, and update the backlog accurately. Never access or publish
> local secrets/learning history, never auto-approve AI-only questions, and do not
> incur paid API charges or deploy high-risk data changes without the necessary
> permissions and verified safeguards. Report actual PRs, test outcomes,
> releases, and remaining blockers succinctly. Do not claim background work
> unless a scheduled task actually ran.

Schedule setup and permissions are external to this repository. A workflow that
runs on the user's PC requires that machine and its Codex runtime to be available;
cloud work can handle GitHub tasks but cannot automatically reach private local files.
