# Ohmgym Onboarding Workflow — Scheduled AWS → Okta → Slack Activation

The **proactive** half of the JML pipeline. Every morning at 9:00 AM America/Los_Angeles, an AWS-native scheduled job queries Okta for users whose `status == STAGED` and `profile.startDate == today_PT`, activates each one with `sendEmail=true`, writes a full identity-snapshot audit row to DynamoDB, and posts one Block Kit batch summary to `#joiner-it-ops`. The existing `novatech-okta-hook` Lambda from [doc 08](08-okta-event-hook-lambda.md) is the **reactive** half — it fires per-user when each hire clicks their activation link later in the day.

Companion to:
- [04-okta-migration.md](04-okta-migration.md) — Okta IdP foundation
- [06-end-to-end-joiner-demo.md](06-end-to-end-joiner-demo.md) — `joiner_workflow.py --use-activation-email` (manual one-off path)
- [08-okta-event-hook-lambda.md](08-okta-event-hook-lambda.md) — Okta event hook → Lambda → Slack (the reactive half this complements)

This adds **a second Terraform-managed AWS stack** in `terraform/aws-onboarding/`, deployed in **us-west-1** for regional isolation from the existing us-east-1 reactive stack. Four Secrets Manager entries are replicated cross-region via native `replica` blocks so the new Lambda reads local-region ARNs with zero application-code change.

## Purpose

Doc 08 closed the "did the hire click the link?" audit gap. This doc closes the gap on the OTHER side of activation: **when do new hires actually get the activation email in the first place?**

Today, a human runs `joiner_workflow.py --use-activation-email` per new hire. That's fine when HR onboards one person at a time. The realistic production pattern is HR pre-stages a cohort of hires weeks in advance (Q3 starts, intern class, M&A integration), each with a future `startDate`. None of them should get activation emails until their first day. Three architectural options for the trigger:

1. **Poll Okta from a long-running watcher process.** Couples scheduling to a host that has to stay up; breaks if the laptop closes.
2. **Okta Workflows scheduled flow.** Production-grade for shops that live in the Okta console, but introduces a SaaS dependency and isn't config-as-code. Explicitly out of scope for this repo.
3. **EventBridge Scheduler → AWS Lambda → Okta + Slack** ← chose this. Native AWS primitives, deployed-as-code via Terraform, observable in CloudWatch, scoped IAM, secrets in Secrets Manager. Mirrors the doc-08 architecture in the inverse direction (AWS-initiated, Okta-targeted, vs Okta-initiated, AWS-targeted).

