# Okta Migration — Federation Test Changelog

Live log of the Okta → Google Workspace federation work. Captures the disposable-user test that proves the SAML + SCIM plumbing end-to-end without touching the sole super-admin account. This doc is updated in real time as each step executes.

## Purpose

The RBAC foundation (profile attributes + 10 department groups + 10 group rules, see `config/okta/desired-state.json`) shipped in the prior cycle. This phase proves the actual authentication path: a user assigned to the Okta Google Workspace app gets auto-provisioned into GWS via SCIM (Okta → Google Directory API), then successfully signs into Google services via SAML.

**Federation topology proved here:**

```
User → accounts.google.com → [SAML redirect] → Okta sign-in →
  [signed SAMLResponse] → Google ACS → session in myaccount.google.com
```

**Licensing model proved here:** Google Cloud Identity Free (50 seats available) is sufficient for SAML federation testing. The one Workspace license stays on `chris@ohmgym.com` as the break-glass account. The test user lands on `myaccount.google.com` rather than Gmail — expected, not a failure.

## Pre-test state

Captured via `python scripts/gws/inspect_sso.py` on 2026-04-21:

```
GWS SAML SSO Inspection
Admin:       chris@ohmgym.com
Customer:    C02q25mc3
Domain:      ohmgym.com

=== Inbound SAML SSO Profiles (1) ===

  Name:          Okta <> Google Workspace
  Resource ID:   02wlm7fb184ibr4
  IdP match:     Okta
  IdP entity:    https://integrator-2367542.okta.com
  SSO URL:       https://integrator-2367542.okta.com/app/google/exk126dvrcnTavyds698/sso/saml
  Logout URL:    https://integrator-2367542.okta.com
  SP entity:     https://accounts.google.com/samlrp/02wlm7fb184ibr4
  SP ACS URL:    https://accounts.google.com/samlrp/02wlm7fb184ibr4/acs

=== SSO Profile Assignments (11) ===
  OU /                       →  SAML_SSO    Okta <> Google Workspace
  OU /Engineering            →  SAML_SSO    Okta <> Google Workspace
  OU /IT-Ops                 →  SAML_SSO    Okta <> Google Workspace
  OU /Finance                →  SAML_SSO    Okta <> Google Workspace
  OU /Executive              →  SAML_SSO    Okta <> Google Workspace
  OU /Data                   →  SAML_SSO    Okta <> Google Workspace
  OU /Product                →  SAML_SSO    Okta <> Google Workspace
  OU /Design                 →  SAML_SSO    Okta <> Google Workspace
  OU /HR                     →  SAML_SSO    Okta <> Google Workspace
  OU /Sales                  →  SAML_SSO    Okta <> Google Workspace
  OU /Marketing              →  SAML_SSO    Okta <> Google Workspace

=== SAML Events (last 7 days, 0 total) ===
  (none — no SAML logins attempted in window)
```

**Key observations:**
- SAML profile exists and points at Okta (not Auth0)
- All 11 OUs including root `/` route through Okta SAML → root must be carved out for break-glass before any test
- Zero historical SAML events → no prior validation; this test is the first true exercise

## Step log

### Step 0 — Seed this changelog

- **When:** 2026-04-22 (initial commit)
- **What:** Created `public-docs/04-okta-migration.md` with pre-test snapshot.
- **Result:** ✅ Committed alongside `config/okta/desired-state.json` update for `access-gws`.

### Step 1 — GWS break-glass OU carve-out

- **When:** 2026-04-22
- **Actions:**
  - Created `/Break-Glass` OU under root (parent = Ohmgym root)
  - Moved `chris@ohmgym.com` into `/Break-Glass`
  - Security → Authentication → SSO with third-party IdP → assigned `/Break-Glass` to **None (SSO off)**
- **Verification:** `python scripts/gws/inspect_sso.py`:
  ```
  === SSO Profile Assignments (12) ===
    OU /                          →  SAML_SSO    Okta <> Google Workspace
    OU /Engineering               →  SAML_SSO    Okta <> Google Workspace
    OU /IT-Ops                    →  SAML_SSO    Okta <> Google Workspace
    ... (8 more department OUs on SAML_SSO)
    OU /Break-Glass               →  SSO_OFF     (none)
  ```
