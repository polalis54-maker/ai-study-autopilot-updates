# AI Study Autopilot (Windows updater)

For the opt-in **100 new provisional questions/day, 500 cumulative** supply
controller, recovery guarantees, unchanged budget and one-time Windows setup,
see [NIGHT_SUPPLY.md](NIGHT_SUPPLY.md). Legacy behavior below remains unchanged
until the new supply campaign is explicitly configured.

AI Study SAA-C03 practice-question pipeline and update distribution. The repository
contains application update files, **not** the user's Windows data, keys, or study history.

## Reviewed question -> local study app

A Gemini `PASS` is not permission to use a question. A held repair must be independently
checked against AWS documentation and explicitly accepted on the Windows computer.

When the operator has reviewed a repaired question:

```powershell
# First stop Autopilot safely (if it is still running).
New-Item -ItemType File -Path .\work\stop_requested -Force | Out-Null

# 1. Inspect original and revised question, choices, answer and explanations.
py -3 .\update_watchdog.py revision-compare SAA-AUTO-00020

# 2. Stage the held revision; no API call or study-app change.
py -3 .\update_watchdog.py revision-stage SAA-AUTO-00020

# 3. ONLY AFTER a person checks all choices/explanations against official AWS docs:
py -3 .\update_watchdog.py revision-approve SAA-AUTO-00020 https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.html
```

The last command asks the operator to type the exact question ID as explicit
verification attestation. The example documentation URL is **not a claim** that
the particular problem has been fact-checked or that the article supports its answer.
Do **not** run that final command unless the content and cited official documentation
have really been reviewed.

Approved candidates are bound by a SHA256 digest in a **private local**
`work/content_approvals.json`. Only exact-matching, approved items are imported to the
PC PWA; no other AI-only questions are published. The operation preserves the original
trial and learning history. It **does not auto-deploy to Netlify**. Never upload
`work/`, `AI_Study/`, keys, or approval files to GitHub.

For an overview without API calls or writes:

```powershell
py -3 .\update_watchdog.py revision-status
```

## When Gemini PASS is wrong

A Gemini `PASS` does not override a human technical review. If the revised
question still contains inaccurate AWS explanations, **do not stage or approve it**.

After checking the complete question and all distractors, run these commands
on your own Windows machine with Autopilot stopped:

```powershell
# Record a human rejection. Does not call OpenAI or Gemini.
py -3 .\\update_watchdog.py revision-request-changes SAA-AUTO-00020 "Explain the actual AWS feature limitations, correct misleading distractors, and distinguish event fanout from queue replication."

# Only when you explicitly choose another paid trial and the local day/campaign
# budget has room for up to three provider requests:
py -3 .\\update_watchdog.py revision-retry SAA-AUTO-00020

# Inspect the new result before considering publication.
py -3 .\\update_watchdog.py revision-compare SAA-AUTO-00020
```

The first command keeps the previous revision, Gemini PASS, and issue notes in
`work/state.json`; sets `REVISION_REQUESTED`; and prevents staging/approval.
The explicit retry feeds the actual human QA feedback into another revision
attempt, archives the previous trial in `revision_trial_history`, preserves
the original source and study history, and leaves the latest result on hold.
No retry is automatic. A rejected trial cannot be treated as reviewed/approved.

**Never claim the second repair is correct until its AWS facts have been checked.**
The request-count budget uses an estimated 5 JPY reservation per provider call
and **does not guarantee** actual billed spend is under 1000 JPY.

## Immediate offline practice for held candidates (no paid API)

Generated questions with `QUALITY_HOLD` are **not** officially verified and are
intentionally excluded from the scored, published PC/mobile question bank. To
make the locally saved Gemini-PASS candidates available for **provisional**
practice while independent review continues, run from the Windows installation:

```powershell
py -3 .\\live_progress.py practice-preview
```

This opens a standalone HTML practice room backed by
`work/state.json`. It shows one or two selections, the model's **provisional**
answer, and the full explanation for every candidate, with prominent warnings
that the answer may be wrong. It omits every rejected or revised-trial question.
It does not use APIs or change `AI_Study/questions.json`, learning history,
trophies, approvals, or Netlify. The output file is local:
`work/outputs/AI_Study_未検証練習室.html`.

**Important:** This is not a claim that 14+ questions were added to the main
study app. Actual availability depends on the user's local state, and
all provisional answers require independent fact-checking.

## Unattended overnight practice (Windows PC stays powered on)

**Intended daily workflow:** Keep the existing Windows Autopilot watchdog
running. The watchdog uses the configured local Windows timezone/date and
does not require ChatGPT to be open. Each day's first run generates up to 20
new SAA-C03 candidates by OpenAI/Gemini and then automatically prepares a
private `work/outputs/AI_Study_本日の新問.html` quiz from **only unseen**
Gemini-PASS `QUALITY_HOLD` items.

The morning quiz is **provisional** and clearly labeled AWS-docs-unverified.
The main scored PWA and Netlify remain independent and unchanged, because
Gemini PASS has demonstrably produced incorrect explanations. Incorrect
rejected candidates are excluded from the daily practice set.

This still obeys the existing **25 provider requests/day**, **150 reserved
requests/campaign**, and **2026-10-28 cutoff**. Up to 20 new questions is a
best-effort generation target, **not** a guaranteed delivery count. The
software will not invent questions or spend past those budget/cutoff guards.
The 1000 JPY reservation is a proxy, not a real-billing maximum.

One-time Windows wakeup after intentionally stopping the watchdog:

```powershell
# From the existing AI_Study_Autopilot directory:
Remove-Item .\\work\\stop_requested -ErrorAction SilentlyContinue
.\\START_AUTOPILOT.cmd
```

If the original installer instead enabled Task Scheduler or another autorun
command, keep using the configured startup script/task. Do not start two
watchdog processes. The computer must be powered on and not asleep; a sleeping
or powered-off PC will not run an unattended Python process.

After waking up, the owner can open the automatically created quiz with:

```powershell
py -3 .\\live_progress.py practice-today
```

This command also creates a daily practice page immediately from previously
unseen saved candidates if there is no page yet. **It makes no API calls.**
The local `work/practice_delivery.json` records previously served problem IDs
so tomorrow's practice does not present the same question as 'new'. If the
hold queue is empty, the morning page explicitly says 0 new questions.

Do not mark this objective done until the owner verifies a genuinely new
daily page and the original/PC/mobile exam-question bank and attempt history
remain intact.

## Developer tests

```sh
python3 tests/test_revision_pipeline.py
python3 tests/test_revision_http.py
python3 tests/test_revision_staging.py
python3 tests/test_revision_approval.py
python3 tests/test_verified_study_sync.py
```

See [AGENTS.md](AGENTS.md) and [CODEX_BACKLOG.md](CODEX_BACKLOG.md) for safety rules and
pending work. The current AI content corpus, private Windows runtime, and Netlify site
are **not** automatically deployed or updated by merging a PR.
