# Phase 2 — License Scanner Lambda

Deterministic scan after Okta deactivate: GitHub / Linear / Jira membership → DynamoDB + JSM ticket (when seats remain **or** the scan is incomplete) + Slack `#leaver-it-ops`. Error handling is the handler contract, not an afterthought (ADR-010 / ADR-011).

Roadmap: [16-license-reclamation-human-in-the-loop-roadmap.md](../16-license-reclamation-human-in-the-loop-roadmap.md). Prior logs: [phase-0-trials-and-credentials.md](phase-0-trials-and-credentials.md), [phase-1-jsm-foundation.md](phase-1-jsm-foundation.md).

**Date:** 14 Aug 2026  
**Status:** Live in account `882248517627` / `us-west-1`. Scanner stack applied; read secrets promoted; Okta `githubUsername` schema applied. Offboarding `leaver.completed` emit patched in-place (no Terraform state for `aws-offboarding` in this worktree). Dashboard (P2-R10) deferred. First scheduled batch armed for 17:00 America/Los_Angeles 14 Aug 2026; live JSM create from this Lambda is not yet observed.

---

## What shipped

- Offboarding emits `leaver.completed` (`source=ohmgym.offboarding`) after each successful deactivate. PutEvents failure is logged and does **not** undo Okta deactivate (ADR-001).
- Scanner Lambda `ohmgym-license-scanner`: isolated connectors, always persist, ticket or reuse JSM request type `4`, Slack on every run, raise only on infra / JSM create fail / all connectors failed.
- Connectors: `scripts/licenses/{github,linear,jira}_client.py`. Figma stays `enabled: false`.
- Terraform stack `terraform/aws-license-reclaim/`: EventBridge rule (`maximum_retry_attempts = 2`), SQS DLQ `ohmgym-license-scanner-dlq`, DynamoDB `ohmgym-license-reclaim-logs`, read-only Secrets Manager IAM, SNS Errors ≥ 1 alarm.
- Okta profile attribute `githubUsername` in `config/okta/desired-state.json` (open question 6). Missing value → `not_assigned`; GitHub membership API is not called; no identity-only ticket (P2-R15). Historical 14 Aug DynamoDB rows may still show `identity_unresolved`.
- CLI: `scripts/licenses/scan_cli.py --dry-run` (local `.env` tokens) or `--invoke` (deployed Lambda).
- Unit tests: `lambdas/license_scanner/tests/` plus offboarding emit tests. CI: `.github/workflows/license-scanner-ci.yml`.

---

## Live apply (14 Aug 2026)

Use AWS profile `novatech-sandbox` (account `882248517627`). The `default` / `website-admin` profile is a different account and will not see these functions.

| Step | Outcome |
|---|---|
| Okta schema | `python scripts/okta/reconcile_config.py --apply` added `githubUsername`. Extra Clinical group/rule/Slack assignment left alone. |
| Scanner stack | `bash lambdas/license_scanner/build.sh` then `terraform -chdir=terraform/aws-license-reclaim apply` (23 resources). |
| Read secrets | `put-secret-value` on `ohmgym-licenses/{github,linear,jira}-read` from gitignored `.env`. `*-write` shells empty (Phase 3). |
| Offboarding emit | Live Lambda was still the 3 Jul package: no PutEvents, no `events:PutEvents` IAM. This worktree has no `aws-offboarding` Terraform state, so the zip was rebuilt and `update-function-code` + `put-role-policy` (`ohmgym-offboarding-workflow-events`) applied in-place. Do not `terraform apply` that stack from here without importing state. |
| Smoke | `aws lambda invoke` with `dry_run: true` — Erin `ticketed` (GitHub + Jira); Marcus `partial` / `ticket_wanted=true` (`identity_unresolved`). No JSM/DDB/Slack on dry-run. |

SNS topic `ohmgym-license-scanner-alarms` subscribed `weinreichchris@gmail.com`. Confirm the subscription email or Errors ≥ 1 will not page.

`.env` lives in the main checkout and must be symlinked into this worktree (same as Phase 1).

---

## Seeded leavers (14 Aug 2026)

Five Okta users have `endDate=2026-08-14` so the 17:00 America/Los_Angeles offboarding schedule picks them up (`ACTIVE` or `PROVISIONED`). Mixed seats on purpose — not identical membership on all three apps (P0-R5).

| Person | Okta login | Okta status | `githubUsername` | GitHub | Linear | Jira | Scanner ticket |
|---|---|---|---|---|---|---|---|
| Erin Patel | `chris+access-review-01@ohmgym.com` | ACTIVE | `erin-patel` | Seat | Not a member | Seat | Yes — github, jira |
| Marcus Lee | `chris+access-review-02@ohmgym.com` | ACTIVE | — | Not assigned | Not a member | Not a member | No — `not_assigned` (deliberate no-license user) |
| Ned Stark | `chris+ned@ohmgym.com` | PROVISIONED | — | Not assigned | Not a member | Seat | Yes — jira |
| Tyrion Lannister | `chris+tyrion@ohmgym.com` | ACTIVE | — | Not assigned | Not a member | Seat | Yes — jira |
| Elena Vasquez | `chris+elena.vasqueuz@ohmgym.com` | ACTIVE | — | Not assigned | Seat | Not a member | Yes — linear |