## Topology

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                                                                                  │
│  EventBridge Scheduler  (us-west-1)                                              │
│    name:     ohmgym-onboarding-workflow                                          │
│    cron:     cron(0 9 * * ? *)                                                   │
│    tz:       America/Los_Angeles                                                 │
│    target:   aws_lambda_function.onboarding_workflow                             │
│       │                                                                          │
│       │  9:00 AM PT every day                                                    │
│       ▼                                                                          │
│  AWS Lambda  ohmgym-onboarding-workflow  (Python 3.12, 512 MB, 60s)              │
│       │                                                                          │
│       ├─► Secrets Manager (us-west-1 replicas) × 4 — at cold start               │
│       │     slack-bot-token, okta-api-client-id,                                 │
│       │     okta-api-key-id, okta-api-private-key                                │
│       │                                                                          │
│       ├─► today_pt = datetime.now(ZoneInfo("America/Los_Angeles")).date()        │
│       │     (override via event["override_date"] for the replay CLI)             │
│       │                                                                          │
│       ├─► GET https://<okta>/api/v1/users                                        │
│       │     ?search=status eq "STAGED" and profile.startDate eq "<today_pt>"     │
│       │     &limit=200                                                           │
│       │                                                                          │
│       ├─► for each matched user:                                                 │
│       │     DynamoDB GetItem (run_date, user_id) → skip if status=success        │
│       │     POST /api/v1/users/{id}/lifecycle/activate?sendEmail=true            │
│       │     DynamoDB PutItem with full identity snapshot                         │
│       │       (login, first_name, last_name, department, role_title,             │
│       │        start_date, status, okta_response_status, error_message,          │
│       │        timestamp_utc, batch_run_id, ttl_epoch=now+90d)                   │
│       │     time.sleep(0.2)  # Okta rate-limit pacing                            │
│       │                                                                          │
│       ├─► Slack chat.postMessage → #joiner-it-ops                                │
│       │     🚀 Daily joiner activations — <run_date>                             │
│       │     • First Last — role, department (login) [per activated user]        │
│       │     • Errors / Skipped sections (conditional)                            │
│       │     • Context footer with batch_run_id                                   │
│       │                                                                          │
│       └─► CloudWatch Logs: /aws/lambda/ohmgym-onboarding-workflow                │
│             └─► structured JSON line for each user + final summary line          │
│                                                                                  │
│  CloudWatch Alarm                                                                │
│    metric: AWS/Lambda Errors, period 5m, threshold ≥ 1                           │
│    action: SNS topic → email                                                     │
│                                                                                  │
│  ─── unchanged ───                                                               │
│  Existing novatech-okta-hook (us-east-1) continues handling per-user             │
│  activation Slack posts later in the day as each hire clicks their link.         │
│                                                                                  │
└────────────────────────────────────────────────────────────────────────────────┘
```

Two Lambdas, two regions, one channel. Doc-08's per-user post and this Lambda's batch summary are distinguishable Block Kit shapes so a Slack reader can tell them apart at a glance.

## What's in `terraform/aws-onboarding/`

```
terraform/aws-onboarding/
├── .gitignore               # state, *.tfvars (real values), build artifacts
├── providers.tf             # aws ~> 5.70; region = us-west-1; default tags
├── variables.tf             # 18 inputs (4 sensitive: secret ARNs + alarm email)
├── dynamodb.tf              # ohmgym-onboarding-logs table
├── iam.tf                   # Lambda exec role + 3 scoped policies + scheduler role + invoke policy
├── lambda.tf                # log group + function + scheduler-invoke permission
├── scheduler.tf             # aws_scheduler_schedule.daily (9am PT cron)
├── alarms.tf                # SNS topic + email sub + CW metric alarm
├── outputs.tf               # 7 outputs (function name/arn, log group, table, scheduler arn, sns arn, role arn)
├── terraform.tfvars         # GITIGNORED — real values
└── terraform.tfvars.example # committed template
```

**13 new AWS resources** in us-west-1 + **4 replica modifications** to `terraform/aws/secrets.tf` (us-east-1). The replica modifications were a one-line `replica { region = "us-west-1" }` block per secret — beats cross-region GetSecretValue calls (latency + regional dependency) and beats duplicate native secrets (rotation drift).

## Decisions worth calling out

### Why us-west-1 and not us-east-1

The existing reactive stack lives in us-east-1. Putting the new proactive stack in us-west-1 gives **regional isolation**: separate Terraform state, separate IAM surface, a misapplied plan on this stack can't touch the production-shaped doc-08 work. The cost is ~$1.60/month in replicated-secret overhead ($0.40 × 4 secrets). Worth it for the blast-radius reduction.

### Why EventBridge Scheduler and not the legacy CloudWatch Events rule

`aws_scheduler_schedule` (the modern EventBridge Scheduler primitive, GA Nov 2022) supports the `schedule_expression_timezone` field. The legacy `aws_cloudwatch_event_rule` only accepts UTC cron expressions, which means manual DST math twice a year. With the timezone field, `cron(0 9 * * ? *)` + `America/Los_Angeles` does the right thing on both DST sides for free.

### Why a server-side `search` filter and not client-side filtering

Okta supports two query patterns on users:
- `/api/v1/users?filter=...` — limited to a small allowlist of system fields (status, lastUpdated, etc.). Cannot filter on custom profile attributes.
- `/api/v1/users?search=...` — full SCIM filter syntax over the whole profile.

`profile.startDate` is a custom attribute (defined in `config/okta/desired-state.json`), so `search` is the only option. The exact query:

```
search=status eq "STAGED" and profile.startDate eq "<today_pt>"
```

One API call returns exactly the users to activate. The alternative — listing all STAGED users and client-side filtering by `profile.startDate` — would scale poorly as the STAGED cohort grows past a quarter's worth of pre-stages.

The same `search` pattern is already used by `scripts/okta/provision_users.py:70` for login dedup, so this isn't novel — it's the established pattern in the repo.

### Why STRICT same-day match (`eq today_pt`) and not `<= today`

A `<=` filter would self-heal missed runs (Monday's hires get picked up by Tuesday's batch). But it muddies the audit story: "was Sandra activated on her start date or two days later?" becomes ambiguous without inspecting the DynamoDB row. With strict same-day, the contract is unambiguous: each batch activates exactly that day's cohort.

The remediation path is explicit: `scripts/onboarding/replay_batch_activation.py --date 2026-05-13` re-runs any past date. The DynamoDB idempotency guard makes replays safe. The CloudWatch alarm catches missed runs so operator attention is drawn at the right moment.

### Why DynamoDB and not a flat log file or just CloudWatch

Three jobs that DynamoDB handles cleanly:

1. **Idempotency guard.** Before activating, `GetItem(run_date, user_id)` — if a success row exists for today, skip. Prevents double-activation if the scheduler retries or the replay CLI is rerun within minutes.
2. **Audit trail.** Each row captures the full identity snapshot at the moment of activation (login, first_name, last_name, department, role_title, start_date). This makes "who got activated last month" a single Query without back-references to Okta, and it survives downstream user renames / department moves.
3. **TTL cost hygiene.** `ttl_epoch = now + 90d` and AWS sweeps old rows within ~48h after expiry. Sandbox cost stays trivial.

Schema:

| Attribute | Type | Notes |
|---|---|---|
| `run_date` | String (PK) | YYYY-MM-DD in America/Los_Angeles. Colocates a single day's batch for one Query |
| `user_id` | String (SK) | Okta user id. Enforces per-(date, user) idempotency |
| `login` | String | profile.login |
| `first_name`, `last_name` | String | profile.firstName, profile.lastName |
| `department`, `role_title` | String | profile.department, profile.role_title |
| `start_date` | String | profile.startDate (ISO date) |
| `status` | String | `success` | `error` |
| `okta_response_status` | Number | HTTP status from the activate POST |
| `error_message` | String | Okta `errorSummary` when status=error |
| `timestamp_utc` | String | ISO 8601 UTC of the attempt |
| `batch_run_id` | String | UUID for the invocation, correlates to CloudWatch log lines |
| `ttl_epoch` | Number | Unix seconds; AWS auto-purges after this |

Billing is `PAY_PER_REQUEST` — for a table that sees < 30 writes/day, on-demand is dramatically cheaper than provisioned.

### Why module-level secret fetching duplicates across both Lambdas

The existing `lambdas/okta_activation_handler/handler.py` and this new `lambdas/onboarding_workflow/handler.py` share ~70 lines of JWT exchange + secret cache + Slack post helpers. A Lambda Layer would deduplicate but adds operational fragility (Layer versioning, region pinning, separate Terraform resource). The duplicated code is small, stable (the JWT protocol won't change), and the two Lambdas have divergent futures (the reactive one verifies inbound signatures; this one writes DynamoDB). Both files carry `# DUPLICATED IN:` comments so future drift is loud.

