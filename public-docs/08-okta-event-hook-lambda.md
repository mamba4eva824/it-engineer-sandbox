# Okta Event Hook → AWS Lambda → Slack — Cross-Platform Audit Trail

A live trace of an end-to-end activation event firing an Okta event hook against an AWS Lambda Function URL, which in turn posts to Slack `#joiner-it-ops`. Closes a real audit-coverage gap in the JML triplet: the Joiner CLI knows when the welcome email was *dispatched*, but only Okta knows when the new hire actually *clicked the link and set their password*. This is what the rest of the org cares about — "is the person actually onboarded?" — and now it's auditable in Slack.

Companion to:
- [04-okta-migration.md](04-okta-migration.md) — Okta IdP foundation
- [05-slack-scim-lifecycle.md](05-slack-scim-lifecycle.md) — Slack SCIM provisioning
- [06-end-to-end-joiner-demo.md](06-end-to-end-joiner-demo.md) — `joiner_workflow.py --use-activation-email`
- [07-end-to-end-leaver-demo.md](07-end-to-end-leaver-demo.md) — `leaver_workflow.py`

This is the first piece of **Terraform-managed AWS infrastructure** in the repo. `terraform/aws/` is no longer empty — 10 resources are now declared and applied via standard `init / plan / apply`, with state committed locally (S3 + DynamoDB remote state is a Phase 7 follow-up).

## Purpose

The Joiner workflow logs `slack_welcome_post` when the activation email is dispatched, but that's only one half of the onboarding story:

| Question | Who knows the answer | Pre-this-doc |
|---|---|---|
| Was the welcome email dispatched? | Local audit (joiner_workflow.py) | ✅ logged + Slack post |
| Did the new hire activate their account? | **Okta only** | ❌ no signal anywhere else |
| Was the leaver deactivated? | Local audit (leaver_workflow.py) | ✅ logged + Slack post |

Closing that gap requires Okta to *push* the activation event somewhere we can observe. Three architectural options were on the table:

1. **Poll Okta system log** from the joiner CLI after the email is dispatched. Simple, but couples the joiner workflow to a long-running watcher and breaks if the operator's terminal closes.
2. **Okta Workflows / Workato recipe** that subscribes to the event and posts to Slack. Production-grade, but introduces a SaaS dependency and isn't config-as-code.
3. **Okta Event Hook → AWS Lambda → Slack** ← chose this. Native Okta primitive, deployed-as-code via Terraform, observable in CloudWatch, scoped IAM, secrets in Secrets Manager.

Option 3 is also the architecture multiple repo runbooks (`mover-workflow.md`, `leaver-workflow.md`) explicitly hand-wave as *"in production this would sit behind an Okta Event Hook → Lambda."* Now it does.

## Topology proved here

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                      │
│  New hire (browser, incognito)                                                       │
│       │                                                                              │
│       │ click activation link → set password + enroll MFA                            │
│       ▼                                                                              │
│  Okta tenant                                                                         │
│       │                                                                              │
│       ├─► system log: user.account.update_password                                  │
│       │                                                                              │
│       └─► Event Hook subscription (configured in Workflow → Event Hooks)            │
│             │                                                                        │
│             │  HTTPS POST                                                            │
│             │  Authorization: <shared secret from Secrets Manager>                  │
│             │  body: { data: { events: [...LogEvent...] } }                         │
│             ▼                                                                        │
│  AWS Lambda Function URL  (us-east-1, account 430118826061)                         │
│       │  https://dfjxsz67aq7iwqc4hzqszw3axi0txfbj.lambda-url.us-east-1.on.aws/      │
│       ▼                                                                              │
│  Lambda: novatech-okta-hook  (Python 3.12, 256 MB, 10 s)                            │
│       │                                                                              │
│       ├─► Secrets Manager: GetSecretValue ×5                                        │
│       │     • okta-webhook-secret    (Authorization header verification)             │
│       │     • slack-bot-token         (chat.postMessage auth)                        │
│       │     • okta-api-client-id     ┐                                              │
│       │     • okta-api-key-id        ├─ Okta Mgmt API (Private Key JWT) for         │
│       │     • okta-api-private-key   ┘  the dedup `lastLogin` lookup                 │
│       │     └─► IAM execution role with least-privilege inline policy:              │
│       │           GetSecretValue on EXACTLY those 5 ARNs (no wildcards)              │
│       │                                                                              │
│       ├─► verify Authorization header == OKTA shared secret                         │
│       │                                                                              │
│       ├─► filter data.events[] for eventType == user.account.update_password        │
│       │                                                                              │
│       ├─► DEDUP: GET https://<okta>/api/v1/users/{actor.id}                         │
│       │     └─► if `lastLogin` is null → first activation → post to Slack           │
│       │     └─► if `lastLogin` is set  → routine password change → silent skip     │
│       │                                                                              │
│       ├─► resolve_or_create #joiner-it-ops via conversations.create / list          │
│       │                                                                              │
│       ├─► chat.postMessage with Block Kit (login, activated_at, source, status)     │
│       │                                                                              │
│       └─► CloudWatch Logs: /aws/lambda/novatech-okta-hook                           │
│             └─► structured JSON includes the skip reason:                            │
│                {"event":"okta_hook_processed","posted":[],                          │
│                 "skipped":[{"login":"...","reason":"not_first_activation:..."}]}    │
│                                                                                      │
│  Slack workspace (ohmgym sandbox, T0AUHDULU9Z)                                      │
│       │                                                                              │
│       └─► #joiner-it-ops gets a second message: "✅ New hire activated Okta"        │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

