# Phase 4 — Human-in-the-loop Cursor skill

Service-desk loop: an IT-Ops agent prompts Cursor with a JSM issue key. The copilot reads the ticket via Atlassian MCP, calls the Phase 3 reclaim broker (`scripts/licenses/reclaim.py --invoke`), comments a brief close-out, and transitions the ticket toward Done. The agent never holds GitHub / Linear / Jira write tokens and never writes DynamoDB — the broker is still the only SaaS write path (ADR-005).

Roadmap: [16-license-reclamation-human-in-the-loop-roadmap.md](../16-license-reclamation-human-in-the-loop-roadmap.md). Prior logs: [phase-0-trials-and-credentials.md](phase-0-trials-and-credentials.md), [phase-1-jsm-foundation.md](phase-1-jsm-foundation.md), [phase-2-license-scanner.md](phase-2-license-scanner.md), [phase-3-reclaim-broker.md](phase-3-reclaim-broker.md).

**Date:** 15 Aug 2026
**Status:** Skill shipped; live end-to-end test complete on [SUP-3](https://buffett-dev.atlassian.net/browse/SUP-3) (Erin Patel).

---

## What shipped

- Cursor project skill [`.cursor/skills/reclaim-licenses/SKILL.md`](../../.cursor/skills/reclaim-licenses/SKILL.md) (auto-invoke on reclaim / License Reclamation prompts). Not under gitignored `.claude/`.
- Runbook: MCP `getJiraIssue` first (never invent user/apps) → refuse holds / wrong leaver / fixture `SUP-2` → dry-run `--invoke` → **stop for human confirm** → `--invoke --apply` → MCP summary comment → discover Done transition → read-only DynamoDB verify.
- `--invoke` only. Local connector `--apply` is out of bounds for this phase (that path uses `.env` write tokens and bypasses the broker).

Ticket fields (unchanged from Phase 1):

| Field | Jira id |
|---|---|
| Leaver email | `customfield_10138` |
| Okta user ID | `customfield_10139` |
| Offboarding run ID | `customfield_10140` |
| Apps requiring action | `customfield_10141` |
| Hold / exception notes | `customfield_10142` |

Cloud ID: `359c6979-fbf2-459e-b948-9feb032a082e`.

### JSM workflow caveat

From **To Do**, License Reclamation issues expose `Start` (→ In Progress, id `81`) and `In review` (→ Pending, id `91`) — no direct Done. The skill calls `getTransitionsForJiraIssue` at the current status, prefers a target whose `statusCategory.key` is `done`, and if none exists takes `Start` then re-queries. Resolution is set to `Done` if the resolve screen requires it.

---

## Live test — SUP-3 Erin Patel

Target chosen because it is the only 14 Aug 17:00 PT scanner ticket with two confirmed seats and no scan errors.

| | |
|---|---|
| Issue | [SUP-3](https://buffett-dev.atlassian.net/browse/SUP-3) |
| Leaver | Erin Patel / `chris+access-review-01@ohmgym.com` |
| Okta id | `00u163ktpumc0fZmD698` |
| Apps | `github, jira` |
| GitHub login | `erin-patel` |
| Jira group | `jira-users-buffett-dev` (Jira Software product-access group) |

First `--invoke --apply` (15 Aug 16:40 UTC): GitHub `reclaimed` (204); Jira `error_class=misconfig` (401 on `deactivate_user`) because `remove_product_access` targeted the JSM group she was not in. Broker row `status=partial`. Retargeted `product_group` to `jira-users-buffett-dev` and retried Jira only (GitHub `already_reclaimed`).

Second `--invoke --apply` (15 Aug 16:59 UTC): Jira `reclaimed` (`remove_product_access`, HTTP 200) from `jira-users-buffett-dev`. Row `status=reclaimed`. Seat checks: GitHub `erin-patel` → 404; Erin no longer in `jira-users-buffett-dev`. [SUP-3](https://buffett-dev.atlassian.net/browse/SUP-3) commented and transitioned **Done** (Start → Resolved).

---

## IDs / names

| Resource | Value |
|---|---|
| Skill | `.cursor/skills/reclaim-licenses/SKILL.md` |
| CLI | `scripts/licenses/reclaim.py --invoke` |
| Broker Function URL | `https://qfyzllebdanedjk7qbrxehciei0nhxim.lambda-url.us-west-1.on.aws/` |
| Table | `ohmgym-license-reclaim-logs` |
| GSI | `jira_issue_key-index` |
| AWS profile / region | `novatech-sandbox` / `us-west-1` |

Env for `--invoke` (gitignored `.env`): `BROKER_FUNCTION_URL`, `BROKER_WEBHOOK_SECRET`. No SaaS write tokens in the Cursor path.

---

## Not in this phase

- Auto-reclaim without a human trigger (Phase 5, `auto_reclaim: true`).
- GRC/dashboard reclaim reporting (Phase 5).
- Re-seeding Erin’s GitHub/Jira seats after the demo (needed for a replayable interview run).
