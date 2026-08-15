# Phase 3 — Reclaim Broker

Allowlisted, deterministic revoke API: `POST /v1/licenses/reclaim` on a Lambda Function URL, gated on the Phase 2 scanner's findings. This is the **only** thing in the license-reclamation architecture allowed to hold GitHub/Linear/Jira write credentials (ADR-005) — a CLI (and later, a Cursor/Claude skill) calls the broker; nothing upstream of it ever touches a revoke token.

Roadmap: [16-license-reclamation-human-in-the-loop-roadmap.md](../16-license-reclamation-human-in-the-loop-roadmap.md). Prior logs: [phase-0-trials-and-credentials.md](phase-0-trials-and-credentials.md), [phase-1-jsm-foundation.md](phase-1-jsm-foundation.md), [phase-2-license-scanner.md](phase-2-license-scanner.md).

**Date:** 14 Aug 2026
**Status:** Applied and live in `us-west-1` (account `882248517627`). `terraform apply` ran 14 Aug ~11:07pm UTC (11 resources added, 2 changed, 0 destroyed) under profile `novatech-sandbox`. Broker Lambda, Function URL, GSI, and alarm are all healthy. Write secrets not yet promoted with real values and no live reclaim has been executed — see [Live apply](#live-apply--applied-secrets-not-yet-promoted).

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

Instead, `remove_product_access` (`DELETE /rest/api/3/group/user`, scope `manage:jira-configuration`) was built as the primary path — it works with a normal scoped Jira Cloud API token and a site-admin caller, both of which exist on `buffett-dev`. `JIRA_API_TOKEN` in `.env` now carries all four needed scopes (`read:jira-work`, `read:jira-user`, `write:jira-work`, `manage:jira-configuration`) on one token — an earlier attempt that only added `manage:jira-configuration` to the token's scope list via Atlassian's "Edit scopes" screen silently *replaced* the existing scopes instead of adding to them (401 `"scope does not match"` on every call, including `/myself`, until it was re-minted with all four together). So for now the "read" and "write" Jira secrets hold the same underlying token value — the IAM separation between the scanner role and the broker role is still structurally enforced (the scanner role cannot `GetSecretValue` on the write ARN even though the value happens to match today).

`config/licenses/apps.json`'s `jira.actions` is `["remove_product_access", "deactivate_user"]` — the broker tries them **in that order**, stopping at the first `"reclaimed"`. `deactivate_user` stays wired as a harmless best-effort second attempt in case a future tenant does have org-admin access, but is not expected to succeed here.

**Confirmed (14 Aug 2026):** `product_group` in `apps.json` is now the real group — `jira-servicemanagement-users-buffett-dev` (groupId `7f60582b-683f-47de-8611-b6f0e0769866`), found via `GET /rest/api/3/user/groups` on the site admin account (both read-only). The site admin is also in `jira-users-buffett-dev` (base Jira Software access, a separate product); `remove_product_access` only removes the one configured group, so a leaver who also holds `jira-users-buffett-dev` keeps base Jira access after reclaim — the JSM seat is the billed product this phase targets, so that's accepted as out of scope for v1, not a bug.

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

## Live apply — applied, secrets not yet promoted

Updated 14 Aug 2026, ~11:07pm: `terraform apply` ran successfully.

```
Apply complete! Resources: 11 added, 2 changed, 0 destroyed.

broker_function_name       = "ohmgym-license-reclaim-broker"
broker_function_url        = "https://qfyzllebdanedjk7qbrxehciei0nhxim.lambda-url.us-west-1.on.aws/"
broker_role_arn            = "arn:aws:iam::882248517627:role/ohmgym-license-reclaim-broker-lambda-exec"
broker_webhook_secret_name = "ohmgym-licenses/broker-webhook-secret"
```

The DynamoDB `jira_issue_key-index` GSI backfill took ~6 minutes (normal for a new GSI regardless of table size) but is confirmed `ACTIVE`. The broker Lambda is `Active`/`Successful`. `terraform.tfvars`/state are gitignored and local-only (matches Phase 2's setup) — this stack still has no remote backend.

Steps 1-4 below are done. Remaining before a live reclaim: promote the write secrets (step 5) and a dry-run smoke test (step 6).

1. **Write credentials — done, all via the "upgrade the existing token's scope" pattern (no new env vars):**
   - GitHub: `GITHUB_READ_TOKEN` re-minted with `admin:org` (confirmed via the `X-OAuth-Scopes` response header — includes `read:org` implicitly). No separate `GITHUB_WRITE_TOKEN`; `reclaim.py`'s local `--apply` path falls back to `GITHUB_READ_TOKEN` when `GITHUB_WRITE_TOKEN` is unset.
   - Linear: `LINEAR_API_KEY` granted full/admin access in place. No separate `LINEAR_WRITE_KEY`; same fallback pattern already existed for this one.
   - Jira: `JIRA_API_TOKEN` re-minted with all four scopes together (`read:jira-work`, `read:jira-user`, `write:jira-work`, `manage:jira-configuration`) — a first attempt that only *added* `manage:jira-configuration` via Atlassian's "Edit scopes" screen replaced the scope set instead of extending it (401 `"scope does not match"` on every call, including `/myself`, until re-minted with all four at once).
   - **Consequence for Secrets Manager:** because none of these are distinct read/write token *values*, `put-secret-value` for each app's `-read` and `-write` secret will use the **same string** for now. The two Secrets Manager entries and the IAM role separation (scanner can't read write ARNs) still hold as a structural boundary — see [Jira write-path decision](#jira-write-path-decision-no-live-call-made) above for the full rationale.
2. **JSM product-access group — confirmed:** `jira-servicemanagement-users-buffett-dev`, already set in `config/licenses/apps.json`.
3. **Done.** `bash lambdas/license_scanner/build.sh && bash lambdas/license_reclaim_broker/build.sh`
4. **Done.** `terraform -chdir=terraform/aws-license-reclaim apply` under AWS profile `novatech-sandbox` (account `882248517627`) — added the GSI to the **live** table (backfill took ~6 minutes, confirmed `ACTIVE`, no downtime), the broker role/Lambda/Function URL, the broker alarm, and the webhook-secret shell.
5. **Not yet done.** Promote secrets (values match the `-read` secret for each app today, per the note above):
   ```bash
   aws secretsmanager put-secret-value --region us-west-1 \
     --secret-id ohmgym-licenses/github-write --secret-string "$GITHUB_READ_TOKEN"
   aws secretsmanager put-secret-value --region us-west-1 \
     --secret-id ohmgym-licenses/linear-write --secret-string "$LINEAR_API_KEY"
   aws secretsmanager put-secret-value --region us-west-1 \
     --secret-id ohmgym-licenses/jira-write --secret-string "$JIRA_API_TOKEN"
   aws secretsmanager put-secret-value --region us-west-1 \
     --secret-id ohmgym-licenses/jira-read --secret-string "$JIRA_API_TOKEN"
   aws secretsmanager put-secret-value --region us-west-1 \
     --secret-id ohmgym-licenses/broker-webhook-secret --secret-string "$(openssl rand -hex 32)"
   ```
   (`jira-read` needs re-promoting too — its previously-promoted value, if any, was the old broken-scope token.)
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
| Broker Function URL | `https://qfyzllebdanedjk7qbrxehciei0nhxim.lambda-url.us-west-1.on.aws/` |
| Webhook secret | `ohmgym-licenses/broker-webhook-secret` |
| Write secrets | `ohmgym-licenses/{github,linear,jira}-write` |

---

## Still open on this phase

- `terraform apply`, secret promotion, and the first live reclaim — none run yet (steps 3-6 above).
- Longer-term: rotate GitHub/Linear/Jira to genuinely separate least-privilege read vs. write tokens instead of one combined-scope token per app (today's fast-path for a sandbox demo, not the ADR-006 end state).
- `remove_product_access` only removes one group (`jira-servicemanagement-users-buffett-dev`); a leaver also in `jira-users-buffett-dev` keeps base Jira access after reclaim — accepted for v1 (JSM seat is the billed product), revisit if that changes.
- Live end-to-end smoke test against a real seeded leaver once secrets are promoted.

## Not in this phase

- Cursor/Claude skill file, JSM-ticket auto-read, auto-transition-to-Done (Phase 4).
- Auto-reclaim without a human trigger (Phase 5, `auto_reclaim: true`).
- GRC/dashboard reclaim reporting (Phase 5).
