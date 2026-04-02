# IT Operations Sandbox — Project Plan

## Enterprise SaaS Platform Engineering — Interview Preparation

**Auth0 + Google Workspace + Slack + AWS + Claude MCP**
Christopher Weinreich | 10-Week Hands-On Lab Roadmap

---

## Project Overview

This project builds a series of interconnected sandbox environments that replicate enterprise collaboration platform engineering at scale. Each phase produces a demonstrable project you can walk through in interviews — with architecture diagrams, working code, and live system access.

**Target Role:** Enterprise SaaS Engineer — owning tenant-wide architecture for Google Workspace, Slack, and the surrounding identity/collaboration ecosystem. The JD emphasizes going deep on these platforms (cloud infrastructure and endpoints live with separate teams), building integrations in Python against SaaS APIs where the admin console stops, and owning platform configuration as code.

**Why Auth0?** Auth0 is part of the Okta ecosystem (acquired 2021) and shares the same identity concepts — SSO, SAML, OIDC, RBAC, SCIM, lifecycle automation. The free developer tier requires only a personal email. All skills transfer directly to Okta interview conversations, and fluency in both platforms demonstrates deeper understanding of identity protocols rather than vendor-specific muscle memory.

**Why Google Cloud Identity Free?** Provides the full Admin Console, Directory API, Admin SDK, and OU management without a paid Workspace license. Lets you demonstrate tenant architecture, data governance policies, and API-level automation — the core of the role. Using `your-domain.com` as the verified domain.

**Why Slack Developer Sandbox?** Free Enterprise-grade workspace with Admin API access, SCIM endpoints, and app governance controls. Lets you demonstrate workspace provisioning, channel lifecycle management, and third-party app review — all via API, not just the admin console.

### Existing Resources
- AWS Free Tier sandbox (active)
- Auth0 Developer tenant (active)
- 100 NovaTech mock users provisioned with roles + metadata
- Auth0 → AWS SAML federation (active)
- Auth0 MCP server (connected)
- Domain: `your-domain.com` (available for Cloud Identity verification)

### Total Timeline
10 weeks at 1-2 hours per day, or 5 weeks at 3-4 hours per day

---

## Phase 1: Foundation & Platform Setup (Week 1-2)

Stand up all three core platforms — Auth0 (IdP), Google Cloud Identity (collaboration), and Slack (communication) — and federate them. This phase establishes the identity layer everything else depends on.

