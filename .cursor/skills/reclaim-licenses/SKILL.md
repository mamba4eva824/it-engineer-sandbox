---
name: reclaim-licenses
description: Reclaims non-SCIM SaaS seats for a JSM License Reclamation ticket by calling the license reclaim broker. Use when the user asks to reclaim licenses, close a SUP License Reclamation ticket, revoke GitHub/Linear/Jira seats after offboarding, or run the Phase 4 human-in-the-loop reclaim flow.
---

# Reclaim licenses (human-in-the-loop)

IT-Ops copilot for JSM **License Reclamation** tickets. Read the ticket, call the **broker** (the only SaaS write path), comment results, transition Done. Never call GitHub / Linear / Jira admin APIs with write tokens. Never `UpdateItem` DynamoDB.

Roadmap: `public-docs/16-license-reclamation-human-in-the-loop-roadmap.md`. Broker CLI: `scripts/licenses/reclaim.py`. Fields: `config/jira/field-mapping.json`. Allowlist: `config/licenses/apps.json`.

## Constants

- Cloud ID: `359c6979-fbf2-459e-b948-9feb032a082e` (`buffett-dev`)
- Project: `SUP`. Request type id `4`.
- Leaver email: `customfield_10138`
- Okta user ID: `customfield_10139`
- Offboarding run ID: `customfield_10140`
- Apps requiring action: `customfield_10141` (comma-separated keys)
- Hold / exception notes: `customfield_10142`
- Table: `ohmgym-license-reclaim-logs`. GSI: `jira_issue_key-index`. Region: `us-west-1`. Profile: `novatech-sandbox`.
- Fixture — do not reclaim: `SUP-2`

`--invoke` needs `BROKER_FUNCTION_URL` and `BROKER_WEBHOOK_SECRET` in `.env`. Cursor must not use `GITHUB_*` / `LINEAR_*` / `JIRA_API_TOKEN` write paths. `requested_by` = `--requested-by` or `$JIRA_EMAIL`.

## Procedure

### 1. Load the ticket

`getJiraIssue` with the cloud ID above. Fields: `summary`, `status`, `description`, `comment`, plus the five reclaim custom fields.

Parse `customfield_10141` as app keys (split on comma, trim, lowercase). Ignore `none`, empty, `figma`, and anything not `enabled: true` in `config/licenses/apps.json`.

**Refuse (no broker `--apply`) when any of these hold:**

- Issue key is `SUP-2`, or hold notes say do not reclaim / sample / fixture.
- The user named a leaver email that is **not** `customfield_10138` (P4-R7).
- Requested apps are missing from the ticket list or from the allowlist.
- Ticket has no confirmed apps (`none` / empty) and the user asked to revoke seats.

When apps are `none` / empty and the operator asks to **close** the ticket (not revoke seats): comment the close-out, transition toward Done, and expect DynamoDB overall `status` = `No Licenses to Reclaim`. Scanner persist and broker/CLI reclaim rollup write that status when there are no scan-`active` seats (including `not_assigned` or historical `identity_unresolved` with no confirmed seats). Connector `error` (misconfig / retryable) still rolls up to `partial` / `error` so unknown never looks clear (P2-R13). Do not invent a user or an app list. If the prompt omits apps, use the ticket list. If it names a subset that is on the ticket, use the subset.

### 2. Propose the plan

In chat, state issue key, leaver email, Okta id, apps to reclaim, and any hold/error notes. Then dry-run (no `--apply`):

```bash
python scripts/licenses/reclaim.py --issue {KEY} --apps {comma,list} --invoke
```

`--invoke` only. Do not run local connector `--apply`.

Eligible apps proceed. `not_active_in_findings` / `already_reclaimed` stay skipped. Broker never revokes scan `error`, `not_assigned`, or `identity_unresolved`. Treat `not_assigned` like `not_member` (never mapped in Okta; not unresolved identity).

### 3. Human confirm (required)

Stop. Do not `--apply` until the operator explicitly confirms in this chat (e.g. "apply", "go", "reclaim them"). Plan approval in a prior turn counts only when it named this issue key and these apps.

### 4. Live reclaim

```bash
python scripts/licenses/reclaim.py --issue {KEY} --apps {comma,list} --invoke --apply \
  --requested-by "$JIRA_EMAIL"
```

### 5. Comment, Done, verify

If any requested eligible app returned `error`, comment the per-app results and **do not** transition Done (P4-R6).

Otherwise `addCommentToJiraIssue` (markdown), then close:

```
License reclaim complete for {leaver_email} via broker (`--invoke --apply`).

- {app}: {outcome}
- {app}: {outcome}

DynamoDB `ohmgym-license-reclaim-logs` status={row_status}. requested_by={email}. correlation_id=JIRA-{KEY}.
```

Transition toward Done:

1. `getTransitionsForJiraIssue` for the current status.
2. Prefer a transition whose target `statusCategory.key` is `done` (name Done / Resolved / Close).
3. If none, take `Start` (→ In Progress) and re-query.
4. If the resolve screen requires it, set `resolution` to `Done`.

Verify **read-only**:

```bash
aws dynamodb query --region us-west-1 --profile novatech-sandbox \
  --table-name ohmgym-license-reclaim-logs \
  --index-name jira_issue_key-index \
  --key-condition-expression "jira_issue_key = :k" \
  --expression-attribute-values '{":k":{"S":"{KEY}"}}'
```

Expect `status=reclaimed` when every scan-`active` app succeeded, `No Licenses to Reclaim` when none were active, else `partial`. Confirm `reclaim[]`, `reclaimed_by`, `reclaimed_at` after a live reclaim. Do not `UpdateItem`.

Optional seat checks (read APIs / scanner connectors only): GitHub member 404; Linear inactive/absent; Jira not in `jira-users-buffett-dev` or `confluence-users-buffett-dev`. JSM group `jira-servicemanagement-users-buffett-dev` may remain — v1 accepted.

## Failure handling

Comment broker/scanner errors on the ticket. One app error must not hide others. Do not Done while any requested app is `error`. `already_reclaimed` is success (idempotent). Broker 404 (no findings row) → stop; do not create a ticket or invent keys.

## Example prompt

> Pull SUP-3. For the leaver on the ticket, reclaim GitHub and Jira via the license broker. Comment results and set Done if both succeed.