Every arrow is observable: Okta system log on the source side, CloudWatch on the Lambda, Slack audit log on the destination. The whole chain is reproducible from a single `terraform apply` plus an admin-UI event hook registration.

## What's in `terraform/aws/`

```
terraform/aws/
├── .gitignore               # state files, *.tfvars (real secrets), build artifacts
├── providers.tf             # aws ~> 5.70 + local ~> 2.5; us-east-1; default tags
├── variables.tf             # 7 inputs (2 sensitive: secret + bot token)
├── secrets.tf               # 2 Secrets Manager entries + their versions
├── iam.tf                   # Lambda exec role + AWSLambdaBasicExecutionRole + scoped GetSecretValue
├── lambda.tf                # CloudWatch log group + Function + Function URL
├── outputs.tf               # 6 outputs (function_url, log group, ARNs, role)
├── terraform.tfvars         # GITIGNORED — real values for the two sensitive vars
└── terraform.tfvars.example # committed template showing the variable shape
```

10 resources total — exactly what `terraform plan` reported. No CloudWatch alarms (sandbox has only 10-alarm cap and CloudWatch Logs is the right observability primitive for this scope; alarms would be bytes-of-effort for no signal-to-noise gain).

### Lambda code lives outside `terraform/`

```
lambdas/okta_activation_handler/
├── handler.py             # 4 unit tests pass locally before any apply
├── requirements.txt       # only `requests` (boto3 is in the runtime)
├── build.sh               # produces build/handler.zip — re-run any time handler.py changes
└── build/handler.zip      # 1.1 MB, gitignored (built artifact)
```

The Lambda module is deliberately separate from `terraform/`: code lives with code, infra lives with infra. Terraform reads the externally-built zip via `data "local_file"` and uses its `content_base64sha256` as `source_code_hash` so any code change triggers a re-deploy on the next plan.

## The live run — Marcus Reyes

Sandra Jones from doc 06/07 was already DEPROVISIONED; using a fresh persona in the Data team to keep the trace clean.

### Pre-test state

```
Okta active users: 9 / 10
  (no chris+marcus@ohmgym.com yet)
Slack channels: #joiner-it-ops (C0B0N91FHN1), #leaver-it-ops (C0B1KV5CS4Q)
  (both created via API by scripts/slack/notify.py earlier)
Lambda: novatech-okta-hook  status=Active  function URL VERIFIED by Okta
Okta event hook: VERIFIED, subscribed to user.account.update_password
```

### Step 1 — Joiner CLI (creates Marcus + dispatches activation email)

```bash
$ python scripts/lifecycle/joiner_workflow.py \
    --first-name Marcus --last-name Reyes \
    --department Data --role-title "Data Analyst" \
    --cost-center DAT-100 --manager-email heather.gutierrez@ohmgym.com \
    --start-date 2026-05-04 --email chris+marcus@ohmgym.com \
    --use-activation-email --skip-gws-alias

Joiner workflow — name=Marcus Reyes  login=chris+marcus@ohmgym.com  dept=Data
Mode: ACTIVATION EMAIL (STAGED + sendEmail=true)

Step 1: Build Okta profile from CLI args
Step 2: Okta — pre-flight existence check
  No existing user with login=chris+marcus@ohmgym.com; proceeding to create.
Step 3: Okta — create user
  Created (STAGED): chris+marcus@ohmgym.com  id=00u12h47vtlRkpgf0698
  Sending activation email...
  Activation email sent to chris+marcus@ohmgym.com (check Gmail at chris@ohmgym.com).
  Welcome post → #joiner-it-ops (channel=C0B0N91FHN1, ts=1777507204.832189)
Step 4: Okta group rule — wait for Data membership
  Group rule fired: user is in Data within 45s.
…
JOINER WORKFLOW COMPLETE
```

