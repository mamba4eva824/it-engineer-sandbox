# Phase 5 — Autonomous orchestrator (dual-path)

Optional OpenAI GPT-5.6 Luna planner beside the Phase 4 human-in-the-loop path. HITL stays the **production default**. The orchestrator is additive: same broker, same JSM ticket, same DynamoDB table. Offboarding, scanner, Cursor skill, and broker handlers do not change in this slice.

Roadmap: [16-license-reclamation-human-in-the-loop-roadmap.md](../16-license-reclamation-human-in-the-loop-roadmap.md). Prior logs: [phase-4-human-in-the-loop.md](phase-4-human-in-the-loop.md).

**Date:** 24 Aug 2026
**Status:** Orchestrator Lambda deployed in `terraform/aws-license-reclaim/` with GPT-5.6 Luna via the OpenAI API (`gpt-5.6-luna`, secret `ohmgym-licenses/openai`). `enable_orchestrator` remains **false** (HITL is the 5pm path). CLI `orchestrate.py` can invoke the function.

---

## Dual-path contract

| Mode | How it starts | Who decides | When to use |
|---|---|---|---|
| **HITL (default)** | Ticket sits in JSM; operator runs [`.cursor/skills/reclaim-licenses/SKILL.md`](../../.cursor/skills/reclaim-licenses/SKILL.md) | Human confirm in chat | Everyday demo, holds, interview “we shipped judgment first” |
| **Agentic auto** | Terraform `enable_orchestrator = true` enables the EventBridge target on `license.scan.complete` | GPT-5.6 Luna + policy, then broker | Show autonomy after offboarding with no chat |
| **Agentic CLI** | `scripts/licenses/orchestrate.py --issue SUP-n --dry-run\|--apply` | Same orchestrator Lambda | Flag stays **off**; pick one ticket without changing the 5pm path |

Both paths call the **same broker**. Broker idempotency (`already_reclaimed`) is the mutex. If Luna returns `hold`, the ticket stays open and HITL still owns it.

`auto_reclaim: false` stays in [`config/licenses/apps.json`](../../config/licenses/apps.json); that key is a planner hint only, not a silent bypass.

---

## HITL default vs flag vs CLI

- **`enable_orchestrator` default `false`.** Deploy the orchestrator Lambda (CLI can invoke) but the EventBridge **rule is disabled** (`is_enabled = false`). AWS provider 5.x has no per-target `is_enabled`; the rule flag is what stops the target from firing. Scanner may still `PutEvents` `license.scan.complete`; nothing consumes it.
- **Flag on:** same Lambda; EventBridge target on. Post-ticket runs go agentic automatically. Skill remains the hold / leftover path.
- **Runtime env `ORCHESTRATOR_AUTO_RUN`** mirrors the Terraform flag (`true`/`false`) so a Lambda-side no-op is possible if someone enables the rule by accident.
- **CLI does not require the flag.** `aws lambda invoke` / `orchestrate.py` hits the function directly.
- Flip for a demo: `terraform apply -var='enable_orchestrator=true'` (or workspace tfvars). Flip back to restore HITL as the 5pm path.

---

## What shipped (this slice)

Terraform in the existing `terraform/aws-license-reclaim/` stack (not a new stack):

- Lambda `ohmgym-license-reclaim-orchestrator` + log group + dedicated execution role
- EventBridge rule `ohmgym-license-reclaim-orchestrator-scan-complete` on `ohmgym.licenses` / `license.scan.complete`; retries = 2; SQS DLQ `ohmgym-license-reclaim-orchestrator-dlq`
- CloudWatch Errors alarm mirroring scanner/broker (`treat_missing_data = notBreaching`, same SNS topic)
- Packaging stub at `lambdas/license_reclaim_orchestrator/` (`build.sh` → `build/handler.zip`). Real handler is a separate deliverable.

IAM (least privilege, ADR-005/ADR-006):

| Grant | Scope |
|---|---|
| DynamoDB `Query` | `jira_issue_key-index` only |
| DynamoDB `UpdateItem` | table ARN, **`planner` attribute only** (`dynamodb:Attributes`) |
| Secrets `GetSecretValue` | `ohmgym-licenses/broker-webhook-secret`, `ohmgym-licenses/jira-read`, shared Slack bot token, `ohmgym-licenses/openai` |
| **Not granted** | GitHub/Linear/Jira **write** secrets; `PutItem`/`Scan`/`DeleteItem`; broker Function URL invoke (orchestrator POSTs HTTPS like the CLI) |

Env (always set): `OPENAI_MODEL_ID=gpt-5.6-luna`, `OPENAI_SECRET_NAME=ohmgym-licenses/openai`, `OPENAI_BASE_URL=https://api.openai.com/v1`, `OPENAI_MAX_TOKENS=2048`, `ORCHESTRATOR_AUTO_RUN` tied to the flag, `BROKER_FUNCTION_URL` + `WEBHOOK_SECRET_NAME` matching the broker.

One-time account work (not Terraform): store the OpenAI API key in Secrets Manager `ohmgym-licenses/openai` (raw `sk-...` or JSON with `api_key`).

---

## Event pattern

```json
{
  "source": ["ohmgym.licenses"],
  "detail-type": ["license.scan.complete"]
}
```

Detail (scanner, after ticketed/partial persist): `issue_key`, `run_date`, `user_id` / `okta_id`, `login`, `run_id`, `status`, `apps[]`. Skip emit when status is `No Licenses to Reclaim` / `clean`.

---

## IDs / names

| Resource | Value |
|---|---|
| Variable | `enable_orchestrator` (default `false`) |
| Lambda | `ohmgym-license-reclaim-orchestrator` |
| IAM role | `ohmgym-license-reclaim-orchestrator-lambda-exec` |
| Log group | `/aws/lambda/ohmgym-license-reclaim-orchestrator` |
| EventBridge rule | `ohmgym-license-reclaim-orchestrator-scan-complete` |
| DLQ | `ohmgym-license-reclaim-orchestrator-dlq` |
| Alarm | `ohmgym-license-reclaim-orchestrator-errors` |
| Model | OpenAI `gpt-5.6-luna` (GPT-5.6 Luna); secret `ohmgym-licenses/openai` |
| Broker (unchanged) | `ohmgym-license-reclaim-broker` Function URL + `ohmgym-licenses/broker-webhook-secret` |
| Table | `ohmgym-license-reclaim-logs` / GSI `jira_issue_key-index` |

---

## Not in this slice

- Orchestrator Python (`handler.py` Converse loop), token metering, ReclaimPlan policy intersect, unit tests — separate agent.
- CLI `scripts/licenses/orchestrate.py` — separate agent.
- GRC dashboard / weekly SLA report (P5-R1–R3).
- Okta-for-AI-Agents NHI registration (P5-R5).
- `terraform apply` (operator-gated).
- Changing offboarding or broker eligibility rules. `auto_reclaim` stays `false`.
