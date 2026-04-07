# Google Workspace Federation & Administration

## Overview

Set up Google Cloud Identity Free as the collaboration platform for NovaTech, with Auth0 SAML federation, OU-based security policies, cross-platform drift detection, and Python automation via the Admin SDK and Cloud Identity API.

## Architecture

```
Auth0 Tenant (SAML 2.0 IdP)
  │
  │ SAML assertion with department + role_title
  │
  ▼
Google Cloud Identity Free
  │
  ├── 10 Department OUs
  │   ├── Engineering, IT-Ops, Finance, Executive
  │   ├── Data, Product, Design, HR, Sales, Marketing
  │   │
  │   ├── Per-OU 2-Step Verification
  │   │   ├── Enforce: IT-Ops, Executive, Finance, HR
  │   │   └── Allow: Engineering, Data, Product, Design, Sales, Marketing
  │   │
  │   └── Per-OU Third-Party App Governance
  │       ├── Block: Finance, HR, Executive
  │       └── Inherited (allow): all others
  │
  └── SSO Profile assigned to all 10 OUs

Python Automation (Admin SDK + Cloud Identity API)
  ├── OU creation via Directory API
  ├── User provisioning into correct OUs
  ├── Cross-platform drift detection (Auth0 → GWS)
  └── Security policy audit tool
```

## Work Completed

### Domain & Tenant Setup
- Signed up for Cloud Identity Free and verified domain via DNS TXT record (GoDaddy)
- Created GCP project with Admin SDK API and Cloud Identity API enabled
- Configured service account with domain-wide delegation (5 OAuth scopes)
- Service account key stored in gitignored credentials directory

### OU Architecture
- Designed 10-department OU structure mirroring NovaTech's organization
- Created 2 OUs manually via Admin Console (console familiarity)
- Automated remaining 8 OUs via `scripts/gws/create_ous.py` (Directory API)
- Script is idempotent — checks for existing OUs, handles 409 conflicts, supports dry-run

### Auth0 → GWS SAML Federation
- Created Auth0 Regular Web Application with SAML2 addon for Google Workspace
- Configured Google Admin Console SSO profile with Auth0 sign-in URL, sign-out URL, and X.509 certificate
- Assigned SSO profile to all 10 department OUs (admin account exempt from SSO)
- Deployed Auth0 post-login Action injecting department + role_title into SAML assertions
- Verified IdP-initiated SSO flow end-to-end

**Key troubleshooting:** Hit a SAML audience mismatch — Auth0 was configured with the generic `google.com/a/{domain}/acs` format, but Google's newer per-profile SSO uses **unique Entity ID and ACS URL per SAML profile** (visible in SP Details). Fixed by using the profile-specific values. Same debugging methodology as the AWS SAML federation: check IdP logs first, confirm auth succeeded, then inspect the assertion format.

### User Provisioning
- Built `scripts/gws/provision_users.py` to create users in correct department OUs via Directory API
- Sets name, orgUnitPath, department, title, cost center, and manager relationships
- Supports `--dry-run`, `--department` filter, `--count` limit
- Hit Cloud Identity Free license cap (10 users) — provisioned 11 users across Engineering + IT-Ops

### Per-OU Security Policies

**2-Step Verification:**
| Policy | OUs |
|--------|-----|
| **Enforce** (all users must enroll) | IT-Ops, Executive, Finance, HR |
| **Allow** (opt-in) | Engineering, Data, Product, Design, Sales, Marketing |

Rationale: Enforced for OUs with elevated access (admin), sensitive data (financial, PII), or high-value targets (executives). Balance security with productivity for others.

**Third-Party App Governance:**
| Policy | OUs |
|--------|-----|
| **Block** unconfigured apps | Finance, HR, Executive |
| **Inherited** (allow) | All others |

Rationale: Prevent unauthorized OAuth grants for OUs handling sensitive data. Engineering needs flexibility for developer tooling.

### Cross-Platform Drift Detection

Built `scripts/lifecycle/sync_auth0_gws.py` — uses Auth0 as the source of truth for user departments and ensures GWS OU placement matches.

**How it works:**
1. Pulls all users from Auth0 with `user_metadata.department`
2. Pulls all users from GWS with `orgUnitPath`
3. Compares and reports four categories of drift:
   - **OU mismatches** — user in wrong OU (auto-remediates)
   - **Missing from GWS** — Auth0 user not provisioned
   - **Orphaned in GWS** — GWS user not in Auth0
   - **Unknown department** — unmapped department
4. Generates markdown drift reports

This is SCIM-like provisioning from the application side — Auth0 owns the user attributes, GWS OU placement is derived from them.

### Security Policy Audit Tool

Built `scripts/gws/audit_policies.py` — reads per-OU policies from the Cloud Identity Policy API and compares against desired state defined in code.

**Final audit result:** 20 checks, 0 drift — all OUs match their expected 2SV and third-party app policies.

The desired state is a Python dictionary in the script — the code *is* the policy documentation. Running the audit after any policy change gives an automated compliance check.

### Cloud Identity Policy API Investigation

Systematically tested the Cloud Identity Policy API (v1beta1) write capabilities:

| Operation | Result |
|-----------|--------|
| List/Get policies (read) | Works |
| Create new policies (write) | 500 Internal Error |
| Patch existing policies (write) | 400 "Updates not supported" |

Tested across all setting types: security, API controls, Drive, service status. Also explored GAM (GAMADV-XTD3) — same limitation (uses the same API).

**Resolution:** Admin Console is the only write path on Cloud Identity Free. The Python scripts serve as read-only audit and drift detection tools. With a Google Workspace or Cloud Identity Premium license, the same architecture extends to full read-write policy automation.

## Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/gws/create_ous.py` | Create department OUs via Directory API (idempotent, dry-run) |
| `scripts/gws/provision_users.py` | Provision users into correct OUs with org metadata |
| `scripts/gws/configure_2sv.py` | 2SV policy desired state definition + API exploration |
| `scripts/gws/audit_policies.py` | Policy audit: read Cloud Identity API, compare against desired state |
| `scripts/lifecycle/sync_auth0_gws.py` | Auth0 → GWS drift detection with 4 categories + auto-remediation |

## Technical Decisions

**Why Cloud Identity Free?** Full Admin Console, Directory API, and OU management without a paid license. The trade-off: Policy API is read-only, and user licenses are capped at 10. For demonstrating tenant architecture, API automation, and security policy design, it's sufficient.

**Why per-OU policies?** Google Workspace's OU model is the primary mechanism for applying differentiated security policies. Enforcing 2SV and blocking third-party apps for sensitive departments (Finance, HR, Executive) while allowing flexibility for Engineering mirrors real-world compartmentalization.

**Why Python for everything?** The Admin SDK Directory API and Cloud Identity Policy API are both accessible via Python with service account authentication and domain-wide delegation. No GUI clicks recorded as automation.
