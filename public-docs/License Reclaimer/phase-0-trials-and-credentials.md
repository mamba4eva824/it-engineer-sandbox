# Phase 0 — Trials & Credentials (Exec Report)

License Reclamation sandbox: stand up non-SCIM SaaS tenants with **read-only membership APIs** so a later scanner Lambda can answer “does this leaver still have a paid seat?” No automation in this phase.

Roadmap: [16-license-reclamation-human-in-the-loop-roadmap.md](../16-license-reclamation-human-in-the-loop-roadmap.md). Companion log: [phase-1-jsm-foundation.md](phase-1-jsm-foundation.md) (JSM intake already exists on the same Jira site).

**Date:** 13 Aug 2026  
**Status:** Complete for v1 catalog (GitHub + Jira + Linear). Figma parked. Demo user seeding (P0-R5) still open.

---

## Executive summary

Okta deactivation + SCIM already covers Slack and Google Workspace. The reclaim product is for apps that **keep billing seats after the IdP is off**. Phase 0 proved we can inventory those seats over public APIs with least-privilege tokens — without putting revoke keys in Cursor.

Three tenants now answer **“is user X a member?”** with curl/Python:

| App | Tenant | Membership API |
|---|---|---|
| GitHub | org [`ohmgym-sandbox`](https://github.com/ohmgym-sandbox) (Free) | `GET /orgs/{org}/members/{user}` → 204 / 404 |
| Jira | [`buffett-dev.atlassian.net`](https://buffett-dev.atlassian.net) (existing JSM) | `GET /rest/api/3/user/search?query={email}` via `api.atlassian.com/ex/jira/{cloudId}` |
| Linear | workspace [`it-systems-sandbox`](https://linear.app/it-systems-sandbox) (Free) | GraphQL `users { nodes { email active } }` |

Figma Starter team **OhmGym** was created and authenticated, then dropped from the v1 allowlist: Figma’s public REST spec has no team-members route on this plan. Member/SCIM APIs are Organization/Enterprise.

**Interview line:** “I hit the ceiling of the admin console and the vendor’s free-tier API in the same afternoon. GitHub and Linear list members on the free plan; Figma does not. I swapped the third connector instead of pretending the endpoint existed, and I kept write tokens out of the agent.”

Maps to: API-driven SaaS integrations, least privilege, catching orphaned seats after offboarding, and knowing when a SKU gate is the real blocker (Headspace-style vendor constraint, not a missing curl flag).

---

## Goals vs. outcome


| ID | Requirement | Outcome |
|---|---|---|
| P0-R1 | GitHub org + `read:org` for scan | **Met.** Free org `ohmgym-sandbox`; classic PAT `GITHUB_READ_TOKEN`. |
| P0-R2 | Figma team + token that lists members | **Partial / parked.** Team + PAT exist; `GET /v1/teams/{id}/members` is **404** (route not in OpenAPI). Replaced by Linear for the third connector. |
| P0-R3 | Existing Jira/JSM + token for issue create and user lookup | **Met.** Reused `buffett-dev`; scoped token `read:jira-work`, `read:jira-user`, `write:jira-work`. |
| P0-R4 | OIN / SSO notes per app | **Met.** See below. All three v1 apps: SSO/SCIM gated on paid tiers; reclaim stays API-side. |
| P0-R5 | Seed 2–3 test users mirrored to Okta leavers | **Open.** Invites skipped on purpose so GitHub / Figma / Linear / Jira get the same demo identities in one pass. |

**Exit criterion** (roadmap): *Manual curl/Python can answer “is user X a member?” for all three apps.* **Met** for the v1 trio after substituting Linear for Figma.

---

## Tenants (non-secret)

| Platform | Identifier | Plan | Role in architecture |
|---|---|---|---|
| GitHub | `ohmgym-sandbox` (org id `316784624`) | Free | Reclaim **target** — org membership |
| Linear | `it-systems-sandbox` (org uuid `2cb9e2d3-f42b-42a1-a066-8bc4006c2624`) | Free | Reclaim **target** — workspace membership |
| Jira / JSM | `buffett-dev.atlassian.net` · cloudId `359c6979-fbf2-459e-b948-9feb032a082e` | Existing site | **Both** ITSM queue (License Reclamation) **and** a product-seat target |
| Figma | team `1669918311381463155` (OhmGym) | Starter | Parked — UI talking point only |
| Linear (lab tickets) | `buffett-dev` | existing | **Not** the reclaim target. Keep for this repo’s issue tracker. |

GitHub personal account `mamba4eva824` is org owner. Linear and Jira authenticate as `buffett.dev117@gmail.com`. GWS admin remains `chris@ohmgym.com` (not a member of these three SaaS tenants yet).

---

## Membership lookup evidence (13 Aug 2026)

Positive and negative checks on the same run. Tokens never logged.

### GitHub `ohmgym-sandbox`

| Login | Result |
|---|---|
| `mamba4eva824` | **MEMBER** (HTTP 204) |
| `octocat` | **NOT_MEMBER** (HTTP 404) |

Current members: `mamba4eva824` only.

### Jira `buffett-dev` (scoped token **gateway**)

Site URL `https://buffett-dev.atlassian.net/rest/api/3/myself` → **401**. Same token → **200** at:

`https://api.atlassian.com/ex/jira/359c6979-fbf2-459e-b948-9feb032a082e/rest/api/3/myself`

| Email | On site? |
|---|---|
| `buffett.dev117@gmail.com` | **Yes** (Christopher Weinreich, active) |
| `chris@ohmgym.com` | **No** |
| `marcus.reyes@ohmgym.com` | **No** |

`GET /applicationrole` (product-seat counts) → **401 scope does not match**. User search is enough for Phase 0; product-access listing is a Phase 2 connector detail (likely `manage:jira-configuration` or Admin APIs).

### Linear `it-systems-sandbox`

| Email | Result |
|---|---|
| `buffett.dev117@gmail.com` | **MEMBER** (active, admin) |
| `chris@ohmgym.com` | **NOT_MEMBER** |
| `marcus.reyes@ohmgym.com` | **NOT_MEMBER** |

Workspace also lists Linear’s system app user. Scanner must match **human emails** and ignore `*.linear.app` / OAuth app identities.

### Figma OhmGym (parked)

| Check | Result |
|---|---|
| `GET /v1/me` | **200** — Chris, `chris@ohmgym.com` |
| `GET /v1/teams/{id}/members` | **404** Not found (Bearer and `X-Figma-Token`) |
| `GET /v1/teams/{id}/projects` | **403** — missing `projects:read` (proves scope errors are explicit) |

Missing scopes return **403** with the required scope named. Members returns a bare **404**. Extra PAT scopes and inviting a second user would not create that route. Org-level `GET /v1/orgs/{id}/members` is Organization/Enterprise.

---

## Credentials (names only)

Gitignored `.env` in the main checkout (`Documents/Projects/IT Operations Sandbox /.env`), symlinked into this worktree. **Do not commit.** Cursor / Claude do not get write tokens.

| Env var | Use |
|---|---|
| `GITHUB_ORG` / `GITHUB_READ_TOKEN` | Classic PAT, scope **`read:org` only** |
| `JIRA_BASE_URL` / `JIRA_CLOUD_ID` / `JIRA_EMAIL` / `JIRA_API_TOKEN` | Scoped token; calls must use **`api.atlassian.com/ex/jira/{cloudId}`** |
| `LINEAR_API_KEY` | Personal API key issued **in** `it-systems-sandbox` (keys are per workspace) |
| `FIGMA_TEAM_ID` / `FIGMA_ACCESS_TOKEN` | Kept for the parked tenant; `current_user:read` + `folders:read` |

Phase 3 will add **separate** write secrets (`GITHUB` `admin:org`, Linear **Admin**, Jira deactivate/product-access). ADR-006: scanner role must not `GetSecretValue` on write ARNs.

Linear MCP OAuth is **not** a substitute for `LINEAR_API_KEY`. MCP cannot mint keys or create workspaces; the scanner Lambda cannot use Cursor’s OAuth session.

---

## OIN / SSO notes (P0-R4)

Reclaim stays **API membership**, not Okta SSO, until a paid SKU makes SAML worth wiring. That is the point of this product: seats that outlive IdP deactivation.

| App | Okta OIN / SSO | SCIM | Sandbox implication |
|---|---|---|---|
| **GitHub** | GitHub.com (OIN) — SAML is Enterprise Cloud | Enterprise Cloud (org SSO + SCIM) | Free org: password/PAT membership. Orphaned org members after Okta deactivate is the demo. |
| **Jira Cloud** | Atlassian Cloud / Guard for SAML | Atlassian Guard / paid identity | `buffett-dev` is a personal site (`buffett.dev117@gmail.com`), not `ohmgym.com`. User lookup works; domain-claimed SSO is out of band. |
| **Linear** | Okta OIN exists | SAML + SCIM on **Enterprise** | Free workspace: every human is an admin. GraphQL `users` is the inventory API. Suspend/remove needs an **Admin** key in Phase 3. |
| **Figma** | OIN; SAML on Organization | Organization / Enterprise | Starter cannot list members via REST. Parked. |

---

## Decisions

| Decision | Why |
|---|---|
| Reuse Jira `buffett-dev` instead of a new OhmGym site | P0-R3; same site as License Reclamation JSM (Phase 1). Dual role: work queue + product users. |
| GitHub **Free** org, not Team trial | `read:org` + remove-member work on Free. No card. |
| Substitute **Linear** for Figma as the third connector | Need a membership API on a free/trial SKU. Linear workspace already used for this lab; new workspace `it-systems-sandbox` keeps reclaim seats off the `buffett-dev` issue tracker. |
| Do not create Linear workspace via MCP | MCP has no “create organization” tool. `createOrganizationFromOnboarding` is an onboarding mutation, not the scanner path. UI create + new PAT. |
| Skip seeding leavers in Phase 0 signup wizards | P0-R5 needs the **same** 2–3 Okta emails on GitHub, Linear, and Jira. `@ohmgym.com` mailboxes may not accept invites yet. |
| Two apps would have been enough for the POC | Architecture (scan → ticket → human → broker) does not need three. Three is a better interview catalog and matches ADR-008’s “expand = connector + allowlist row.” |

Allowlist: `config/licenses/apps.json` — `github` + `jira` + `linear` enabled; `figma` `enabled: false`.

---

## What was hard (console vs. API)

**Automated browsers cannot open these accounts.** GitHub Google OAuth and Figma signup treat DevTools-attached Chrome as automation. Signups were done in a normal browser.

**Scoped Jira tokens look revoked if you call the site URL.** Classic mental model is `https://{site}.atlassian.net` + Basic `email:token`. Scoped tokens require the platform gateway. Phase 1 notes already warned the worktree cannot see `.env`; this phase adds: **wrong base URL → 401 even with a valid token.**

**Figma PAT UI has no `team_members:read`.** `files:read` is deprecated; granular file scopes do not list people. Official OpenAPI team paths are projects, folders, components, webhooks — not members.

**Linear keys are workspace-scoped.** A PAT minted on `buffett-dev` cannot see `it-systems-sandbox`. After creating the reclaim workspace, the `.env` key had to be replaced. Viewer UUID changed with the org.

**Team id ≠ team name.** Figma `FIGMA_TEAM_ID` was briefly set to `OhmGym`. The id is the numeric path segment in `figma.com/files/team/{id}/...`.

---

## Open items before Phase 2

1. **P0-R5** — Invite 2–3 Okta leavers (e.g. `marcus.reyes@ohmgym.com`) to GitHub `ohmgym-sandbox`, Linear `it-systems-sandbox`, and Jira `buffett-dev`. Confirm membership APIs flip from NOT_MEMBER to MEMBER.
2. **Jira product access** — Decide whether Phase 2 scans “account exists” (`read:jira-user`) or licensed product seats (extra admin scope / Admin Hub API).
3. **Secrets Manager** — Promote `.env` read tokens to `ohmgym-licenses/*-read` in us-west-1 when the scanner stack is Terraform’d. Do not copy write tokens into Cursor.
4. **Linear write path** — Confirm `userSuspend` / equivalent with an Admin key before promising broker reclaim (scan is proven).

Phase 1 JSM foundation is already done on this Jira site. Next build phase is **Phase 2 — License Scanner Lambda** (`leaver.completed` → GitHub + Linear + Jira read → ticket if any `active`).

---

## JD / resume mapping

| JD theme | This phase |
|---|---|
| SSO / SCIM from the application side | Documented where OIN/SAML is SKU-gated; chose API reclaim instead of fake SSO on Free |
| Python against SaaS APIs | Membership probes against GitHub REST, Atlassian gateway, Linear GraphQL |
| Catch drift / orphaned access | Positive + negative member checks; machine users excluded from Linear |
| Partner with Security / least privilege | Read-only tokens; write keys deferred; MCP OAuth barred from Lambda |
| Final escalation / vendor ceiling | Figma 404 vs 403 diagnosis; swapped connector rather than over-scoping the PAT |