- **Result:** ✅ `/Break-Glass` exempt from SAML. Admin account (`chris@ohmgym.com`) now insulated from any Okta federation failure.

### Step 2 — Break-glass smoke test

- **When:** 2026-04-22
- **Actions:** Signed in to `admin.google.com` as `chris@ohmgym.com` with password + 2SV in a fresh incognito window
- **Result:** ✅ Google accepted password auth directly — no SAML redirect to Okta. Break-glass path confirmed working end-to-end. Admin recovery is possible even if Okta federation fails for the rest of the tenant.

### Step 3 — Add `access-gws` group via config-as-code

- **When:** 2026-04-22
- **Plan:**
  - Edit `config/okta/desired-state.json` → add `access-gws` entry to `groups[]` (no rule; manual membership)
  - `python scripts/okta/reconcile_config.py --apply --dry-run`
  - `python scripts/okta/reconcile_config.py --apply`
- **Result:** ✅ Group created. Reconcile output:
  ```
  Missing groups:  - access-gws
  Applying remediation...
    Created group: access-gws
  Remediation: 1 changes (0 schema, 1 group, 0 rule)
  Report saved: public-docs/reports/okta-rbac-foundation-2026-04-22-1205.md
  ```
  Brownfield-safe: dry-run surfaced exactly 1 expected change before the live apply. The 10 department groups and all 10 rules remained untouched. This is the first `access-*` convention group — sibling to the department groups but with manual membership.

### Step 4 — Okta GWS app provisioning enablement

- **When:** 2026-04-22
- **Actions:**
  - OAuth consent completed via Okta Admin Console → Provisioning → Configure API Integration, authenticated as `chris@ohmgym.com`
  - Enabled: Create Users, Update User Attributes, Deactivate Users
  - License dropdown: **Cloud Identity Free not available in the dropdown** (see Outcomes). Worked around by leaving license unset — SAML federation does not require a license
  - Attribute mappings: left at OIN defaults (not independently verified via API — `okta.profileMappings.read` scope not granted; verification deferred to the SCIM push result)
- **Result:** ✅ Verified via direct API (`GET /api/v1/apps/0oa126dvrcoGU7gwb698`). App `features` list includes:
  ```
  PUSH_NEW_USERS, PUSH_USER_DEACTIVATION, PUSH_PROFILE_UPDATES,
  GROUP_PUSH, REACTIVATE_USERS,
  IMPORT_NEW_USERS, IMPORT_PROFILE_UPDATES, IMPORT_USER_SCHEMA
  ```
  All three push capabilities live. Bidirectional + group push as bonus.

### Step 5 — Assign Okta GWS app to `access-gws`

