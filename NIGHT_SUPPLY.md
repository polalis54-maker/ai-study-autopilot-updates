# Unattended provisional question supply (Issue #13)

The opt-in supply controller targets **100 newly playable questions per local
calendar day**, and **500 additional questions cumulatively**. These are targets,
not guarantees about output quality, provider availability, time or cost. It never
calls providers from `practice-today`, changes the verified bank, awards trophies,
or deploys Netlify. Gemini PASS is not AWS documentation verification.

## One-time Windows setup after installing the tested runtime

This repository does not contain the owner's `autopilot.py`, `update_agent.py`,
credentials, PWA or private state. A PR is not a Windows deployment. Package these
changes through the existing release workflow only after review; this change does
not bump VERSION or publish a release. Both edited Python files are on the existing
updater allowlist. Keep the current Windows account (DPAPI keys are account-bound).

1. Stop Autopilot with its existing `work/stop_requested` switch and wait for the
   running batch to exit. Back up the private installation normally.
2. Check actual OpenAI **and** Gemini billing and provider-side spending controls.
   No new budget is granted here. The existing campaign ledger must exist and be
   enabled. The controller reuses its reservations, including previous usage;
   never delete/reset it. Missing/corrupt ledgers fail closed.
3. From the installation folder, explicitly choose start, stop and the date through
   which billing has been checked. Example dates are illustrative, not automatic
   authorization to extend the former October 28 campaign:

   ```powershell
   py -3 .\update_watchdog.py supply-configure 2026-10-22 2026-10-28 2026-10-28
   ```

   This zero-API command creates private `work/supply_campaign.json`, makes an
   exclusive `work/state.before_supply.json` backup, and captures the baseline.
   It requires the stop switch and refuses to overwrite existing configuration.
   Stop first before editing configuration later; retain the delivery and budget
   journals. `enabled=false` disables paid supply (invalid config fails closed).
4. Remove the stop switch and launch the existing `START_AUTOPILOT.cmd`; retain
   the previously configured per-user startup task. The PC must remain awake and
   logged into the same account. Do not run multiple installations against one
   state file. The watchdog's instance lock and the batch/delivery locks serialize
   repeated launches within this installation.
5. Open the existing runtime dashboard and its **本日の新問を解く** link, or
   `py -3 .\live_progress.py practice-today`. No daily command is required to
   generate questions; this command only opens the automatically maintained page.

Private config accepts target <=500, daily target <=100, batch size <=10, daily
requests <=25, cumulative requests <=150 and budget <=1000 JPY. These checks are
upper bounds, never a new allocation. Each request reserves the existing 5-JPY
proxy before the network boundary, including failed/retried requests. A proxy is
**not a true billing cap**. Expired billing confirmation stops paid work. Do not
renew it without checking actual charges. More funds require separate approval.

