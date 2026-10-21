# Codex handoff: Generate and deliver 500 new playable SAA-C03 questions automatically

**Priority: P0, user-visible outcome.** Read `AGENTS.md`, `CODEX_BACKLOG.md`, `README.md`, and current implementation before writing code. Build functioning changes with tests and a PR, not just another plan, dashboard, or version bump.

## 1. What the owner actually wants

The Windows PC is normally left powered on. While the owner sleeps, **AI autonomously creates new Japanese AWS SAA-C03 practice questions, checks their quality, and queues them for next-day study**. The owner should open the app and answer the daily new set without manually approving each candidate, running a command every morning, or requesting a GitHub release each day.

**New measurable target: 500 additional, distinct, playable questions, cumulatively.** “500” must mean *500 unique usable new practice questions actually delivered through a local study interface*, not 500 API requests, model proposals, audit results, copies, or 500 including the existing bank. Capture a migration-safe baseline/checkpoint when this feature first activates. Generate over multiple nights as budget allows. Do **not** promise 500 overnight or a fixed delivery date.

Prefer delivering into the existing PC AI Study study experience where safe and supported; at minimum keep the existing daily offline practice interface automatically populated, clearly accessible, and never silently inflate the verified/official main bank. The owner should see *today’s truly new count* and how many remain to reach 500.

## 2. Verified environment and limits

- Distribution repository: `polalis54-maker/ai-study-autopilot-updates`; it contains updater/runtime files **not** the owner's entire `AI_Study/` PWA, private `work/state.json` or model credentials.
- Last release reported working on the owner's Windows PC: **v0.5.12**. On 2026-10-22, the user ran the Windows updater, removed `work/stop_requested`, enabled `START_AUTOPILOT.cmd` autorun (answered YES), and successfully generated a local daily practice HTML with **14 previously held new candidates using 0 API calls**. This is a past observation, not a live remote state.
- On a subsequently shown local dashboard: **40/55 existing reviewed**, **256 newly saved generator records**, **22 QUALITY_HOLD**, **190/200 Gemini PASS progress**, **22/25 API requests used that day**, **14 new questions in the daily offline practice room**, `SAA-AUTO-00268` rejected for malformed/incomplete response, PC scored-bank sync `UNCHANGED`, mobile Netlify status `ERROR`. These measures have DIFFERENT meanings and must not be conflated.
- Code currently has `GOAL_TOTAL=200`, `GEN_DAILY=20`, `CUTOFF='2026-10-28'`, `GROUP=2`, `CAMPAIGN_DAILY_CAP=25`, `CAMPAIGN_ABSOLUTE_CALL_CAP=150`, `CAMPAIGN_BUDGET_JPY=1000` with a **5 JPY/request reservation proxy**, not real metered billing. Changing the goal constant alone does not deliver 500 questions; the time/cost limits, scheduling, quality gate and delivery all need redesign.
- The owner explicitly wants *automatic question supply* rather than manual one-by-one approvals. Do not infer consent to increase the prior spending cap.
- Study target: AWS SAA-C03. Generated content must not be misrepresented as AWS-official-reviewed. One real example `SAA-AUTO-00020` got a false Gemini PASS involving a nonexistent SQS cross-region clone, a misleading claim that FIFO cannot scale, and conflation of SNS event fanout with existing-queue message replication. Human feedback marked `REVISION_REQUESTED`. Preserve that and all other QA history.

## 3. Implementation milestones (commit and test independently)

### P0a. Fix accurate goal and tracking

- Replace the fixed 200-PASS gate with a configurable **500 *additional delivered unique* questions** campaign, checkpointing the baseline once. Derive progress from unique candidate IDs actually added to the **provisional playable** set, not review count or generated record count. Show counters for created / reviewed / held / rejected / playable newly delivered / verified main-bank / attempted / still needed.
- Do not lose or reset existing/generated/reviewed questions, `revision_trials`, `revision_trial_history`, achievements, completed attempts, review annotations or provider request ledgers.
- Do not cap generation at 2026-10-28 by assumption for the new campaign. But do not silently remove the **old campaign’s consent/date restrictions**: introduce an **explicitly opt-in new campaign configuration** with clear start, stop, spend cap, daily request cap and target. With no fresh spending authorization, remain within previously approved budget and stop cleanly when exhausted, with an honest message.

### P0b. Genuine unattended Windows night-to-morning pipeline

- Reuse and harden the existing Windows scheduled autorun/watchdog. The same Windows user account has DPAPI keys. Handle restarts/locks/single-instance and an awake PC; do not require ChatGPT/Codex to remain open. `work/stop_requested` remains a functioning kill switch.
- After each completed generator/reviewer batch, atomically refresh the next-day private practice queue. At wake-up the user can open the local app/HTML and see new questions immediately. `practice-today` must not itself require paid calls. Fix the current dependency on manual approval for **provisional practice**, while retaining the strict independent-approval gate for anything labeled officially verified or published.
- Ensure there is never a blank claimed-success state: show `0` and concrete reason if paused by cost, time, daily cap, malformed provider response, sleep/offline, or empty eligible inventory.
- New questions from the same date must not be counted as fresh again after restart. Across days avoid repeats until the owner explicitly chooses review mode. Do not overwrite the existing PWA; if integrating scored app files is not possible from the public repo, leave a tested adapter/contract and identify exactly which local files need a one-time integration.