- **When:** 2026-04-22
- **Actions:** Okta Admin Console → Applications → Google Workspace → Assignments → Assign to Groups → `access-gws` → Save
- **Result:** ✅ Verified via direct API:
  ```
  GET /api/v1/apps/0oa126dvrcoGU7gwb698/groups
  → ['Engineering', 'access-gws']
  ```
  (`Engineering` was assigned during earlier exploratory clicking; harmless — our test user has no `department` attribute so won't match the dept group rule.)

### Step 6 — Create test user + add to `access-gws`

- **When:** 2026-04-22 12:34 local
- **Actions:**
  - Generated 24-char password via `openssl rand -base64 18` → wrote to `/tmp/test-jml-01-pwd.txt` with mode 0600; never echoed to terminal or logs
  - `POST /api/v1/users?activate=true` via `scripts/okta/_client.py` helper with body:
    ```json
    {"profile": {"firstName": "Test", "lastName": "JML-01",
                 "email": "test-jml-01@ohmgym.com",
                 "login": "test-jml-01@ohmgym.com"},
     "credentials": {"password": {"value": "<redacted>"}}}
    ```
  - No `department` set (deliberately, to isolate federation test from dept-rule firing)
  - `PUT /api/v1/groups/{access-gws-id}/users/{user-id}` to add to access-gws
- **Result:** ✅
  - User ID: `00u127geeox7innHc698`
  - Status: `ACTIVE` (no forced password change; deterministic login for incognito test)
  - Group membership: `access-gws` (id `00g127erkrup4Pdt1698`)

### Step 7 — SCIM provisioning verification

- **When:** 2026-04-22 12:35 local (~60s after group assignment)
- **Actions:** `GET users().get(userKey='test-jml-01@ohmgym.com')` via Admin SDK Directory API
- **Result:** ✅ Test user present in GWS:
  ```
  primaryEmail:    test-jml-01@ohmgym.com
  name:            Test JML-01
  orgUnitPath:     /
  suspended:       False
  creationTime:    2026-04-22T19:34:26.000Z
  ```
  - OU placement: root `/` (still under Okta SAML SSO per Step 1's inspect_sso output — ✅ will go through SAML on sign-in)
  - SCIM push latency: ~60 seconds from Okta group assignment to GWS user visible via Directory API
  - Attribute mapping sanity: `firstName`/`lastName`/`email` all landed correctly — the OIN defaults work unmodified (validates Step 4's "trust the defaults" decision)
  - License state: not independently verified yet (Cloud Identity auto-assignment is expected). Will show in GWS Admin Console under the user's license section — confirm visually or assign manually if needed after the federation test

### Step 5 — Assign Okta GWS app to `access-gws`

- **When:** *pending — user action*
- **Plan:** Okta Admin Console → Applications → Google Workspace → Assignments → Assign to Groups → `access-gws`
- **Result:** _to be filled in_

### Step 6 — Create test user + add to `access-gws`

- **When:** *pending*
- **Plan:**
  - Login + email: `test-jml-01@ohmgym.com`
  - Name: Test JML-01
  - Department: unset (isolates federation test from dept-rule firing)
  - Password: generated via `openssl rand -base64 18`; activate=true; no forced change
  - Add to `access-gws` group
- **Result:** _to be filled in; log user ID + creation timestamp, NOT the password_

### Step 7 — SCIM provisioning verification

- **When:** *pending*
- **Plan:** Wait ~60s after adding test user to `access-gws`. Confirm in GWS Admin Console → Directory → Users that `test-jml-01@ohmgym.com` exists with Cloud Identity Free license, status Active.
- **Result:** _to be filled in_

### Step 8 — Incognito federation test (both flows)

- **When:** 2026-04-22
- **Actions:**
  - **Flow A (SP-initiated):** Fresh incognito → `https://accounts.google.com/` → entered `test-jml-01@ohmgym.com` → Google redirected to Okta SSO URL → signed in with password → MFA enrollment required (first-time factor setup) → enrolled Okta Verify push + soft-token + signed-nonce → Google SP redirected back → landed on Google account page
  - **Flow B (IdP-initiated):** Fresh incognito → `https://integrator-2367542.okta.com/` → signed in as `test-jml-01@ohmgym.com` → completed Okta Verify push → landed on Okta end-user dashboard → clicked Google Workspace tile → landed in Google Drive signed in as `test-jml-01@ohmgym.com`
- **Result:** ✅✅ Both flows pass end-to-end. Google Drive available with the test account in Flow B confirms full federation including Google-side session establishment.

### Step 9 — Post-test verification

- **When:** 2026-04-22
- **Actions:**
  - Okta System Log queried via Management API for the test user's events: **3x `user.authentication.sso` events with `outcome=SUCCESS` and `signOnMode=SAML 2.0`** observed against target `AppInstance:Google Workspace`
  - GWS Reports API (`scripts/gws/inspect_sso.py --days 1`): `login_success: 0` at time of check. Google's Reports API typically lags by 30–90 minutes for SAML events. Okta-side System Log is the authoritative real-time record. Re-check expected to surface the events within an hour
  - Break-glass not retested post-test (no Okta config changes since Step 2 validation)
- **Result:** ✅ Okta-side SSO events confirm federation working end-to-end. GWS Reports API lag is a known quirk, not a functional issue.

## Troubleshooting encountered

Three distinct blockers surfaced during the incognito test, each caught at a different layer. Each is worth a standalone interview talking point.

### Issue 1 — "Unsupported Sign On Mode" (Okta app was SWA, not SAML)

**Symptom:** Google redirected to Okta, Okta showed an error page: *"You have configured Okta to use Secure Web Authentication for Google Workspace, but Google Workspace appears to be using SAML 2.0."*

**Root cause:** The Okta Google Workspace OIN app was installed with `signOnMode=BROWSER_PLUGIN` (SWA — password vaulting via browser plugin), while the GWS SAML profile was configured to receive SAML assertions. Google hits Okta's SAML endpoint, Okta's app-level mode mismatches, Okta returns the error.

**Fix:** Okta Admin Console → Applications → Google Workspace → Sign On tab → switched to **SAML 2.0**. Verified via API:
```
GET /api/v1/apps/0oa126dvrcoGU7gwb698 → "signOnMode": "SAML_2_0"
```

### Issue 2 — IdP Entity ID mismatch between Okta and GWS

**Symptom:** After Issue 1, Google showed: *"Google Workspace — This domain is not configured to use Single Sign On."*

**Root cause:** Google's per-profile SAML validator compares the SAML response's `Issuer` value to the `IdP Entity ID` field configured on the GWS-side SSO profile. Okta's OIN Google Workspace app emits `google.com/a/ohmgym.com` (legacy Google Apps SAML pattern) as the IdP entity in its metadata, but the GWS SAML profile's `IdP entity ID` field was set to something else (from the Auth0-era setup).

**Fix:** In GWS Admin Console → Security → Authentication → SSO with third-party IdP → edited the "Okta <> Google Workspace" profile → updated **IdP entity ID** to `google.com/a/ohmgym.com`.

### Issue 3 — Audience/ACS URL mismatch (per-profile vs legacy Google Workspace SAML)

**Symptom:** After Issue 2, the same "domain not configured" error persisted despite Issuer alignment.

**Root cause discovery:** Decoded Google's `SAMLRequest` via base64+inflate on the Okta redirect URL. The AuthnRequest XML revealed Google was expecting:
```
AssertionConsumerServiceURL = https://accounts.google.com/samlrp/02wlm7fb184ibr4/acs
Issuer (= SP entity)         = https://accounts.google.com/samlrp/02wlm7fb184ibr4
```
…where `02wlm7fb184ibr4` is the profile-specific SAML SP resource ID from GWS's per-profile SSO model. Okta's OIN app emits the legacy domain-wide audience `google.com/a/ohmgym.com`, not the per-profile URI pattern. Mismatch → Google rejects with "domain not configured."

**Fix (via API — not exposed in Okta's OIN-managed UI):**
```
PUT /api/v1/apps/0oa126dvrcoGU7gwb698
{
  "settings": {
    "signOn": {
      "ssoAcsUrlOverride":    "https://accounts.google.com/samlrp/02wlm7fb184ibr4/acs",
      "audienceOverride":     "https://accounts.google.com/samlrp/02wlm7fb184ibr4",
      "recipientOverride":    "https://accounts.google.com/samlrp/02wlm7fb184ibr4/acs",
      "destinationOverride":  "https://accounts.google.com/samlrp/02wlm7fb184ibr4/acs"
    }
  }
}
```
The four `*Override` fields are Okta's designated way to override OIN defaults without breaking the managed-app semantics. The OIN Google Workspace app pre-dates GWS's per-profile SSO model, so its defaults don't match; overrides bridge the gap.

**Lesson:** When an IdP's OIN/integration preset matches an SP's legacy SAML model but the SP has been upgraded to a newer profile model (per-profile SSO, in this case), the override fields must be set explicitly. This is the exact kind of "the admin console stops at the surface; the fix lives in the API" story the project is built around.

### Other common failure modes (not hit this run; documented for future reference)

| Symptom | Likely cause | Fix |
|---|---|---|
| "NameID format not supported" | Okta defaulting to `unspecified` | Okta app → Sign On → NameID format = `EmailAddress` |
| Test user created in Okta but not in GWS | Okta Provisioning not enabled or OAuth consent expired | Re-run Provisioning → Configure API Integration → re-auth as chris |
| 403 on Okta `POST /api/v1/users` | API Services app not Super Admin, or `okta.users.manage` not in OKTA_SCOPES | Verify scope + role |
| `failure_type: user_not_found_on_domain` | SCIM push hasn't completed yet | Wait 60s and retry; check Okta Push Status under the GWS app |

## Outcomes + decisions

### What's proven

- **Okta → GWS federation works end-to-end** in both SP-initiated (`accounts.google.com` → Okta → Google) and IdP-initiated (Okta dashboard tile → Google Drive) flows. The test user `test-jml-01@ohmgym.com` successfully signed into Google services via Okta authentication + MFA
- **Okta SCIM provisioning works** — assigning the test user to `access-gws` triggered creation of the user in GWS via Directory API within ~60s
- **Break-glass pattern validated** — `chris@ohmgym.com` moved to `/Break-Glass` OU with `SSO_OFF`, password-auth login confirmed working
- **Config-as-code extends cleanly to access groups** — `access-gws` added via `config/okta/desired-state.json` + `reconcile_config.py --apply`, demonstrating the `access-*` convention for future AWS/Slack access groups
- **OIN override pattern documented** — SAML `*Override` fields in Okta are the canonical way to adapt OIN-managed apps to modern SP SAML profiles when OIN defaults are stale (see Issue 3 in Troubleshooting)

### Key decisions made along the way

| Decision | Rationale |
|---|---|
| Cloud Identity Free as the test license (not Workspace) | Test proves SAML/SCIM plumbing; doesn't require Gmail. 50 CI seats vs. 1 spare Workspace seat. |
| No `department` attribute on test user | Isolates federation test from dept-rule firing — if auth fails, we know it's federation, not rule misfire |
| `access-gws` with manual membership (no rule) | GWS-seat decisions are business/cost decisions, not derivable from department. Rule-based auto-assignment would be dangerous at scale. |
| Override via API, not UI | OIN-managed apps hide override fields from UI; API is the canonical source. Documented for future operators. |
| Keep test user post-test (don't deprovision) | Reusable for Phase 2 user-provisioning work. One CI Free seat of 50 is cheap insurance. |

### Deferred to later phases

- **Department rule firing verification** (Phase 2, when multiple test users exist across departments)
- **Okta → AWS IAM Identity Center SAML federation** — mirror this work against AWS as the SP. The override pattern will likely repeat for AWS's per-region or per-account URIs.
- **Full user provisioning (5–8 NovaTech users across 3–4 departments)** — respecting the 10-user Okta cap
- **Extending `reconcile_config.py` with an app-assignment surface** — today app→group assignments are UI-only; Phase 2 should push them into `desired-state.json`
- **`scripts/okta/provision_users.py`** — the batched multi-user equivalent of the one-off MCP/API create we did in Step 6

### New ADR candidates for `okta_workato_zendesk_slack.md`

- **ADR-008: OIN override fields are the canonical adapter for managed SAML apps** — when OIN preset values don't match the SP's modern SAML profile, use `settings.signOn.*Override` via API. Documented as a pattern so future OIN integrations don't spend an hour at the same debugging step.

## Links

- Plan: `/Users/christopherweinreich/.claude/plans/alrighty-the-mcp-server-spicy-hare.md`
- Desired state: `config/okta/desired-state.json`
- Reconcile tool: `scripts/okta/reconcile_config.py`
- GWS inspector: `scripts/gws/inspect_sso.py`
- Previous reconcile reports: `public-docs/reports/`
- Related docs: `public-docs/01-auth0-identity-platform.md`, `public-docs/02-aws-saml-federation.md`, `public-docs/03-gws-federation-and-administration.md`