| Timeline | Task | Details & Interview Talking Points |
|----------|------|------------------------------------|
| Day 1-2 | Auth0 Tenant + User Provisioning | **DONE.** Auth0 developer tenant configured. 100 NovaTech users provisioned via Python Management API scripts with department metadata, role assignments, and app_metadata. 10 roles mapped to departments. |
| Day 3-4 | Auth0 RBAC + SAML Federation to AWS | **DONE.** Resource server with 30 scoped permissions. SAML 2.0 federation to AWS IAM Identity Center with post-login Action mapping departments to Permission Sets (Admin/PowerUser/ReadOnly). |
| Day 5-7 | Google Cloud Identity Free Setup | Sign up for Cloud Identity Free on `your-domain.com`. Verify domain via DNS TXT record. Build OU structure mirroring NovaTech departments (Engineering, IT-Ops, Finance, Executive, Data, Product, Design, HR, Sales, Marketing). Create admin account and enable Admin SDK + Directory API. |
| Day 8-10 | Slack Developer Sandbox Setup | Enroll in Slack Developer Program. Provision Enterprise sandbox workspace. Create channels mirroring NovaTech department structure (#engineering, #it-ops, #finance, etc.). Enable Admin API and SCIM provisioning. Configure Slack as an Auth0 SSO application. |
| Day 11-12 | SSO Federation (Auth0 → GWS + Slack) | Configure Auth0 as SAML/OIDC IdP for Google Workspace. Configure Auth0 SSO for Slack Enterprise. Test SP-initiated and IdP-initiated flows. This is "the application side of SSO connections" the JD calls out. |
| Day 13-14 | MFA & Adaptive Authentication | Configure Auth0 Guardian MFA (push, TOTP). Create Auth0 Actions for adaptive MFA based on risk signals (new device, impossible travel). Build step-up authentication for privileged access. Maps to Headspace zero-trust rollout. |

**Interview framing:** "I stood up a three-platform identity architecture — Auth0 as the IdP federating into Google Workspace and Slack via SAML/OIDC — with 100 users, RBAC, and adaptive MFA. This mirrors the SSO federation work I did at Headspace with Okta, but here I configured the application side of every connection, not just the IdP side."

---

## Phase 2: Google Workspace Architecture & Automation (Week 3-4)

Go deep on Google Workspace — the core platform in the target role. Build tenant architecture, data governance policies, and Python automation against the Admin SDK and Directory API. The goal is to demonstrate that you've gone beyond the admin console and solved problems in code.

| Timeline | Task | Details & Interview Talking Points |
|----------|------|------------------------------------|
| Day 1-3 | OU Architecture & Policy Design | Design NovaTech's OU hierarchy with per-OU security policies. Configure different Drive sharing rules per department (e.g., Finance: internal-only sharing; Engineering: domain + external collaborators). Set per-OU app access policies. Document architectural decisions. |
| Day 4-6 | Directory API Automation (Python) | Write Python scripts against the Admin SDK Directory API to: bulk-create users in correct OUs, manage group memberships by department, sync user attributes from Auth0 user_metadata. This is SCIM-like provisioning from the application side — the JD's core ask. |
| Day 7-9 | Data Governance & Compartmentalization | Design compartmentalization model for NovaTech: which OUs can share externally, DLP rules for sensitive content (finance reports, HR records), Drive permission auditing. Write Python scripts to audit sharing permissions and flag over-exposed files. This directly maps to the JD's "data governance for collaboration content." |
| Day 10-12 | Third-Party App Governance | Audit and configure third-party app access in GWS. Build a Python script that uses the Reports API to identify third-party apps with OAuth grants, categorize by risk level, and generate an app governance report. Configure app allowlisting/blocklisting per OU. Maps to JD's "third-party app governance." |
| Day 13-14 | GWS Config-as-Code | Export Google Workspace configuration to version-controlled Python scripts (not Terraform — GWS doesn't have a mature provider). Build idempotent scripts that can recreate OU structure, group memberships, app policies, and sharing rules from code. "Auditable, repeatable, and version-controlled" — the JD's exact words. |

**Interview framing:** "I designed a compartmentalization model for a 100-person company in Google Workspace — per-OU sharing policies, DLP rules, third-party app governance — then codified the entire tenant configuration in Python against the Admin SDK. When the admin console stopped being enough, I wrote the automation myself. At Headspace, I enforced similar HIPAA-compliant access controls for PHI data across Google Workspace."

---

## Phase 3: Slack Platform Engineering (Week 5-6)

Go deep on Slack — the second core platform. Build workspace architecture, channel governance, SCIM provisioning, and app management. Demonstrate Enterprise-tier administration via API.

| Timeline | Task | Details & Interview Talking Points |
|----------|------|------------------------------------|
| Day 1-3 | Workspace Architecture & Channel Governance | Design NovaTech's Slack workspace topology. Create channel naming conventions and lifecycle policies (archive stale channels, enforce prefixes like #proj-, #team-, #dept-). Write Python scripts against the Slack Web API to audit channels, identify abandoned channels, and enforce naming conventions. |
| Day 4-6 | SCIM Provisioning (Auth0 → Slack) | Build Python automation that provisions Auth0 users into Slack via the SCIM API. Map Auth0 `user_metadata.department` to Slack user groups and default channels. Handle Joiner (create + assign channels), Mover (update groups), Leaver (deactivate). This is "SCIM attribute mappings from the application side." |
| Day 7-9 | App Governance & Security Hardening | Build a Slack app approval workflow. Write Python scripts against the Admin API to: list all installed apps and bot tokens, audit OAuth scopes per app, flag apps with excessive permissions, generate a third-party app risk report. Configure Slack app management policies. Partner-with-Security framing for interviews. |
| Day 10-12 | Slack Integrations & Automation | Build a Slack bot that integrates with Auth0 and GWS: post notifications for JML events (new hire welcome, department transfer, offboarding), allow IT-Ops to trigger access reviews from Slack commands, surface real-time identity alerts. Demonstrates "integrations that fill gaps the vendors left open." |
| Day 13-14 | Slack Config-as-Code | Export Slack workspace configuration to version-controlled Python scripts. Channel structure, user group definitions, app policies, workspace settings — all deployable from code. Pair with the GWS config-as-code from Phase 2 for a full collaboration-stack-as-code story. |

**Interview framing:** "I built SCIM provisioning from Auth0 into Slack entirely via API — mapping identity attributes to workspace access, user groups, and channel membership. Then I codified the entire workspace configuration so it's auditable and repeatable. At Headspace, I built similar provisioning workflows with Okta SCIM, but here I wrote the integration logic directly because the vendor connector didn't cover our use case."

---

## Phase 4: Cross-Platform Identity & Provisioning (Week 7-8)

Bring all three platforms together with unified SCIM provisioning, cross-platform access reviews, and drift detection. This phase demonstrates the "identity and access layer everything else depends on" from the JD.

| Timeline | Task | Details & Interview Talking Points |
|----------|------|------------------------------------|
| Day 1-3 | Unified SCIM Provisioning Pipeline | Build a single Python provisioning engine that takes an Auth0 user event (create/update/delete) and fans out to GWS (Directory API), Slack (SCIM API), and AWS (IAM Identity Center). Handle attribute mapping, conflict resolution, and retry logic. This is the "automation against SaaS APIs to automate provisioning and catch drift" the JD describes. |
| Day 4-6 | Cross-Platform Access Review | Write a Python script that pulls user entitlements from all three platforms (Auth0 roles, GWS OU + groups + app grants, Slack channels + user groups) and generates a unified access certification report. Flag discrepancies: users with Auth0 roles that don't match their GWS OU, Slack users not in expected channels, orphaned accounts. Maps to Headspace quarterly access reviews. |
| Day 7-9 | Drift Detection & Remediation | Build a scheduled job that compares desired state (defined in config-as-code) against actual state across Auth0, GWS, and Slack. Detect configuration drift: OU membership changes, unexpected group additions, unauthorized app installs, role modifications. Generate drift reports and optionally auto-remediate. "Catch drift" — the JD's exact phrase. |
| Day 10-12 | SSO & SCIM Attribute Mapping Deep Dive | Document every SAML assertion attribute and SCIM mapping across all SSO connections. Build a test harness that validates attribute flow end-to-end: change an Auth0 `user_metadata` field → verify it propagates to GWS user attributes and Slack profile fields. Create an attribute mapping reference doc. |
| Day 13-14 | End-to-End Lifecycle Testing | Run full cross-platform lifecycle test: Joiner (Auth0 user created → GWS account in correct OU → Slack user in correct channels) → Mover (department change → GWS OU transfer → Slack group update → Auth0 role reassignment) → Leaver (Auth0 block → GWS suspend → Slack deactivate → token revocation across all platforms). Document with screenshots and architecture diagrams. |

**Interview framing:** "I built a unified provisioning pipeline that fans out identity events from Auth0 into Google Workspace and Slack via their respective APIs, with cross-platform drift detection that catches when actual state diverges from desired state. This is the same access review and compliance work I did at Headspace for SOC 2 — but across the full collaboration stack, not just the IdP."

---

## Phase 5: Config-as-Code, AI Operations & Interview Portfolio (Week 9-10)

Capstone phase. Unify all platform configuration into a single deployable codebase, add Claude MCP integrations, and build your interview demo portfolio.

| Timeline | Task | Details & Interview Talking Points |
|----------|------|------------------------------------|
| Day 1-3 | Unified Config-as-Code Repository | Organize all platform configuration scripts into a deployable structure: `config/auth0/`, `config/gws/`, `config/slack/`, `config/aws/`. Add CI/CD pipeline (GitHub Actions) that validates config on PR, applies on merge. Version-controlled, auditable, repeatable — the JD's "platform configuration as code." |
| Day 4-6 | Claude MCP: SaaS Platform Intelligence | Build Claude Code agents and skills that leverage MCP to: analyze Auth0 logs for anomalous access patterns, audit GWS third-party app risk, review Slack app permissions, generate cross-platform security posture reports, suggest least-privilege changes. Demonstrates "AI-assisted IT operations." |
| Day 7-9 | Vendor Escalation Runbooks | Write detailed runbooks for common escalation scenarios: GWS SAML federation debugging, Slack SCIM sync failures, Auth0 token revocation edge cases, cross-platform provisioning failures. Include diagnostic scripts, API calls, and resolution steps. "Final escalation tier" framing for interviews. |
| Day 10-12 | Interview Demo Portfolio | Create architecture diagrams for all systems. Prepare 2-3 minute walkthroughs for each phase tied to JD requirements. Build a live demo flow: provision a new user → watch them appear in GWS + Slack + Auth0 → transfer departments → watch access shift → offboard → verify revocation everywhere. |
| Day 13-14 | Documentation & Polish | Push all code to GitHub. Write clear README docs. Record short video walkthroughs. Prepare answers for: "Tell me about a time you went beyond the admin console," "How would you design data governance for a scaling company," "Walk me through your SCIM provisioning architecture." |

**Interview framing:** "I built a complete enterprise SaaS platform engineering lab — Auth0 as the IdP federating into Google Workspace and Slack, with Python-based SCIM provisioning, cross-platform drift detection, config-as-code with CI/CD, and AI-powered security auditing via Claude MCP. Every piece is code I wrote against SaaS APIs, not console clicks."

---

## Platform Reference

| Platform | Cost | Used In | What You Get |
|----------|------|---------|-------------|
| Auth0 (by Okta) | Free (permanent) | Phase 1-5 | Management API, Actions, Log Streams, SAML/OIDC, RBAC, Organizations, 25k MAU |
| Google Cloud Identity Free | Free (permanent) | Phase 1-5 | Admin Console, Admin SDK, Directory API, OU management, group policies. Domain: `your-domain.com` |
| Slack Developer Sandbox | Free (6 months, renewable) | Phase 1-5 | Enterprise workspace, Admin API, SCIM API, App Management API, up to 8 users |
| AWS Free Tier | Free (12 months) | Phase 1, 4-5 | IAM Identity Center, Lambda, DynamoDB, Secrets Manager (deemphasized — "cloud infrastructure lives with separate teams") |
| GitHub Actions | Free (2,000 min/month) | Phase 5 | CI/CD for config-as-code pipelines |
| Claude MCP | Claude Pro subscription | Phase 1-5 | Connect Claude to Auth0, GWS, Slack, AWS for AI-assisted SaaS operations |

---

## JD Requirements → Sandbox Mapping

| JD Requirement | Sandbox Deliverable | Phase |
|---|---|---|
| "Own tenant-wide architecture for Google Workspace, Slack" | GWS OU architecture + Slack workspace topology, both config-as-code | 2, 3 |
| "Design compartmentalization and data-governance models" | Per-OU sharing policies, DLP rules, cross-platform data governance | 2 |
| "Build integrations and automation against SaaS APIs" | Python scripts against Admin SDK, Slack Admin API, Auth0 Management API | 2, 3, 4 |
| "Configure the application side of SSO connections and SCIM" | Auth0 → GWS SAML, Auth0 → Slack OIDC, SCIM provisioning pipelines | 1, 3, 4 |
| "Final escalation tier for platform issues" | Vendor escalation runbooks with diagnostic scripts | 5 |
| "Partner with Corporate Security on SaaS hardening" | Third-party app governance, app risk audits, security posture reports | 2, 3 |
| "Own platform configuration as code" | Full config-as-code repo with CI/CD pipeline | 2, 3, 5 |
| "Python against SaaS APIs where the admin console stops" | Every automation in this project is Python against APIs, not console clicks | All |
| "Catch drift" | Cross-platform drift detection engine comparing desired vs. actual state | 4 |
| "8+ years building secure IT systems" | Resume (Headspace, Buffett AI, PeerStreet) + this sandbox portfolio | All |

---

## Resume → Sandbox Mapping (Updated for Target Role)

| Resume Experience | Sandbox Equivalent | JD Alignment |
|---|---|---|
| Okta SCIM/SAML/SSO integrations, zero-touch JML workflows (Headspace) | Auth0 SAML federation to GWS + Slack, SCIM provisioning pipeline | "SSO connections and SCIM attribute mappings from the application side" |
| HIPAA-compliant PHI access controls, least-privilege (Headspace) | GWS data governance, per-OU sharing policies, DLP rules | "Data-governance models that scale with the company" |
| Quarterly access reviews, SOC 2 Type II readiness (Headspace) | Cross-platform access review, unified entitlement report | "Partner with Corporate Security on compliance controls" |
| Google Workspace admin with exception groups (Headspace) | GWS OU architecture, third-party app governance, Admin SDK automation | "Deep, hands-on experience with Google Workspace administration" |
| LLM-powered Slack chatbot with LangChain RAG (Headspace) | Slack bot for JML notifications + access review commands | "Slack administration and APIs" |
| CI/CD pipelines, Terraform, branch-based promotion (Buffett AI) | Config-as-code CI/CD pipeline for GWS + Slack + Auth0 | "Platform configuration as code — auditable, repeatable, version-controlled" |
| Least-privilege IAM across 48 resources (Buffett AI) | Auth0 RBAC scoping, cross-platform least-privilege enforcement | "Security and compliance frameworks" |
| Okta SSO/SAML/SCIM at PeerStreet | Auth0 → GWS + Slack SSO federation, SCIM attribute mapping | "Identity protocols (SAML, OAuth, OIDC, SCIM)" |
| Okta Certified Professional | Auth0 ↔ Okta fluency, identity protocol depth | Demonstrates protocol understanding beyond vendor-specific knowledge |

---

## Auth0 ↔ Okta ↔ Google ↔ Slack Concept Mapping

| Concept | Okta (Resume) | Auth0 (Sandbox) | Google Workspace | Slack |
|---|---|---|---|---|
| User Store | Universal Directory | user_metadata + app_metadata | Directory / Cloud Identity | Member list + profile fields |
| Groups / Structure | Groups + Group Rules | Roles + Organizations | OUs + Google Groups | User Groups + Channels |
| Automation | Workflows (visual) | Actions (Node.js code) | Admin SDK (Python) | Admin API + Bolt SDK |
| Provisioning | SCIM to connected apps | Management API + webhooks | Directory API + GAM | SCIM API |
| SSO Federation | SAML/OIDC app integrations | SAML/OIDC connections | SAML SSO profiles | SAML/OIDC SSO |
| App Governance | App Integration policies | Client Grants | Third-party app access | App Management API |
| Audit/Logs | System Log + Event Hooks | Logs + Log Streams | Audit Log + Reports API | Audit Logs API |
| Config-as-Code | Terraform Provider | Terraform Provider | Python Admin SDK scripts | Python Admin API scripts |
| Data Governance | N/A | N/A | Drive sharing policies, DLP | Channel posting rules, DLP |

---

## Phase Status Tracker

| Phase | Weeks | Focus | Status |
|-------|-------|-------|--------|
| 1. Foundation & Platform Setup | 1-2 | Auth0 + GWS + Slack + SSO federation | In Progress (Auth0 done, GWS + Slack pending) |
| 2. Google Workspace Architecture | 3-4 | OUs, Directory API, data governance, app governance, config-as-code | Not Started |
| 3. Slack Platform Engineering | 5-6 | Admin API, SCIM, channel governance, app governance, config-as-code | Not Started |
| 4. Cross-Platform Identity & Provisioning | 7-8 | Unified SCIM, access reviews, drift detection, attribute mapping | Not Started |
| 5. Config-as-Code, AI Ops & Portfolio | 9-10 | Unified config repo, Claude MCP, runbooks, interview demos | Not Started |
