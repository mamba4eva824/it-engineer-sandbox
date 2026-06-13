# SaaS License Dashboard

Local web dashboard for license allocation across Okta, Google Workspace, Cloud Identity, and Slack, plus JML pipeline visibility for upcoming joiners and scheduled leavers.

## Prerequisites

1. `pip install -r requirements.txt`
2. Repo-root `.env` with credentials (same as other scripts):
   - **Okta**: `OKTA_ORG_URL`, `OKTA_CLIENT_ID`, `OKTA_PRIVATE_KEY`, `OKTA_KEY_ID`, `OKTA_SCOPES`
   - **GWS**: `GWS_ADMIN_EMAIL`, service account key at `credentials/service-account-key.json` with `apps.licensing` scope
   - **Slack**: `SLACK_USER_TOKEN` (xoxp-), `SLACK_TEAM_ID` (T-prefix workspace ID)

### Slack seat counting

The dashboard calls `admin.users.list` to count active non-bot members. Your user token needs the `admin.users:read` scope.

If that scope is not available on your sandbox token, the Slack card shows an error. As a workaround, count active seats via the audit log:

```bash
python scripts/slack/audit_log_query.py --action user_created --since 30d
```

Then compare against the purchased cap in `config/dashboard/license-limits.json`.

## License limits

Purchased seat caps are configured in `config/dashboard/license-limits.json` (not fetched from vendor APIs):

| Service | Default purchased |
|---------|-------------------|
| Okta | 10 |
| Google Workspace | `null` (shows assigned count only until you set a cap) |
| Cloud Identity | 50 |
| Slack | 8 |

Edit this file to match your tenant subscriptions.

## Run

```bash
python scripts/dashboard/run.py
# → http://127.0.0.1:8080
```

Optional port:

```bash
python scripts/dashboard/run.py --port 9000
```

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard UI |
| `GET /api/licenses` | License usage for all four services |
| `GET /api/pipeline/onboarding` | STAGED/PROVISIONED users with `startDate` |
| `GET /api/pipeline/offboarding` | ACTIVE/PROVISIONED users with `endDate` |
| `GET /api/health` | Credential reachability check |

## Panels

**Onboarding pipeline** — Okta users in `STAGED` or `PROVISIONED` status with a `startDate` profile attribute, sorted soonest-first. Users with `STAGED` status and a past start date are flagged as missed activations (the 9 AM PT batch Lambda may not have run).

**Offboarding pipeline** — Okta users in `ACTIVE` or `PROVISIONED` status with an `endDate` profile attribute, sorted soonest-first. Users with end date today or in the past are flagged as due/overdue (the 5 PM PT offboarding Lambda handles today's batch).

Dates use `America/Los_Angeles`, consistent with the scheduled Lambdas.

## Security

The server binds to `127.0.0.1` by default. Do not expose it to the network without adding authentication.
