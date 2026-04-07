# Auth0 → AWS SAML Federation

## Overview

Configured Auth0 as a SAML 2.0 Identity Provider for AWS IAM Identity Center, enabling NovaTech users to SSO into AWS with department-based Permission Set assignments. The SAML assertion carries dynamic attributes that determine each user's AWS access level.

## Architecture

```
Auth0 Tenant (SAML 2.0 IdP)
  │
  │ Post-Login Action injects:
  │   - RoleSessionName (email)
  │   - AccessLevel (Admin/PowerUser/ReadOnly)
  │   - department, role_title
  │   - SessionDuration (8 hours)
  │
  ▼
AWS IAM Identity Center (SP)
  │
  │ Permission Set assignment
  │ based on department:
  │
  ├── IT-Ops        → Admin (AdministratorAccess)
  ├── Engineering   → PowerUser (PowerUserAccess)
  ├── Data          → PowerUser (PowerUserAccess)
  └── All others    → ReadOnly (ReadOnlyAccess)
```

## Work Completed

### AWS Setup
- Created dedicated AWS account for the NovaTech sandbox
- Created AWS Organization (prerequisite for IAM Identity Center)
- Enabled IAM Identity Center and changed identity source to External identity provider
- Created 3 Permission Sets mapped to department categories:
  - **Admin** — `AdministratorAccess` for IT-Ops
  - **PowerUser** — `PowerUserAccess` for Engineering, Data
  - **ReadOnly** — `ReadOnlyAccess` for all other departments

### SAML Configuration
- Created Auth0 Regular Web Application with SAML2 Web App addon enabled
- Configured ACS URL, Audience (SP Entity ID), and NameID format (`emailAddress`)
- Downloaded Auth0 IdP Metadata XML (contains X.509 signing certificate) and uploaded to AWS
- Certificate trust established — AWS cryptographically verifies SAML assertions signed by Auth0

### Post-Login Action (SAML Attribute Mapping)
- Deployed an Auth0 Action (Node.js) on the post-login trigger
- Scoped to only fire for the AWS SAML application (client_id check)
- Reads `user_metadata.department` and maps to Permission Set via lookup table
- Injects SAML attributes: RoleSessionName, SessionDuration, AccessLevel, department, role_title
- Department-based RBAC is enforced at the IdP level, enabling dynamic Permission Set assignment

### Test Users Provisioned
- 5 test users created in AWS Identity Store across different departments
- Verified end-to-end SSO flow: Auth0 login → SAML assertion → AWS session with correct Permission Set

## Troubleshooting

### Issue 1: SAML Audience Mismatch (403 on AWS)
**Symptom:** Auth0 login succeeded (`type=s` in logs), but AWS returned an error after receiving the assertion.

**Diagnosis:** Checked Auth0 tenant logs — successful authentication confirmed the issue was in the assertion format, not credentials. Inspected the SAML addon config and found the `audience` field was set to a placeholder instead of the actual AWS Issuer URL.

**Fix:** Updated the audience to the correct AWS IAM Identity Center Issuer URL.

**Takeaway:** A successful IdP login with an SP-side error always points to assertion format — audience, NameID, or signing issues.

### Issue 2: SAML NameID Format Mismatch (403 persisted)
**Symptom:** After fixing the audience, the same error persisted.

**Diagnosis:** The NameID format was set to `persistent` (sends an opaque identifier) instead of `emailAddress` (sends the actual email). AWS Identity Store matches users by email, so the format must match.

**Fix:** Changed `nameIdentifierFormat` from `persistent` to `emailAddress`.

**Takeaway:** The NameID format is one of the most common SAML pitfalls. The SP needs to match the NameID to a user record — if the format doesn't match expectations, auth fails from the SP's perspective even though the IdP succeeded.

## SAML Debugging Methodology

This consistent pattern works across any IdP/SP combination (Auth0, Okta, Azure AD, Google):
1. Check IdP logs — did authentication succeed?
2. If yes, the problem is in the assertion (audience, NameID, signing, clock skew)
3. Verify the audience matches the SP's Entity ID exactly
4. Verify the NameID format matches what the SP expects
5. Use browser SAML tracer or IdP logs to inspect the raw assertion
