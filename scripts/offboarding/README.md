# scripts/offboarding/ — CLI helpers for the ohmgym-offboarding-workflow

Local-laptop tooling for the AWS → Okta → Slack scheduled offboarding workflow. The Lambda runs autonomously in us-west-1 (triggered by EventBridge Scheduler at 5:00 PM PT daily). These scripts exist for development, demos, and operator remediation.

| Script | Purpose | When to use |
|---|---|---|
| `set_end_date.py` | Set `profile.endDate` on user(s) by login, user id, or full name | Before manual invoke or scheduler run |
| `seed_active_user.py` | Thin wrapper around `set_end_date.py` for smoke-test prep | Same as `set_end_date.py` (naming parity with onboarding `seed_staged_user.py`) |
| `invoke_offboarding_workflow.py` | Manually invoke the Lambda + optionally tail CloudWatch logs | Phase 1 demo, development, investigations |
| `replay_batch_deactivation.py` | Re-run the batch for any past date via `event.override_date` | Operator remediation when a 5 PM run failed |
| `restage_for_onboarding.py` | Reactivate DEPROVISIONED users for Phase 2 onboarding retest | After Phase 1 offboard, before `invoke_onboarding_workflow.py` |

## Parity with `scripts/onboarding/`

| Onboarding (`scripts/onboarding/`) | Offboarding (`scripts/offboarding/`) |
|---|---|
| `seed_staged_user.py` — create STAGED user + `startDate` | `set_end_date.py` / `seed_active_user.py` — set `endDate` on existing ACTIVE user |
| `invoke_onboarding_workflow.py` | `invoke_offboarding_workflow.py` |
| `replay_batch_activation.py` | `replay_batch_deactivation.py` |

## Phased demo — Alex Novak and Jordan Kim

After `profile.endDate` is in the tenant (`reconcile_config.py --apply`):

```bash
# 1) Tag both leavers for today's batch (America/Los_Angeles).
python scripts/offboarding/set_end_date.py --name "Alex Novak" --end-date 2026-05-27
python scripts/offboarding/set_end_date.py --name "Jordan Kim" --end-date 2026-05-27

# 2) Manual invoke (Phase 1 — do not wait for 5 PM scheduler).
python scripts/offboarding/invoke_offboarding_workflow.py --tail-logs
```

Expected: `deactivated_count: 2`, DynamoDB rows in `ohmgym-offboarding-logs`, batch post in `#leaver-it-ops`, Slack SCIM `user_deactivated` for both logins.

**Phase 2 (reset):** re-stage and run `scripts/onboarding/invoke_onboarding_workflow.py`.

**Phase 3:** set `endDate` to a future day and let the scheduler fire at 5:00 PM PT.

## Operator remediation — missed batch

```bash
python scripts/offboarding/replay_batch_deactivation.py --date 2026-05-26
```

The DynamoDB idempotency guard on `(run_date, user_id)` makes replays safe — users already deactivated for that date are skipped.

## Idempotency contract

| Scenario | Behavior |
|---|---|
| First run of the day | Deactivates every ACTIVE/PROVISIONED user with `profile.endDate == today_PT`, writes audit row, posts summary |
| Re-run same day, same users | Deactivate skipped (Okta search returns 0 matches). Skipped rows in summary |
| Replay a past date | DynamoDB guard skips success rows; only users still ACTIVE with that `endDate` are processed |

## Environment

All scripts honor the project `.env` for Okta credentials (Private Key JWT) and AWS SDK / `~/.aws/credentials` for Lambda invoke. Requires `profile.endDate` on the Okta user schema before `set_end_date.py` can write values.

## Companion docs

- [`public-docs/11-aws-scheduled-offboarding-workflow.md`](../../public-docs/11-aws-scheduled-offboarding-workflow.md) — architecture + runbook (when present)
- [`public-docs/10-aws-scheduled-onboarding-workflow.md`](../../public-docs/10-aws-scheduled-onboarding-workflow.md) — mirror pattern for joiners
- [`public-docs/07-end-to-end-leaver-demo.md`](../../public-docs/07-end-to-end-leaver-demo.md) — manual `leaver_workflow.py` (CLI, not scheduled)
- [`lambdas/offboarding_workflow/handler.py`](../../lambdas/offboarding_workflow/handler.py) — Lambda handler
- [`terraform/aws-offboarding/`](../../terraform/aws-offboarding/) — us-west-1 stack
