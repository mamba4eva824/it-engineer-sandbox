# Ohmgym Offboarding Workflow — Scheduled AWS → Okta → Slack Deactivation

The **proactive leaver** half of the JML pipeline. Every day at **5:00 PM America/Los_Angeles**, EventBridge Scheduler invokes a Lambda that queries Okta for users whose `(status == ACTIVE or PROVISIONED) and profile.endDate == today_PT`, revokes sessions, deactivates each account, writes audit rows to DynamoDB, and posts one batch summary to `#leaver-it-ops`. SCIM cascades Slack (and GWS for real SCIM users) without code in this Lambda.

Mirror of [10-aws-scheduled-onboarding-workflow.md](10-aws-scheduled-onboarding-workflow.md).

Companion to:
- [07-end-to-end-leaver-demo.md](07-end-to-end-leaver-demo.md) — manual `leaver_workflow.py`
- [05-slack-scim-lifecycle.md](05-slack-scim-lifecycle.md) — SCIM deprovision evidence

## Topology

```
EventBridge Scheduler (us-west-1)
  cron(0 17 * * ? *) + America/Los_Angeles
  → ohmgym-offboarding-workflow Lambda
      → Okta search: (ACTIVE|PROVISIONED) + profile.endDate == today_PT
      → per user: DELETE sessions → POST lifecycle/deactivate
      → DynamoDB ohmgym-offboarding-logs
      → Slack #leaver-it-ops batch summary
      → CloudWatch alarm → SNS email on Errors >= 1
```

## Repo layout

| Path | Role |
|---|---|
| [`lambdas/offboarding_workflow/`](../lambdas/offboarding_workflow/) | Lambda handler + tests |
| [`terraform/aws-offboarding/`](../terraform/aws-offboarding/) | us-west-1 stack |
| [`scripts/offboarding/`](../scripts/offboarding/) | CLI helpers (see README there) |
| [`config/okta/desired-state.json`](../config/okta/desired-state.json) | `profile.endDate` attribute |

## Okta search

```
search=(status eq "ACTIVE" or status eq "PROVISIONED") and profile.endDate eq "<today_pt>"
```

## Phased demo (Alex Novak + Jordan Kim)

### Phase 1 — Manual offboard (completed 2026-05-27)

```bash
# Schema + endDate (operator; once per tenant)
python scripts/okta/reconcile_config.py --apply   # needs okta.schemas.manage

python scripts/offboarding/set_end_date.py --name "Alex Novak"
python scripts/offboarding/set_end_date.py --name "Jordan Kim"
python scripts/offboarding/invoke_offboarding_workflow.py
```

**Result:** `deactivated_count: 2`, DynamoDB rows in `ohmgym-offboarding-logs`, Slack batch in `#leaver-it-ops` (channel `C0B1KV5CS4Q`).

### Phase 2 — Re-onboard (completed 2026-05-27)

```bash
python scripts/offboarding/restage_for_onboarding.py --name "Alex Novak" --name "Jordan Kim"
python scripts/onboarding/invoke_onboarding_workflow.py --tail-logs
```

**Result:** `activated_count: 2`, `#joiner-it-ops` batch summary. Onboarding Lambda search includes `DEPROVISIONED` (in addition to `STAGED`) so leaver round-trips work after `restage_for_onboarding.py`.

### Phase 3 — Scheduled offboard

Set `profile.endDate` to a future PT date; wait for 5:00 PM scheduler (do not manual invoke).

## DynamoDB audit schema

Same keys as onboarding: `run_date` (PK), `user_id` (SK). The `start_date` attribute stores `profile.endDate` at deactivation time for schema parity.

## Links

- [`scripts/offboarding/README.md`](../scripts/offboarding/README.md)
- [`.github/workflows/offboarding-workflow-ci.yml`](../.github/workflows/offboarding-workflow-ci.yml)
