# License Reclamation — How Failure Is Handled

**Audience:** Engineering, IT-Ops, and management  
**Purpose:** Confirm that leftover SaaS seats after offboarding will sometimes fail to scan or revoke — and that this workflow is designed for that, not around it.  
**Date:** 15 August 2026

This is a briefing, not a runbook. Implementation detail lives in the [product roadmap](../16-license-reclamation-human-in-the-loop-roadmap.md) and the phase logs in this folder.

---

## Bottom line

SaaS APIs time out. Identity data is incomplete. A seat on GitHub can revoke cleanly while Jira does not. Those are expected operating conditions.

The workflow is built so that:

1. **A reclaim failure never undoes offboarding.** The person is already deactivated in Okta. License reclaim is downstream and isolated.
2. **Incomplete information is treated as work, not as “all clear.”** If we cannot confirm whether a seat exists, a ticket still opens.
3. **We never revoke a seat we are not sure is there.** Uncertain findings are skipped, not guessed.
4. **Partial success is a first-class result.** One app can succeed while another fails; the ticket stays open until the remaining work is done.
5. **Nothing destructive happens without a person confirming the plan.** The copilot proposes; a human approves; a dedicated broker is the only system allowed to revoke.

If a license reclaim run fails, the outcome is visible, recorded, and retryable. It is not silent, and it is not mistaken for completion.

---

## What this workflow does

After Okta deactivates a leaver, a **scanner** checks GitHub, Linear, and Jira for leftover paid seats. When seats remain — or when the scan itself is incomplete — a **Jira Service Management** ticket opens for IT-Ops.

An agent reviews the ticket, confirms which apps to reclaim, and a **reclaim broker** revokes only those confirmed seats. An AI copilot (Cursor) can read the ticket and call the broker; it never holds the vendor admin keys.

That human gate is the primary control. Error handling is the second: it decides what happens when a vendor, a credential, or a ticket is not in a state we trust.

---

## Design principles

| Principle | What it means in practice |
| --- | --- |
| **Offboarding is independent** | If the scanner or broker fails, Okta deactivation still stands. Reclaim inventory must not block the leaver workflow. |
| **Continue per app** | A GitHub timeout does not skip Linear or Jira. One failure must not hide the rest of the picture. |
| **Unknown ≠ clean** | Auth errors and vendor outages are recorded as errors. They never look like “this person has no seats.” An empty Okta `githubUsername` is `not_assigned` (never mapped), not an error. |
| **Do not revoke uncertainty** | If the scan could not confirm an active seat, the broker will not revoke that app. |
| **Safe to retry** | A seat already removed is treated as success. Re-running the same ticket does not double-revoke. |
| **Human before Done** | The ticket is not closed while any requested app still failed. Operators comment the result and try again. |
| **Email is for real breakage** | Slack is everyday visibility. Email pages only when infrastructure or the work queue itself fails. |

---

## What can go wrong — and what we do

### 1. Discovery (the scan)

The scanner checks each app independently after offboarding.

| Situation | What we do |
| --- | --- |
| Confirmed leftover seat | Ticket opens listing that app. This is the happy path for reclaim. |
| Confirmed no seat | Recorded as clear for that app. No work item for it. |
| Vendor blip (timeout, rate limit) | Recorded as a retryable error. Other apps still scan. Ticket still opens so “unknown” is not filed as clean. |
| Wrong credential or misconfigured API | Recorded as a configuration error. Ticket still opens. We do **not** treat “unauthorized” as “not a member.” |
| No GitHub username on the Okta profile | We do not call GitHub. Recorded as `not_assigned` (never mapped in Okta). No identity-only ticket. |
| Every vendor call fails | Ticket still opens, Slack is notified, and an alarm email fires. Incomplete inventory is an incident, not a quiet pass. |
| Slack notification fails | Logged. The scan and the ticket still proceed. Slack is visibility, not the system of record. |

A ticket is opened whenever there is **confirmed work or incomplete knowledge**. The only no-ticket path is a complete scan that found no seats and no errors.

### 2. The work queue (JSM)

The ticket is the durable queue. Email is not.

| Situation | What we do |
| --- | --- |
| Ticket already exists for this offboarding run | The existing ticket is updated. We do not open a duplicate. |
| Ticket cannot be created after findings are saved | Findings stay in the audit log, Slack shows an error, and an alarm email fires. Work is not lost; the handoff failed and that is paged. |
| Hold / exception notes, or a known fixture ticket | The copilot refuses to reclaim. A human must clear the hold. |
| Operator asks to reclaim a different person than the ticket | Refused. The ticket is the source of truth for who is being processed. |

### 3. Reclaim (the revoke)