The dashboard's remaining-request count deducts **all prior campaign reservations**:
`max(0, min(150-used, configured_call_cap-used, configured_budget_jpy//5-used))`.
For example, 90 existing reservations leave at most 60, not a new 150-call grant.
Today's remaining count is additionally limited by `25 - today's used requests`.
The synthetic short-output test now uses **102** reservations for 500 deliveries,
including the conservative first batch. This does not mean the owner has 102
requests left, or that real Japanese content will fit that many calls. Shortage,
duplicates, transport retries and long outputs can require more calls; ceilings
remain unchanged and shortage stops generation.

## Recovery and measurement

The old 200-PASS goal and old cutoff are unchanged for legacy mode. Only explicitly
configured supply uses its own dates and delivered-question goal. First activation
excludes every pre-existing generated, pending, reviewed and already delivered ID.
It therefore does not relabel the previously observed 256 records or 14 deliveries
as new progress. Existing records and revision history remain untouched.

Jobs reserve IDs before requests, cache raw generation and reviewer replies before
processing, persist validated pending items, and permit at most two calls per
provider per job, including interrupted calls. A network timeout/429 can retry once
with a two-second delay. Permanent errors also have this finite bound. Malformed
generation keeps valid neighbors and persists a smaller batch ceiling.
Malformed review, exhausted retries and zero-delivery batches stop safely. A new
day can resume saved jobs; a structurally invalid cached reviewer reply requires
operator investigation rather than endlessly recharging for the same failure.

The supervisor reads configuration, state and delivery receipts without rendering
or rewriting practice pages. Daily completion and daily quota wait until the next
local date. Cumulative completion, exhausted campaign budget, stop date, expired
billing confirmation, disabled configuration or invalid configuration terminate
the generation supervisor with an explicit status, without launching a batch
child. After changing terminal configuration, restart the existing watchdog;
never reset request/delivery journals. Same-day safety pauses do not launch new
children until the next day. Idle heartbeat updates remain separate from decks.

Generation keeps the existing **9500 output-token ceiling per request**. Without
provider usage measurements it starts with at most two questions (4000 tokens
each plus framing headroom). Completed Responses usage is saved in the job; a
persisted high-water tokens/question estimate plus 30% margin and 1000 tokens of
headroom permits a batch to grow, up to the configured maximum of ten. Missing
usage never justifies growth. A longer response shrinks future batches. A
`max_output_tokens` incomplete response is archived as a failed job and reduces
the persisted batch ceiling by half; it is not blindly resent. If one question
still truncates, stop for that day. Old pending ten-item jobs without a cached
response are split before another provider call, preserving IDs and retry counts.
All failed/resized requests still consume the same finite reservation ledger.
The number of reserved requests is not a token/currency billing guarantee.

The delivery journal contains immutable ID receipts plus replayable daily decks.
It is committed before the HTML file and rebuilt on restart. Within a day each
batch appends unseen questions until the target; across dates IDs do not repeat.
Late rejected/revised items disappear on refresh but their historical delivery
receipt remains. Day boundaries follow the installation's local timezone; this
is not a configured arrival-time scheduler. A PC resuming from sleep cannot promise
100 ready questions by a particular hour.

All-choice explanation markers, selected-answer counts, domain/type/ID matching,
review quality and known SQS/FIFO false-PASS claims are gated. Exact/near-duplicate
checks include saved candidates and revision history at delivery. They are
conservative text/answer heuristics, **not a semantic uniqueness or correctness
proof**. The provider review remains independent of generation. Questions passing
these gates remain explicitly unverified provisional practice.

The dashboard separates today's newly playable count, cumulative new deliveries,
unverified count, this feed's independently verified count (zero), request usage,
reservation exposure and the last stopping reason. A shortage is visible rather
than a blank success. Existing PC/mobile sync status remains independently shown;
the previously reported Netlify ERROR has **not** been repaired or verified.

## Verification and remaining real-machine checks

`python tests/test_supply_campaign.py` drives the actual controller with fake
providers and temporary private fixtures. It checks 500 deliveries across five
days, 30/26/24/20 domain allocation, restarts at generation/review/deck/in-flight
boundaries, budget reuse, timeout retry, false-PASS guards, and preservation of
256 baseline records, 22 held statuses, 14 past deliveries and learning data.
It also exercises repeated supervisor ticks/restarts with zero child launches
after completion, quota/budget exhaustion, expiry and disabled/invalid config;
next-day daily/quota resume; fifty ten-question batches with diverse per-domain
topics; real Responses serialization/parsing with mocked HTTP truncation and
pre-call splitting, without increasing the token limit or budget caps.
CI uses no keys and cannot establish factual correctness of real generated content.

Before claiming unattended operation, verify on the owner's installation: updater
installation, DPAPI access, actual Responses/Gemini payload sizes at batch 10,
provider-side costs, autorun after reboot, stop during a provider timeout, two-day
no-repeat decks, original PWA scores/trophies, and sleep/power policy. Real API
requests, 100 actual improved questions, official AWS fact checks, PWA/mobile
integration, and Netlify recovery are **not demonstrated by these offline tests**.