### P1. Scale generation without junk or runaway bills

- Implement controlled multi-question OpenAI structured batches and independent Gemini review, with adaptive batch sizing based on actual output size, candidate failures and available spend. Existing `GROUP=2` and `GEN_DAILY=20` are not sufficient by themselves.
- Validate correct id/domain/type/topic/choice count/answer count, **all distractor reasons**, explanations, malformed/truncated JSON, and scenarios that mention fictitious AWS features. Salvage good questions when one candidate fails. Retry transient 429/timeout/network errors with bounded backoff and daily/cumulative safeguards. Do not retry the same structurally impossible candidate endlessly.
- Detect exact and semantic near duplicates across existing bank, all generated candidates, revision history and delivered practice history. Vary scenarios/architecture decisions, not just wording.
- Target SAA blueprint distribution **D1 30%, D2 26%, D3 24%, D4 20%** across the new 500 playable unique items (roughly 150/130/120/100). Include niche AWS services only when the scenario calls for them; avoid repetitive S3/EC2/VPC rephrases.
- Store full provider trial/reviewer issues and reject reasons; never silently promote Gemini PASS to independently fact-checked status. Prior false-PASS cases become regression fixtures. Practice-only answers must be prominently labeled *AI generated / unverified / possibly wrong*. Add a quick wrong-answer/incorrect-explanation report and exclude rejected items from future new decks.
- Track actual provider **tokens/estimated currency exposure if available**, independently auditable request counts, and provider-side real billing where feasible. **The existing 1000 JPY and 150-call limit must not be increased by Codex**. Fail closed when spend data is missing or ceiling reached. No real-provider calls from GitHub CI, no secrets or user content uploads.

### P2. Exam learning outcomes

- Each day's set should be solvable in one day, default configurable `daily_delivery_target` (e.g. 20–50). Generate a stock buffer when authorized, never burn API calls on duplicates just to chase the target.
- Track answer correctness and answer confidence per question locally for **the provisional practice room**, clearly distinct from officially scored exams. Support dedicated weak-area and reattempt mode; only the **new question** counter is deduped across days.
- Keep full answer/incorrect-choice explanations, show exam-domain distribution and genuine first-seen accuracy; no trophy inflation for provisional questions.
- Netlify mobile was `ERROR`. Do not claim phone auto-sync works. Offer a safe separate PWA integration plan and implement only if permitted, using owner-provided local files/credentials in an approved runtime, never in this public repo.

## 4. Hard acceptance tests (CI uses mocks only)

1. Synthetic generation/review fixture can produce, persist, deduplicate, and **deliver 500 structurally valid, unique playable IDs** over multiple simulated days; exactly 500 count as added, not 500 attempts or old-bank items. Domain distribution must satisfy targets within documented rounding.
2. Simulated user starts with existing `256` generator records, `22` QUALITY_HOLD and `14` already delivered (example fixture, not live state). Migration preserves them and creates no fake new-count increment.
3. Restarts mid-OpenAI call, after provider response, after review, and mid-deck write never create duplicates, lose content or trigger unbounded extra spending.
4. Mocked malformed JSON, incomplete responses, 429, network timeout, Gemini false PASS, SQS clone/FIFO regression, duplicates and no remaining budget fail safely.
5. 500-target and daily-target calculations are decoupled from old fixed `GOAL_TOTAL=200`, old campaign cutoff and the actual `AI_PASS` count. Exit clearly if 500 is unattainable within authorized spend; **never** bypass consent automatically.
6. Demonstrate the Windows startup/scheduler -> batch -> morning local page end-to-end using offline fixtures. It opens 20+ correct-format new candidates where available; next date uses distinct IDs; state, verified bank and scores are preserved.
7. Dashboard clearly displays `new today`, `new delivered total / 500`, `provisional count`, `independently verified count`, `calls today`, `cumulative authorized spend`, and actionable last error.
8. Test full release flow and updater allowlist. The proof of Windows real-provider operation must be gathered separately, never invented from CI success.

## 5. Requested output from Codex

- Open focused PR(s), run existing regression suite and new offline tests, fix failures, then report code paths touched, passing checks, expected overnight operations, cost ceilings, and blockers.
- The **primary acceptance metric is playable new questions delivered**, not release version, GitHub merge count, AI PASS count or how many errors were retried.
- Supply one-time operator instructions for safe configuration and authorization; after that, Windows should run without day-to-day manual commands.
- Do not use the repository to trigger paid bulk generation. Do not start 500 real API generations unless the owner has explicitly configured and approved a sufficient actual spending ceiling.
- If source PWA or its `work/` data is required, note the missing local file boundary. Build what can be verified inside this repository, and ask for no API keys, private user history, or repo upload of `work/` files.
