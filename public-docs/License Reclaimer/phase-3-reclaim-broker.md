# Phase 3 — Reclaim Broker

Allowlisted, deterministic revoke API: `POST /v1/licenses/reclaim` on a Lambda Function URL, gated on the Phase 2 scanner's findings. This is the **only** thing in the license-reclamation architecture allowed to hold GitHub/Linear/Jira write credentials (ADR-005) — a CLI (and later, a Cursor/Claude skill) calls the broker; nothing upstream of it ever touches a revoke token.

Roadmap: [16-license-reclamation-human-in-the-loop-roadmap.md](../16-license-reclamation-human-in-the-loop-roadmap.md). Prior logs: [phase-0-trials-and-credentials.md](phase-0-trials-and-credentials.md), [phase-1-jsm-foundation.md](phase-1-jsm-foundation.md), [phase-2-license-scanner.md](phase-2-license-scanner.md).

**Date:** 14 Aug 2026
**Status:** Code + Terraform + tests complete and validated locally (`terraform validate`, `pytest`). **Not yet applied** — no `terraform apply` or live SaaS/AWS write has been run for this phase; that is an explicit human-gated next step (see [Live apply — not yet done](#live-apply--not-yet-done)).

---

## What shipped

- Connector write functions on top of the Phase 2 read/scan connectors (`scripts/licenses/{github,jira,linear}_client.py`):
  - `github_client.remove_org_member(org, token, login)` — `DELETE /orgs/{org}/memberships/{login}`. 204/404 → `reclaimed` (404 = already gone, idempotent).
  - `linear_client.suspend_user(api_key, email, expected_org_uuid)` — resolves the human by email, then `userSuspend(id)`. Already-absent or already-inactive is idempotent `reclaimed`.
  - `jira_client.remove_product_access(email, write_token, read_token, auth_email, cloud_id, group_name)` — `DELETE /rest/api/3/group/user`, the write path this phase actually ships live (see [Jira write-path decision](#jira-write-path-decision-no-live-call-made) below).
  - `jira_client.deactivate_user(email, write_token, read_token, auth_email, cloud_id)` — `POST https://api.atlassian.com/users/{accountId}/manage/lifecycle/disable`, kept as a best-effort first attempt but expected to fail on this tenant.
- Lambda `ohmgym-license-reclaim-broker` (`lambdas/license_reclaim_broker/handler.py`): Function URL, shared-secret auth, GSI lookup by `jira_issue_key`, per-app eligibility + idempotency checks, continue-on-error revoke, DynamoDB `reclaim` list + row-status rollup, best-effort Jira comment.
- Terraform (`terraform/aws-license-reclaim/`, same stack as the scanner): `jira_issue_key` GSI on the existing table, `broker_iam.tf` (dedicated role — `Query`/`UpdateItem` only, `GetSecretValue` on the three write secrets + `jira-read` + a new webhook-secret shell), `broker_lambda.tf` (Function URL mirroring `terraform/aws/lambda.tf`'s `okta_activation_handler` pattern), broker Errors≥1 alarm.
- CLI `scripts/licenses/reclaim.py` — dry-run by default (repo convention), `--apply` for a live revoke, `--invoke` to call the deployed Function URL instead of running connectors locally.
- Tests: `lambdas/license_reclaim_broker/tests/` (27 tests — connectors + handler, `moto` for DynamoDB/Secrets Manager) and `tests/unit/test_license_reclaim_broker_infra_contract.py` (11 tests — IAM/Terraform shape). CI extended in `.github/workflows/license-scanner-ci.yml`.

---

## Jira write-path decision: no live call made

Phase 0 left this open: *"Jira product access — decide whether Phase 2 scans account exists or licensed product seats."* This phase resolves it **without a live API call**, for two reasons documented at build time and confirmed with the operator before writing any Terraform:

1. `deactivate_user`'s target (`api.atlassian.com/users/{accountId}/manage/lifecycle/disable`) is the Atlassian **User Management / org-admin API** — a different credential family than the Jira Cloud API token already in `.env`. It only works for org admins of a **domain-verified** Atlassian org. `buffett-dev.atlassian.net` is a personal site tied to a `@gmail.com` account, not a domain-claimed org, so this admin surface likely does not exist here regardless of token.
2. The only real Jira account on the site is `buffett.dev117@gmail.com` — the same account that authenticates every other Jira automation in this repo. Live-probing `deactivate_user` would mean firing a real deactivate call against that account, which is exactly the kind of live write this phase's build was gated on asking first.

Instead, `remove_product_access` (`DELETE /rest/api/3/group/user`, scope `manage:jira-configuration`) was built as the primary path — it works with a normal scoped Jira Cloud API token and a site-admin caller, both of which exist on `buffett-dev`. The operator added `manage:jira-configuration` to the existing `JIRA_API_TOKEN` (rather than minting a second token), so for now the "read" and "write" Jira secrets hold the same underlying token value — the IAM separation between the scanner role and the broker role is still structurally enforced (the scanner role cannot `GetSecretValue` on the write ARN even though the value happens to match today).

`config/licenses/apps.json`'s `jira.actions` is `["remove_product_access", "deactivate_user"]` — the broker tries them **in that order**, stopping at the first `"reclaimed"`. `deactivate_user` stays wired as a harmless best-effort second attempt in case a future tenant does have org-admin access, but is not expected to succeed here.

**Open before a live apply:** `product_group` in `apps.json` is a placeholder (`jira-servicedesk-users`). Confirm the real JSM product-access group name on `buffett-dev` via `GET /rest/api/3/groups/picker` before the first live reclaim — this is a read-only call, not yet run.

---

## Broker API contract

`POST /v1/licenses/reclaim` (Function URL, `authorization_type = "NONE"`; caller authenticates via a shared secret in the `Authorization` header — same pattern as `lambdas/okta_activation_handler`):

```json
{
  "issue_key": "SUP-2",
  "requested_by": "chris@ohmgym.com",
  "apps": ["github", "linear"],
  "dry_run": true
}
```

| Step | Behavior |
|---|---|
| Auth | Wrong/missing `Authorization` → 401. Non-POST → 405. |
| Allowlist | Unknown or disabled app key → 400, before any SaaS/DynamoDB call at all. |
| Lookup | `Query` the `jira_issue_key` GSI → 404 if no finding row exists for that ticket. |
| Eligibility (P3-R5) | Only apps with scan `status="active"` are `"eligible"`. `"error"` or `"identity_unresolved"` findings are **never** revoked — reported as `not_active_in_findings`. |
| Idempotency | An app with an existing `reclaim` entry already `"reclaimed"` is skipped as `already_reclaimed` — no repeat SaaS call. |
| Dry-run (default) | Returns the plan only. No write-secret fetch, no SaaS call, no DynamoDB write. |
| Live | Revokes each eligible app independently (one failure never blocks another); updates the row's `reclaim` list; rolls the row `status` up to `reclaimed` (all active apps succeeded) or `partial`. Posts a best-effort Jira comment summarizing outcomes. |

Write secrets are fetched lazily, only inside a live request, only for the app being revoked right then — a dry-run request never touches Secrets Manager for a revoke token (enforced by `test_broker_handler_never_fetches_write_secrets_at_import_time`).

---

## CLI usage (natural-language via Cursor today)

`scripts/licenses/reclaim.py` is what a service-desk agent runs — a formal Cursor/Claude skill file is Phase 4, but the CLI's flags are explicit enough that Cursor can already translate a prompt like *"reclaim GitHub and Linear for SUP-2, dry-run first"* into the right command today.

```bash
# Local dry-run: query DynamoDB directly, print the plan. No writes anywhere.
python scripts/licenses/reclaim.py --issue SUP-2 --apps github,linear

# Local apply: call connectors directly using .env write tokens (pre-deploy testing).
python scripts/licenses/reclaim.py --issue SUP-2 --apps github,linear --apply

# Invoke the deployed broker (the real Phase 4 path) — dry-run first, then apply.
python scripts/licenses/reclaim.py --issue SUP-2 --apps github,linear --invoke
python scripts/licenses/reclaim.py --issue SUP-2 --apps github,linear --invoke --apply
```

`--invoke` needs `BROKER_FUNCTION_URL` (from `terraform output broker_function_url`) and `BROKER_WEBHOOK_SECRET` (whatever value gets `put-secret-value`'d into `ohmgym-licenses/broker-webhook-secret`) in `.env` — no AWS credentials or SaaS write tokens touch the CLI's environment in that mode.

---

## Live apply — not yet done

Nothing in this list has been run. Recorded here so the next session (or Chris) can execute it deliberately, in order:

1. **Mint/confirm write credentials** (see chat history 14 Aug 2026 for the exact scopes):
   - `GITHUB_WRITE_TOKEN` — classic PAT, `admin:org`, minted by org owner `mamba4eva824`.
   - `LINEAR_WRITE_KEY` — personal API key from `buffett.dev117@gmail.com` (already admin in `it-systems-sandbox`); operator has since granted the existing `LINEAR_API_KEY` full access, so it may be reused.
   - `JIRA_WRITE_TOKEN` — done: `manage:jira-configuration` added to the existing `JIRA_API_TOKEN` on `buffett-dev`.
2. **Confirm the real JSM product-access group name** via `GET /rest/api/3/groups/picker` (read-only) and update `config/licenses/apps.json`'s `jira.product_group` placeholder.
3. `bash lambdas/license_scanner/build.sh && bash lambdas/license_reclaim_broker/build.sh`
4. `terraform -chdir=terraform/aws-license-reclaim apply` — adds the GSI to the **live** table (async backfill, no downtime expected on this small table), the broker role/Lambda/Function URL, the broker alarm, and the webhook-secret shell. Requires AWS profile `novatech-sandbox` (account `882248517627`), not `default`/`website-admin`.
5. Promote secrets:
   ```bash
   aws secretsmanager put-secret-value --region us-west-1 \
     --secret-id ohmgym-licenses/github-write --secret-string "$GITHUB_WRITE_TOKEN"
   aws secretsmanager put-secret-value --region us-west-1 \
     --secret-id ohmgym-licenses/linear-write --secret-string "$LINEAR_WRITE_KEY"
   aws secretsmanager put-secret-value --region us-west-1 \
     --secret-id ohmgym-licenses/jira-write --secret-string "$JIRA_WRITE_TOKEN"
   aws secretsmanager put-secret-value --region us-west-1 \
     --secret-id ohmgym-licenses/broker-webhook-secret --secret-string "$(openssl rand -hex 32)"
   ```
6. Dry-run against a real seeded leaver first (e.g. Erin Patel's `SUP-n` ticket from the 14 Aug batch), **then** `--apply` against a single app before trusting the full flow.

---

## IDs / names

| Resource | Value |
|---|---|
| AWS account / region | `882248517627` / `us-west-1` |
| Broker Lambda | `ohmgym-license-reclaim-broker` |
| Broker IAM role | `ohmgym-license-reclaim-broker-lambda-exec` |
| Table (shared with scanner) | `ohmgym-license-reclaim-logs` |
| New GSI | `jira_issue_key-index` |
| Broker alarm | `ohmgym-license-reclaim-broker-errors` |
| Webhook secret | `ohmgym-licenses/broker-webhook-secret` |
| Write secrets | `ohmgym-licenses/{github,linear,jira}-write` |

---

## Still open on this phase

- Live-apply steps above — none run yet.
- Confirm the real JSM product-access group name (currently a placeholder).
- Decide whether to mint a dedicated `LINEAR_WRITE_KEY` or keep reusing `LINEAR_API_KEY` now that it has full access (ADR-006 prefers separate secrets even when the underlying token is the same for now).
- Live end-to-end smoke test against a real seeded leaver once secrets are promoted.

## Not in this phase

- Cursor/Claude skill file, JSM-ticket auto-read, auto-transition-to-Done (Phase 4).
- Auto-reclaim without a human trigger (Phase 5, `auto_reclaim: true`).
- GRC/dashboard reclaim reporting (Phase 5).
