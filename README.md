# AI Study Autopilot (Windows updater)

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
