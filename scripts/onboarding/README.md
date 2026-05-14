# scripts/onboarding/ — CLI helpers for the ohmgym-onboarding-workflow

Local-laptop tooling for the AWS → Okta → Slack scheduled onboarding workflow. The Lambda itself runs autonomously in us-west-1 (triggered by EventBridge Scheduler at 9:00 AM PT daily). These scripts exist for development, demos, and operator remediation.

| Script | Purpose | When to use |
|---|---|---|
| `seed_staged_user.py` | Provision a STAGED Okta user with a chosen `startDate` | Setting up an end-to-end smoke test |
| `invoke_onboarding_workflow.py` | Manually invoke the Lambda + optionally tail CloudWatch logs | Development, demo, or "did it run?" investigations |
| `replay_batch_activation.py` | Re-run the batch for any past date via `event.override_date` | Operator remediation when a 9 AM run failed |

## Smoke test — full demo loop

The three scripts are designed to chain. After both Terraform stacks are applied:

```bash
# 1) Seed a STAGED user with today's startDate.
python scripts/onboarding/seed_staged_user.py \
    --first-name Priya --last-name Patel \
    --email chris+priya@ohmgym.com \
    --department Data --role-title "Data Engineer"

# 2) Trigger the Lambda manually (instead of waiting until 9 AM tomorrow).
python scripts/onboarding/invoke_onboarding_workflow.py --tail-logs
```

You should see, in order:
- The Lambda log line `{"event": "onboarding_batch_complete", "activated_count": 1, ...}`
- A new row in DynamoDB `ohmgym-onboarding-logs` with the full identity snapshot
- A 🚀 Block Kit post in Slack `#joiner-it-ops` listing Priya
- The Okta activation email in `chris@ohmgym.com` (Gmail `+` aliasing routes `chris+priya@` here)
- Priya's status flip from STAGED to PROVISIONED in Okta

Click the activation link in the email → the **existing** `novatech-okta-hook` reactive Lambda (us-east-1) fires the per-user `✅ activated Okta` Slack post a few seconds later. That's the JML pipeline working end-to-end across both Lambdas.

## Operator remediation — missed batch

If the scheduled 9 AM run fails for some date (Lambda error, AWS outage, Okta unreachable, etc.) the CloudWatch alarm sends an email to the configured `alarm_email`. Recovery is one command:

```bash
python scripts/onboarding/replay_batch_activation.py --date 2026-05-13
```

The DynamoDB idempotency guard on `(run_date, user_id)` makes replays safe — already-activated users in that date's batch are skipped silently. If the replay also fails, the alarm will fire again; check the CloudWatch logs for the structured error line.

## Idempotency contract

| Scenario | Behavior |
|---|---|
| First run of the day | Activates every STAGED user with `profile.startDate == today_PT`, writes audit row, posts summary |
| Re-run same day, same users | Activate POSTs are skipped (Okta filter returns 0 STAGED users — they're now PROVISIONED). Empty summary posted |
| Re-run same day with a NEW STAGED user added | Only the new user is activated. Audit row written. Summary lists 1 activation |
| Replay yesterday's date | Idempotency guard on DynamoDB skips success rows; only users whose status is somehow still STAGED get re-activated |

## Environment

All three scripts honor the project `.env` for Okta credentials (Private Key JWT against the API Services app) and standard AWS SDK env vars / `~/.aws/credentials` for the Lambda invoke. No additional configuration needed if `scripts/okta/*.py` already works.

## Companion docs

- [`public-docs/10-aws-scheduled-onboarding-workflow.md`](../../public-docs/10-aws-scheduled-onboarding-workflow.md) — end-to-end runbook + architecture
- [`public-docs/08-okta-event-hook-lambda.md`](../../public-docs/08-okta-event-hook-lambda.md) — the reactive companion Lambda
- [`lambdas/onboarding_workflow/handler.py`](../../lambdas/onboarding_workflow/handler.py) — what the Lambda actually does
- [`terraform/aws-onboarding/`](../../terraform/aws-onboarding/) — the us-west-1 stack