Elena’s Okta login is the typo `vasqueuz`. GitHub org members at seed time: `erin-patel`, `mamba4eva824`. Tyrion still had a pending Owner invite by email; that is not membership.

Marcus is the clean-seat negative: no GitHub / Linear / Jira seats. Empty `githubUsername` is `not_assigned` (never mapped in Okta), not an incomplete scan — no ticket. A GitHub login that 404s plus Linear/Jira `not_member` is the other no-ticket path. 14 Aug live DynamoDB rows still show `identity_unresolved` until a new scan.

Offboarding itself does **not** create JSM issues. Each successful deactivate emits `leaver.completed`; the scanner opens one License Reclamation request (`SUP`, request type `"4"`) when any enabled app is `active` or `error`. Against this matrix that is four tickets (Marcus does not ticket).

---

## Error-handling contract (implemented)

Continue per app; raise only on infrastructure or work-queue failure.

| Class | Handler |
|---|---|
| Infra (bad payload, secret miss, DynamoDB PutItem fail) | Best-effort persist; Slack; **raise** (SNS) |
| Connector unknown (429/5xx, timeout) | `apps[].error_class=retryable`; keep scanning |
| Misconfig (GitHub 401/403, Jira site URL, Linear wrong org) | `misconfig`; keep scanning; ticket |
| Not a member (GitHub 404, Linear absent, Jira empty search) | `not_member` |
| Not assigned (no `githubUsername`) | No GitHub HTTP; `status=not_assigned`; no identity-only ticket |
| Work-queue fail (JSM create 5xx after persist) | DDB `status=error`; Slack; **raise** |
| All enabled connectors failed | Ticket + Slack + **raise** (`all_connectors_failed`) |
| Slack fail | Log; do not raise |

Row `status`: `clean` (no ticket) · `ticketed` · `partial` (≥1 error and ≥1 non-error enabled result) · `error`. Unknown never looks like `clean`.

---

## Operator replay

Rebuild + apply scanner after handler or zip changes:

```bash
export AWS_PROFILE=novatech-sandbox AWS_REGION=us-west-1
bash lambdas/license_scanner/build.sh
terraform -chdir=terraform/aws-license-reclaim apply
```

Promote read tokens only if they rotated:

```bash
aws secretsmanager put-secret-value --region us-west-1 \
  --secret-id ohmgym-licenses/github-read --secret-string "$GITHUB_READ_TOKEN"
aws secretsmanager put-secret-value --region us-west-1 \
  --secret-id ohmgym-licenses/linear-read --secret-string "$LINEAR_API_KEY"
aws secretsmanager put-secret-value --region us-west-1 \
  --secret-id ohmgym-licenses/jira-read --secret-string "$JIRA_API_TOKEN"
```

`jira-read` is the scoped token (`read:jira-user` + `write:jira-work`) used for user search **and** JSM issue create.

Local dry-run (no JSM/DDB/Slack):

```bash
python scripts/licenses/scan_cli.py --email chris+access-review-01@ohmgym.com \
  --okta-id 00u163ktpumc0fZmD698 --run-id local --run-date 2026-08-14 \
  --github-username erin-patel --dry-run
```

---

## IDs / names

| Resource | Value |
|---|---|
| AWS account / region | `882248517627` / `us-west-1` |
| Lambda | `ohmgym-license-scanner` |
| Table | `ohmgym-license-reclaim-logs` |
| DLQ | `ohmgym-license-scanner-dlq` |
| Event | `ohmgym.offboarding` / `leaver.completed` |
| EventBridge rule | `ohmgym-license-scanner-leaver-completed` |
| SNS | `ohmgym-license-scanner-alarms` |
| JSM request type | `"4"` on project `SUP` |
| GitHub org | `ohmgym-sandbox` |
| Linear org uuid | `2cb9e2d3-f42b-42a1-a066-8bc4006c2624` |
| Jira gateway | `https://api.atlassian.com/ex/jira/{cloudId}/...` |
| Offboarding schedule | `cron(0 17 * * ? *)` America/Los_Angeles |

---

## Still open on this phase

- Confirm SNS email for `ohmgym-license-scanner-alarms`.
- Observe the 14 Aug 17:00 PT batch: five Okta deactivates → five `leaver.completed` → five License Reclamation tickets (or DDB `error` + SNS if JSM create fails).
- Import or reconstruct `terraform/aws-offboarding` state so the next offboarding change is not another CLI patch.

---

## Not in this phase

- Phase 3 reclaim broker / write tokens in Cursor
- Dashboard / workflows card (P2-R10)
- Figma connector

---

## Data model addendum (14 Aug 2026, during Phase 3 build)

Added `first_name` / `last_name` to `leaver.completed` (from Okta `profile.firstName`/`lastName`, already used elsewhere in the offboarding audit table and Slack summary) and to the `ohmgym-license-reclaim-logs` item persisted by this Lambda. Both fields are optional on the event — `_validate_payload` defaults them to `""` rather than requiring them, so older or hand-built (CLI/dry-run) `leaver.completed` payloads without the fields still validate. No Terraform change needed (DynamoDB only declares attributes used as keys/index hash keys; this is a plain, non-indexed item attribute).