Revisit if a third Lambda joins.

### Why the alarm fires on `Errors >= 1` and not a higher threshold

A once-per-day automation has no statistical headroom — one error per day IS the population. The alternative (errors > N in M periods) effectively disables alerting for the idempotency-critical batch. Acceptable downside: noisy emails if Okta is transiently flaky.

## Tests

`lambdas/onboarding_workflow/tests/` ships with 11 pytest cases covering:

- search URL builds today_pt correctly (with `freezegun`)
- `event.override_date` precedence
- per-user activate POST (with `sendEmail=true`)
- DynamoDB idempotency guard skips already-success rows
- record attributes capture the full identity snapshot
- error path (Okta 5xx → status=error row + errorSummary)
- Slack Block Kit shape (header + activated list + context footer)
- zero-staged-today no-op
- JWT token caching across users (one token call per batch)
- partial-failure summary return shape
- Okta search HTTP failure raises so the alarm fires

All AWS calls go through `moto` (in-memory mocks). Okta + Slack HTTP calls go through `requests_mock`. No live network. The full suite runs in ~1 second.

```bash
$ pytest lambdas/onboarding_workflow/tests -v
============================== 11 passed in 1.05s ==============================
```

## CI/CD

`.github/workflows/onboarding-workflow-ci.yml` runs on every push to `feature/ohmgym-onboarding-workflow` and every PR back to `main`. Four parallel jobs:

| Job | What it gates |
|---|---|
| `python-tests` | `pytest lambdas/onboarding_workflow/tests` (11 cases) |
| `build-zip` | `bash build.sh` produces `build/handler.zip` |
| `terraform-validate` (matrix: `terraform/aws` + `terraform/aws-onboarding`) | `fmt -check`, `init -backend=false`, `validate` |
| `python-syntax` | `py_compile` on handler + 3 CLI helpers + notify.py |

**Apply stays operator-gated.** CI never runs `terraform apply` and never runs `aws lambda invoke`. The line is explicit: CI catches regressions and lint issues; humans run the deploys.

## Demo loop

After `terraform apply` on both stacks:

```bash
# 1) Seed a STAGED user with today's startDate.
python scripts/onboarding/seed_staged_user.py \
    --first-name Priya --last-name Patel \
    --email chris+priya@ohmgym.com \
    --department Data --role-title "Data Engineer"

# 2) Trigger the Lambda manually (instead of waiting until 9 AM tomorrow).
python scripts/onboarding/invoke_onboarding_workflow.py --tail-logs
```

Expected output (illustrative):

```
Invoking ohmgym-onboarding-workflow in us-west-1 with payload: {}
{
  "status_code": 200,
  "function_error": null,
  "response": {
    "event": "onboarding_batch_complete",
    "run_date": "2026-05-14",
    "batch_run_id": "8a3f...",
    "activated_count": 1,
    "error_count": 0,
    "skipped_count": 0,
    "activated": [{"user_id": "00uA1B2C3", "login": "chris+priya@ohmgym.com", ...}],
    "slack": {"posted": true, "channel": "C0B0N91FHN1", "ts": "1777..."}
  }
}
--- Tailing /aws/lambda/ohmgym-onboarding-workflow for 60s ---
[16:00:01] {"event": "onboarding_batch_complete", "run_date": "2026-05-14", ...}
```

Five things provable from that output:
1. **Lambda authenticated to Okta** (otherwise the search call would fail before activate)
2. **Okta search matched the user** (otherwise activated_count would be 0)
3. **Activate POST succeeded** (otherwise status=error in the audit row)
4. **DynamoDB row written** (otherwise re-running would fire activate again)
5. **Slack post landed** (otherwise `slack.posted` would be false)

Click the activation email in `chris@ohmgym.com` (Gmail `+` aliasing routes `chris+priya@` here) → the existing `novatech-okta-hook` reactive Lambda fires a per-user `✅ activated Okta` post a few seconds later. That's the JML pipeline working end-to-end across both Lambdas.

## Idempotency contract

