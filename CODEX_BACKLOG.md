# AI Study Autopilot: Codex execution backlog

> Read [AGENTS.md](AGENTS.md) first. Repository-only development can proceed without the
> user's Windows machine. No real API calls may be fabricated, and no task is scheduled
> merely by committing these instructions.

## Success criteria

The user wants to **solve AWS SAA-C03 practice questions and complain about quality**.
Agent-led coding, regression tests, maintenance, and repeatable delivery should require
minimal user intervention, within existing authorizations.

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
