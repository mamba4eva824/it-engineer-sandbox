# Phase 2 — License Scanner Lambda

Deterministic scan after Okta deactivate: GitHub / Linear / Jira membership → DynamoDB + JSM ticket (when seats remain **or** the scan is incomplete) + Slack `#leaver-it-ops`. Error handling is the handler contract, not an afterthought (ADR-010 / ADR-011).

Roadmap: [16-license-reclamation-human-in-the-loop-roadmap.md](../16-license-reclamation-human-in-the-loop-roadmap.md). Prior logs: [phase-0-trials-and-credentials.md](phase-0-trials-and-credentials.md), [phase-1-jsm-foundation.md](phase-1-jsm-foundation.md).

**Date:** 14 Aug 2026  
**Status:** Code complete. Live `terraform apply`, secret promote, and Okta `githubUsername` reconcile are operator steps (not run in this change). Dashboard (P2-R10) deferred.

---

## What shipped

- Offboarding emits `leaver.completed` (`source=ohmgym.offboarding`) after each successful deactivate. PutEvents failure is logged and does **not** undo Okta deactivate (ADR-001).
- Scanner Lambda `ohmgym-license-scanner`: isolated connectors, always persist, ticket or reuse JSM request type `4`, Slack on every run, raise only on infra / JSM create fail / all connectors failed.
- Connectors: `scripts/licenses/{github,linear,jira}_client.py`. Figma stays `enabled: false`.
- Terraform stack `terraform/aws-license-reclaim/`: EventBridge rule (`maximum_retry_attempts = 2`), SQS DLQ `ohmgym-license-scanner-dlq`, DynamoDB `ohmgym-license-reclaim-logs`, read-only Secrets Manager IAM, SNS Errors ≥ 1 alarm.
- Okta profile attribute `githubUsername` in `config/okta/desired-state.json` (open question 6). Missing value → `identity_unresolved`; GitHub membership API is not called; ticket still opens (P2-R15).
- CLI: `scripts/licenses/scan_cli.py --dry-run` (local `.env` tokens) or `--invoke` (deployed Lambda).
- Unit tests: `lambdas/license_scanner/tests/` (24) plus offboarding emit tests. CI: `.github/workflows/license-scanner-ci.yml`.

---

## Error-handling contract (implemented)

Continue per app; raise only on infrastructure or work-queue failure.

| Class | Handler |
|---|---|
| Infra (bad payload, secret miss, DynamoDB PutItem fail) | Best-effort persist; Slack; **raise** (SNS) |
| Connector unknown (429/5xx, timeout) | `apps[].error_class=retryable`; keep scanning |
| Misconfig (GitHub 401/403, Jira site URL, Linear wrong org) | `misconfig`; keep scanning; ticket |
| Not a member (GitHub 404, Linear absent, Jira empty search) | `not_member` |
| Identity unresolved (no `githubUsername`) | No GitHub HTTP; ticket |
| Work-queue fail (JSM create 5xx after persist) | DDB `status=error`; Slack; **raise** |
| All enabled connectors failed | Ticket + Slack + **raise** (`all_connectors_failed`) |
| Slack fail | Log; do not raise |

Row `status`: `clean` (no ticket) · `ticketed` · `partial` (≥1 error and ≥1 non-error enabled result) · `error`. Unknown never looks like `clean`.

---

## Operator steps (before the first live scan)

1. **Okta schema.** `python scripts/okta/reconcile_config.py --apply` so `githubUsername` exists. Set it on demo users, e.g. `chris@ohmgym.com` → `mamba4eva824`. P0-R5 seeding (same emails on GitHub/Linear/Jira) is still open.
2. **Build + apply.**
   ```bash
   bash lambdas/license_scanner/build.sh
   bash lambdas/offboarding_workflow/build.sh   # PutEvents IAM + emit
   terraform -chdir=terraform/aws-license-reclaim apply
   terraform -chdir=terraform/aws-offboarding apply
   ```
3. **Promote `.env` tokens to Secrets Manager** (scanner IAM cannot read write shells):
   ```bash
   aws secretsmanager put-secret-value --region us-west-1 \
     --secret-id ohmgym-licenses/github-read --secret-string "$GITHUB_READ_TOKEN"
   aws secretsmanager put-secret-value --region us-west-1 \
     --secret-id ohmgym-licenses/linear-read --secret-string "$LINEAR_API_KEY"
   aws secretsmanager put-secret-value --region us-west-1 \
     --secret-id ohmgym-licenses/jira-read --secret-string "$JIRA_API_TOKEN"
   ```
   `jira-read` is the existing scoped token (`read:jira-user` + `write:jira-work`) used for user search **and** JSM issue create. `*-write` secrets stay empty until Phase 3.
4. **Confirm the SNS email** for `ohmgym-license-scanner-alarms`.
5. **Dry-run locally** (no JSM/DDB/Slack):
   ```bash
   python scripts/licenses/scan_cli.py --email chris@ohmgym.com --okta-id 00u... \
     --run-id local --run-date 2026-08-14 --github-username mamba4eva824 --dry-run
   ```

`.env` lives in the main checkout and must be symlinked into this worktree (same as Phase 1).

---

## IDs / names

| Resource | Value |
|---|---|
| Lambda | `ohmgym-license-scanner` |
| Table | `ohmgym-license-reclaim-logs` |
| DLQ | `ohmgym-license-scanner-dlq` |
| Event | `ohmgym.offboarding` / `leaver.completed` |
| JSM request type | `"4"` on project `SUP` |
| GitHub org | `ohmgym-sandbox` |
| Linear org uuid | `2cb9e2d3-f42b-42a1-a066-8bc4006c2624` |
| Jira gateway | `https://api.atlassian.com/ex/jira/{cloudId}/...` |

---

## Not in this phase

- Phase 3 reclaim broker / write tokens in Cursor
- Dashboard / workflows card (P2-R10)
- Figma connector
- Live `terraform apply`