| Scenario | Behavior |
|---|---|
| First run of the day | Activates every STAGED user with `profile.startDate == today_PT`, writes audit row, posts summary |
| Re-run same day, same users | Activate POSTs are skipped (Okta filter returns 0 STAGED users — they're now PROVISIONED). Empty summary posted |
| Re-run same day with a NEW STAGED user added | Only the new user is activated. Audit row written. Summary lists 1 activation |
| Replay yesterday's date via the CLI | DynamoDB guard skips success rows; only users still STAGED somehow get re-activated |

## Caveats and explicit non-goals

- **No `terraform apply` in CI.** Plan-only is the line. Phase 8 will tackle CI/CD for IaC.
- **No `aws lambda invoke` in CI.** Production invocations are operator-only.
- **No Step Functions / SQS.** Single Lambda is sufficient at sandbox scale (≤10 hires/day). Migrate to SFN with a Map state if a batch ever exceeds ~200 users / Okta rate limits start biting.
- **No catch-up window (`startDate <= today`).** Strict same-day match by design; the replay CLI is the explicit remediation path.
- **No multi-region failover.** Sandbox.
- **No remote Terraform state.** Local state file matches the existing `terraform/aws/` pattern. Phase 7 moves both roots to S3 + DynamoDB together.
- **One Slack workspace.** The bot is approved for `T0AUHDULU9Z` only; multi-workspace fan-out would need different identity scoping in the Block Kit helper.

## Outcomes

### What's proven (after operator runs apply + smoke test)

- **AWS-native scheduled lifecycle automation** against the Okta Management API
- **Cross-region Secrets Manager replication** for blast-radius isolation between two AWS stacks
- **Server-side Okta `search` filter** on custom profile attributes (the only correct way to filter by `startDate`)
- **DynamoDB-backed idempotency + audit trail** with TTL-driven cost hygiene
- **CloudWatch alarm + SNS email** on Lambda errors for a daily automation
- **CI-gated regression coverage** (11 pytest cases, terraform validate, build verification)
- **Cross-platform automation** — three SaaS tenants (Okta, AWS, Slack) coordinating from one cron trigger

### Why this is interview-shippable

The JD calls out: *"Develop, test, deploy API integrations,"* *"Reducing operational overhead, eliminating manual tasks,"* *"Identity and access concepts (RBAC, SCIM, SAML, OAuth),"* and *"Catching drift / config-as-code."* This single feature exercises:

- **Scheduled automation** — EventBridge Scheduler with proper timezone handling
- **API integration** — Okta Management API (Private Key JWT, custom-attribute search, lifecycle endpoint)
- **Infrastructure-as-code** — second Terraform root, cross-region replication, scoped IAM
- **Cloud functions + secrets** — Lambda runtime, cross-region Secrets Manager replicas, scoped policies
- **Audit-trail design** — DynamoDB schema doubling as idempotency guard
- **Test-first** — 11 pytest cases with moto + requests_mock, all green in CI
- **CI/CD discipline** — apply stays operator-gated; tests + plan run autonomously

The screen-share moment: open three terminals, run `seed_staged_user.py` in one, `invoke_onboarding_workflow.py --tail-logs` in the second, and have `aws dynamodb scan --table-name ohmgym-onboarding-logs --region us-west-1` ready in the third. Watch the CloudWatch log line, the DynamoDB row, and the Slack post arrive within ~3 seconds of the invoke. Then click the activation email and watch the *reactive* Lambda's `✅` post arrive in `#joiner-it-ops` a few seconds later. Two Lambdas, two regions, one channel, one feature, end-to-end demoable in 4 minutes.

## Links

- [`lambdas/onboarding_workflow/handler.py`](../lambdas/onboarding_workflow/handler.py) — the Lambda
- [`lambdas/onboarding_workflow/tests/test_handler.py`](../lambdas/onboarding_workflow/tests/test_handler.py) — 11 pytest cases
- [`terraform/aws-onboarding/`](../terraform/aws-onboarding/) — the us-west-1 stack
- [`terraform/aws/secrets.tf`](../terraform/aws/secrets.tf) — replica blocks added for the cross-region secrets
- [`scripts/onboarding/`](../scripts/onboarding/) — seed, invoke, replay CLI helpers
- [`scripts/slack/notify.py`](../scripts/slack/notify.py) — `post_joiner_batch_summary` helper
- [`.github/workflows/onboarding-workflow-ci.yml`](../.github/workflows/onboarding-workflow-ci.yml) — CI
- [`public-docs/08-okta-event-hook-lambda.md`](08-okta-event-hook-lambda.md) — the reactive companion
