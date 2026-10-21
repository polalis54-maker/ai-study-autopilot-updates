# AI Study Autopilot: Codex execution backlog

> Read [AGENTS.md](AGENTS.md) first. Repository-only development can proceed without the
> user's Windows machine. No real API calls may be fabricated, and no task is scheduled
> merely by committing these instructions.

## Success criteria

The user wants to **solve AWS SAA-C03 practice questions and complain about quality**.
Agent-led coding, regression tests, maintenance, and repeatable delivery should require
minimal user intervention, within existing authorizations.

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
- [ ] **Blocking acceptance:** real provider end-to-end verification with the owner's
      secured Windows runtime remains **unverified**. Do not auto-approve or silently
      enable paid batches until this is explicitly tested and authorized.
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
- [ ] Deliver only quality-approved, provenance-marked questions; no automatic
      `QUALITY_HOLD` or `REVISE_UNRESOLVED` promotion.
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