The broker is the only component allowed to hold GitHub / Linear / Jira write credentials. Requests that are malformed, unauthorized, or aimed at an unknown app are rejected before any vendor call.

| Situation | What we do |
| --- | --- |
| Human has not confirmed the plan | No revoke. Dry-run shows the plan only. |
| App was not confirmed active in the scan | Skipped. We do not revoke on a guess. |
| Seat was already reclaimed on a prior run | Treated as success. No repeat vendor call. |
| One app revokes and another fails | The successful app is recorded as done. The failed app is recorded with the error. Overall status is **partial**. The ticket stays open. |
| Vendor error on live revoke | That app is marked failed. Other requested apps still run. Results are commented on the ticket. |
| No findings exist for the ticket | Stop. We do not invent a user or an app list. |
| Jira comment from the broker fails | Logged. The revoke outcome is still stored in the audit log. Commenting is best-effort; the record of what happened is not. |

The copilot’s close-out rule is the same: **comment every app’s result; do not mark the ticket Done while any requested app is in error.**

---

## What leadership and operators will see

| Outcome | Meaning | Ticket | Who is notified |
| --- | --- | --- | --- |
| **Reclaimed** | Every confirmed leftover seat was removed. | Closed | Slack (routine) |
| **No licenses to reclaim** | Scan found nothing to take back (and no connector outage pretending to be “nothing”). | Closed or never opened | Slack (routine) |
| **Partial** | Some seats reclaimed; some still failed or unconfirmed. | Stays open | Slack (routine). Agent retries the remaining apps. |
| **Scan / work-queue error** | Inventory or ticket create broke. | Open if JSM succeeded; otherwise alarm | Slack plus **email** (infrastructure or queue failure) |

Everyday connector problems do **not** page email. They create tickets. Email is reserved for “the machine that was supposed to create the work item, or store the result, did not.”

All outcomes are written to the same audit table (`ohmgym-license-reclaim-logs`), with a correlation to the JSM issue. GRC and IT-Ops can see who requested the reclaim, when, and per app what happened.

---

## A live example (why this design exists)

On 15 August 2026 we reclaimed seats for Erin Patel on [SUP-3](https://buffett-dev.atlassian.net/browse/SUP-3).

1. **First live run:** GitHub membership was removed. Jira failed because the revoke targeted the wrong product-access group. The audit row was **partial**. The ticket was **not** closed.
2. **Correction and retry:** Jira was pointed at the correct group. GitHub was already gone, so it was skipped as already reclaimed — no second destructive call. Jira then succeeded. The row moved to **reclaimed**. The ticket was commented and closed.

That is the intended operating model: one vendor can fail without erasing the other result, the ticket remains the work queue, and a retry is safe.

---

## What we will not do

- Close a ticket while a requested reclaim is still in error.
- Treat “we could not check” as “there is nothing to reclaim.”
- Revoke an app whose scan result was an error, `not_assigned`, or unresolved identity.
- Let the AI copilot call GitHub, Linear, or Jira admin APIs with write keys.
- Undo Okta offboarding because license reclaim had a problem.
- Page the team by email for a single-app vendor blip that already landed in JSM.

---

## Residual risk (accepted for v1)

These are known limits, not surprises:

- **Jira:** v1 removes the Jira Software product-access group. A leaver who also holds Jira Service Management access may keep that product until a later pass.
- **GitHub identity:** Membership is login-based. If Okta has no GitHub username, the scan records `not_assigned` and does not query GitHub. A shadow org member invited outside Okta, with no profile login, will not be scanned. The broker still refuses revoke without a login.
- **No autonomous revoke yet.** Auto-reclaim without a human trigger is a later, opt-in step per app — after this human-gated path is trusted.
- **Sandbox credentials** today sometimes share a read and write token *value* per vendor. The IAM boundary still holds: the scanner role cannot read write secrets. Splitting to truly separate tokens is a follow-up.

---

## For engineers

The operational contract (failure classes, retries, DLQ, alarms, and “never classify auth failure as not-a-member”) is in the roadmap section [Error handling (Phase 2 contract)](../16-license-reclamation-human-in-the-loop-roadmap.md#error-handling-phase-2-contract). Phase 3 (broker) and Phase 4 (copilot) reuse that same vocabulary; they do not invent a second matrix.

| Layer | Where it is implemented |
| --- | --- |
| Scan continue-on-error, ticket-on-unknown | License Scanner Lambda; [phase-2 log](phase-2-license-scanner.md) |
| Allowlisted revoke, partial rollup, refuse uncertain seats | Reclaim Broker Lambda; [phase-3 log](phase-3-reclaim-broker.md) |
| Human confirm, comment errors, do not Done on failure | Cursor skill; [phase-4 log](phase-4-human-in-the-loop.md) |