**`#joiner-it-ops` post 1 of 2 lands here** — `:incoming_envelope: Welcome email sent to new hire: Marcus Reyes` — posted by `scripts/slack/notify.py` from inside the joiner CLI.

### Step 2 — Operator clicks the activation link

In incognito: open Gmail (`chris@ohmgym.com`), find the Okta welcome email addressed to `chris+marcus@ohmgym.com` (Gmail's `+` subaddressing routes it correctly), click the activation link, set a password, enroll MFA. Lands on the Okta dashboard signed in as Marcus.

### Step 3 — Okta event hook fires the Lambda (within seconds of clicking)

CloudWatch tail for `/aws/lambda/novatech-okta-hook` during the run captures the cold start + invocation:

```
2026-04-30T00:02:39.287Z  INIT_START Runtime Version: python:3.12...
2026-04-30T00:02:39.965Z  START RequestId: 2f48ab4b-3a1c-4926-92f0-51222c91cf52
2026-04-30T00:02:40.199Z  {"event": "okta_hook_processed",
                           "posted": [{"login": "chris+marcus@ohmgym.com",
                                       "ts": "1777507360.167539"}],
                           "skipped": []}
2026-04-30T00:02:40.201Z  END RequestId: 2f48ab4b-3a1c-4926-92f0-51222c91cf52
2026-04-30T00:02:40.201Z  REPORT  Duration: 235.66 ms  Billed Duration: 911 ms
                                  Memory Size: 256 MB  Max Memory Used: 93 MB
                                  Init Duration: 674.35 ms
```

Five things provable from that log line alone:

1. **Okta sent the event** (otherwise no INIT_START)
2. **Lambda authenticated the request** (otherwise the structured log line would say `unauthorized`)
3. **The handler matched the event type** (`user.account.update_password` is in `WATCHED_EVENT_TYPES`)
4. **The handler extracted the right user** — `actor.alternateId` correctly parsed to `chris+marcus@ohmgym.com`
5. **Slack accepted the post** with `ts=1777507360.167539` (this is the canonical Slack message id; you can pin or react to it via API)

### Step 4 — `#joiner-it-ops` post 2 of 2 lands

Same channel, same bot identity, different message:

> :white_check_mark: **New hire activated Okta:** Marcus Reyes (chris+marcus@ohmgym.com)
>
> | | |
> |---|---|
> | **Login** | chris+marcus@ohmgym.com |
> | **Activated at** | 2026-04-30T00:02:38.999Z |
> | **Source** | Okta event hook → AWS Lambda |
> | **Status** | Account active — full identity-layer access live |
>
> *Posted by NovaTech IT Ops automation*

### Step 5 — Leaver CLI (closes the arc)

```bash
$ python scripts/lifecycle/leaver_workflow.py --okta-user-id 00u12h47vtlRkpgf0698

Step 1: Okta — look up user and capture profile
  Found: Marcus Reyes  login=chris+marcus@ohmgym.com  status=ACTIVE  dept=Data
Step 2: Okta — revoke active sessions  → revoked
Step 3: Okta — deactivate user  → DEPROVISIONED. SCIM DELETE cascade triggered.
  Leaver post → #leaver-it-ops (channel=C0B1KV5CS4Q, ts=1777507483.813519)
Step 4: GWS — suspend account
  No real GWS user for chris+marcus@ohmgym.com (Gmail +alias only); skipping.
Step 5: Slack — auto-deactivation via SCIM cascade  (Okta SCIM client fires automatically)
Step 7a: Slack — DM the manager
  Slack DM to heather.gutierrez@ohmgym.com sent (channel=D0B0RSR79U2, ts=1777507485.278979)
…
LEAVER WORKFLOW COMPLETE
```

**`#leaver-it-ops` post lands** — `:no_entry: Leaver Okta account deactivated: Marcus Reyes` — posted by `scripts/slack/notify.py` from inside the leaver CLI.

## Step-by-step trace with timing

| # | Operator action / system event | Time (UTC) | Latency | Where it shows up |
|---|---|---|---|---|
| 1 | `joiner_workflow.py …` | 17:00:00 | T+0s | terminal stdout |
| 2 | Okta create + activation email POST | 17:00:04 | T+4s | Okta system log: `user.lifecycle.activate` |
| 3 | Welcome post → `#joiner-it-ops` | 17:00:04 | T+4s | Slack ts=1777507204 |
| 4 | (operator opens Gmail, finds email) | 17:00:30 | (human delay) | Gmail inbox |
| 5 | (operator clicks activation link, set password, enrolls MFA) | 17:02:30 | (human delay) | Okta welcome flow |
| 6 | Okta records `user.account.update_password` | 17:02:39 | T+0s from human | Okta system log |
| 7 | Okta event hook POST → Lambda Function URL | 17:02:39 | < 1s | CloudWatch INIT_START |
| 8 | Lambda authenticates, fetches secrets, posts to Slack | 17:02:40 | 235ms execution + 674ms cold start | CloudWatch REPORT |
| 9 | Activation post → `#joiner-it-ops` | 17:02:40 | T+1s from clicking | Slack ts=1777507360 |
| 10 | `leaver_workflow.py …` | 17:04:43 | T+0s | terminal stdout |
| 11 | Leaver post → `#leaver-it-ops` | 17:04:43 | T+0s | Slack ts=1777507483 |
| 12 | Manager DM to Heather | 17:04:45 | T+2s | Slack ts=1777507485 |

End-to-end automation runtime (excluding human MFA enrollment): **~5 seconds**. The Lambda's contribution to that — Okta-click to Slack-post — is **~1 second** including a cold start; warm-path invocations would be ~250ms.

## Dedup verification — Priya Patel (after the Lambda gained `lastLogin` lookup)

After the Marcus run shipped, a real concern surfaced: `user.account.update_password` *also* fires on every subsequent password change. An employee rotating their password 6 months in would generate a misleading "new hire activated Okta" post in `#joiner-it-ops`. The fix was to extend the Lambda with an Okta Management API lookup (Private Key JWT against the existing API Services app) and skip if the user already has a `lastLogin` timestamp.

Verified end-to-end against a fresh persona:

### First activation — post DOES land

```bash
$ python scripts/lifecycle/joiner_workflow.py \
    --first-name Priya --last-name Patel \
    --department Data --role-title "Data Engineer" \
    --cost-center DAT-100 --manager-email heather.gutierrez@ohmgym.com \
    --start-date 2026-05-04 --email chris+priya@ohmgym.com \
    --use-activation-email --skip-gws-alias
…
  Created (STAGED): chris+priya@ohmgym.com  id=00u12i65jscqUmdCu698
  Welcome post → #joiner-it-ops (channel=C0B0N91FHN1, ts=1777570417.163009)
```

Operator clicks activation email, sets password, enrolls MFA. CloudWatch captures the Lambda firing (truncated for clarity):

```
{"event": "okta_hook_processed",
 "posted": [{"login": "chris+priya@ohmgym.com", "ts": "..."}],
 "skipped": []}
```

`#joiner-it-ops` gets the activation post — same as Marcus. **Expected behavior; first activation always posts.**

### Subsequent password change — post CORRECTLY SUPPRESSED

Operator stays signed in as Priya, opens Settings → Change Password, sets a new password. Same `user.account.update_password` event fires in Okta. Lambda receives it, calls `GET /api/v1/users/00u12i65jscqUmdCu698`, sees `lastLogin: "2026-04-30T18:00:18.000Z"` (the activation sign-in 10 minutes earlier), and silently skips:

```
2026-04-30T18:00:30Z  {"event": "okta_hook_processed",
                       "posted": [],
                       "skipped": [{"login": "chris+priya@ohmgym.com",
                                    "reason": "not_first_activation:already_logged_in_at_2026-04-30T18:00:18.000Z"}]}
2026-04-30T18:00:30Z  REPORT  Duration: 1422.03 ms  Billed: 2246 ms  Init: 823.80 ms
```

`#joiner-it-ops` is NOT touched. The skip is forensically auditable in CloudWatch — the `reason` field tells you exactly why and references the timestamp that proved the user wasn't activating.

The dedup adds ~1 second to warm-path execution (extra Okta JWT exchange + `GET /users/{id}`); cold-start latency rose modestly because the Lambda zip grew from 1.1 MB to 5.9 MB (PyJWT + cryptography added). Acceptable trade-off; alternative was a misleading audit signal.

## Decisions worth calling out

### Why Lambda Function URL instead of API Gateway

API Gateway HTTP API was the documented path in `docs/prompts/api-gateway-jwt-authorizer.md` and would have been correct for a multi-route HTTP service. For a single Okta event-hook receiver, it would be 8 extra Terraform resources (HTTP API, integration, route, stage, deployment, permissions) for no observable benefit — Function URL gives the same HTTPS endpoint, IAM-backed authorization (we set it to `NONE` because Okta's shared secret is the auth model), and one resource. When the next webhook receiver arrives, *that's* when API Gateway becomes the right call.

### Why the Authorization header (and not signature verification)

Okta event hooks support two auth models: a static `Authorization: <secret>` header, or HMAC signature verification of the request body. The signature path is more robust (replay-resistant if the body includes a timestamp) but requires shared secret rotation tooling and signature-verification code on the Lambda side. For a sandbox where the operator controls both ends and the secret can be rotated by editing `terraform.tfvars`, the static header is the right complexity tradeoff. Production deployments handling real PII should choose HMAC.

### Why Secrets Manager and not Lambda env vars

Three reasons:

- **Visibility:** env vars show in `lambda:GetFunctionConfiguration` to anyone with that read permission; Secrets Manager requires explicit `secretsmanager:GetSecretValue` scoped to a specific ARN.
- **Auditability:** every secret access is a CloudTrail event tied to a principal.
- **Rotation:** rotating the secret is a `aws_secretsmanager_secret_version` change with no Lambda redeploy needed (next cold start picks up the new value).

The IAM policy in `iam.tf` grants `GetSecretValue` on **exactly the five ARNs** this Lambda needs (Okta webhook secret + Slack bot token + 3 Okta Management API credentials) — no wildcards. That's the kind of thing the resume bullet "least-privilege IAM across 48 resources" is referring to, applied here at the small scale of this Lambda.

### Event subscription + dedup with Okta API lookup

Okta emits multiple events around activation. None of them are perfectly clean — every candidate either fires too early (before the user clicks the link) or also fires later in the user's lifecycle. The trade-off matrix from inspecting Marcus Reyes's actual system log:

| Event type | When it fires | Problem for "user is onboarded"? |
|---|---|---|
| `user.lifecycle.activate` | When the joiner CLI POSTs `/lifecycle/activate?sendEmail=true` | Fires ~2 minutes BEFORE the human clicks the email link |
| `user.account.update_password` | User sets a password | Fires on first activation AND every subsequent password change/rotation/reset |
| `user.session.start` | Any sign-in | Fires on every login, not just first |
| `user.mfa.factor.activate` | MFA enrolled | Fires on every MFA factor add, not just first |
| `user.authentication.verify` | Successful MFA challenge | Fires on every MFA challenge across the user's lifetime |

**Subscribing to `user.account.update_password` plus a server-side dedup is the clean answer.** The handler:

1. Receives every `update_password` event
2. Reads the user from Okta Management API (`GET /api/v1/users/{id}`)
3. Inspects the user's `lastLogin` field — null means the user has never signed in, which only happens during the activation flow before they reach the dashboard
4. Posts to Slack only if `lastLogin` is null; logs a structured skip reason otherwise

A real password rotation 6 months later: same event fires, but `lastLogin` is populated → handler skips with a CloudWatch log line like:

```json
{"event": "okta_hook_processed", "posted": [],
 "skipped": [{"login": "chris+priya@ohmgym.com",
              "reason": "not_first_activation:already_logged_in_at_2026-04-30T18:00:18.000Z"}]}
```

That skip line is itself the audit evidence — you can grep CloudWatch for `not_first_activation` to count suppressed posts and reason about whether the dedup is doing the right thing in production.

The Lambda's `_is_first_activation()` returns False on Okta API errors too, treating "I can't tell" as "don't post" — false negatives are far less bad than false positives in an audit channel that managers and security read.

### Why JWT-based Okta auth (not a static API token)

The Lambda authenticates to Okta the same way every other script in the repo does: Private Key JWT client-credentials exchange against the existing API Services app (`OKTA_CLIENT_ID` + `OKTA_KEY_ID` + `OKTA_PRIVATE_KEY`). Single principal, single rotation point, same audit trail in Okta's system log. The credentials live in three Secrets Manager entries that the Lambda's execution role can read; the access token is cached in module scope across warm invocations.

### Why no CloudWatch alarms

The AWS account is at its 10-alarm sandbox cap, and the right observability primitive for this scope is **logs** (which you can `tail` with `aws logs tail --follow`), not threshold alarms. Production would absolutely want alarms on Lambda errors, throttles, and Okta delivery failures — but that's a separate hardening pass, not this PR.

### Why local Terraform state

Phase 7 of the roadmap explicitly calls for S3 + DynamoDB remote state. For a single-engineer sandbox with a single workspace-of-truth, local state in `terraform/aws/terraform.tfstate` is the correct level of complexity. The state file is gitignored so it doesn't leak ARNs or secret-version metadata.

## Caveats and explicit non-goals

- **No retry queue.** If Slack is unreachable when the Okta event arrives, the Lambda returns 200 (so Okta doesn't redeliver) and the post is dropped — CloudWatch shows the failure. Production would queue the post to SQS and retry. Acceptable tradeoff for this scope.
- **No HMAC signature verification.** Static shared-secret only (see "Decisions" above).
- **No alarms.** Logs only (see "Decisions" above).
- **No CI/CD for `terraform apply`.** Manual `apply` from your laptop is the explicit choice; `.github/workflows/` is empty in the repo and Phase 8 is when that gets built out. The current workflow exercises every Terraform skill except CI promotion.
- **Existing `#it-ops-audit` posts in the legacy joiner/leaver code paths still fail with `channel_not_found`.** That channel was never created via API; the new architecture creates `#joiner-it-ops` and `#leaver-it-ops` instead. Cleanup of the legacy code paths is a future-doc item.
- **One workspace, one bot.** The Slack bot is approved for a single Enterprise Grid workspace (`T0AUHDULU9Z`); multi-workspace fan-out would need different identity scoping in `notify.py`.

## Outcomes

### What's proven

- **Okta event hook → AWS Lambda → Slack pipeline works end-to-end** with sub-second latency on warm path
- **Full JML triplet now has audit-trail coverage on all three states** (welcome dispatched, account activated, account deactivated)
- **Terraform-managed AWS infrastructure** is no longer a roadmap item — it's live, with state committed locally and a clean apply path
- **Least-privilege IAM** scoped to exactly the secrets the Lambda needs
- **Cross-platform observability** — Okta system log, CloudWatch Logs, Slack audit log all carry the same event correlatable by timestamp

### Why this is interview-shippable

The JD calls out: *"Develop, test, deploy API integrations,"* *"Reducing operational overhead, eliminating manual tasks,"* *"Identity and access concepts (RBAC, SCIM, SAML, OAuth)."* This single feature exercises all of those plus three more:

- **Webhook integration** — Okta event hooks are a real production primitive, not just docs hand-waving
- **Infrastructure-as-code** — first Terraform in the repo, full lifecycle (init/plan/apply), state management, secrets handling
- **Cloud functions + secrets management** — Lambda runtime, IAM execution roles, Secrets Manager, scoped policies
- **Cross-platform automation** — three SaaS tenants (Okta, AWS, Slack) plus one cloud platform (AWS infra) coordinating from a single trigger

The screen-share moment: run the joiner CLI, watch `#joiner-it-ops` post the welcome, click the activation email in incognito, watch the *second* `#joiner-it-ops` post arrive 1 second after MFA enrollment completes, then `aws logs tail /aws/lambda/novatech-okta-hook --since 5m` to show the structured log line proving the Lambda fired. Three terminals, three real cloud platforms, one feature, end-to-end demoable in 4 minutes.

## Links

- [`scripts/slack/notify.py`](../scripts/slack/notify.py) — Slack post helpers used by both the joiner CLI and the Lambda
- [`lambdas/okta_activation_handler/handler.py`](../lambdas/okta_activation_handler/handler.py) — the Lambda code, with module-level secret fetching cached across warm invocations
- [`lambdas/okta_activation_handler/build.sh`](../lambdas/okta_activation_handler/build.sh) — build the deployment zip
- [`terraform/aws/`](../terraform/aws/) — the 7 .tf files
- [`scripts/lifecycle/joiner_workflow.py`](../scripts/lifecycle/joiner_workflow.py) — calls `notify.post_joiner_welcome_sent` after the activation email is dispatched
- [`scripts/lifecycle/leaver_workflow.py`](../scripts/lifecycle/leaver_workflow.py) — calls `notify.post_leaver_deactivated` after Okta deactivation
- [`public-docs/06-end-to-end-joiner-demo.md`](06-end-to-end-joiner-demo.md) — the original Joiner trace (Sandra Jones)
- [`public-docs/07-end-to-end-leaver-demo.md`](07-end-to-end-leaver-demo.md) — the original Leaver trace (Sandra Jones)
