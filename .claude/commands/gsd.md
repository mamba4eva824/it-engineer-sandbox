---
description: "Run the GSD (Get Stuff Done) planning workflow — Audit, Plan, Tasks, Approval"
---

# GSD (Get Stuff Done) — IT Operations Planning Workflow

You are entering the GSD planning phase. Follow these steps strictly before any implementation begins.

## Step 1: Audit Snapshot

Gather context before planning. Spawn parallel agents:

- **Explore agent** (`subagent_type=Explore`): Explore the codebase for existing scripts, Auth0 Actions, AWS configurations, and Terraform modules related to the user's request. Identify what already exists and what needs to be built.
- **Explore agent** (second instance): Check the current state of Auth0 (users, roles, actions, clients) and AWS (IAM Identity Center, Permission Sets, Identity Store) via API calls to understand the live environment.

While agents are running, draft the audit:
- **Knowns / Evidence**: What's certain from the user's request, codebase, and live environment state
- **Unknowns / Gaps**: Missing info that could change decisions
- **Constraints**: Auth0 free tier limits (25k MAU, 1k M2M tokens/month), AWS Free Tier limits, existing SAML federation dependencies
- **Risks**: Top 3 things that could break existing functionality
- **Phase Context**: Which phase of the 10-week roadmap this work belongs to (see `it_ops_lab.md`)

When agents return, incorporate their findings into the audit.

## Step 2: Acceptance Criteria

Create acceptance criteria that are:
- **Observable**: Can be seen/measured (e.g., "user can SSO into AWS via Auth0")
- **Testable**: Has a pass/fail condition (e.g., "Auth0 logs show type=s for test user")
- **Interview-ready**: Each criterion maps to a resume talking point

Example:
```
AC-1: Given an IT-Ops user, when they SSO via Auth0 to AWS, then they receive the Admin Permission Set.
AC-2: Given a new device login, when adaptive MFA triggers, then the user is prompted for TOTP verification.
```

## Step 3: Implementation Plan

Consider the hybrid approach for this project:
- **Dashboard steps**: What needs manual console configuration (Auth0 or AWS)?
- **API/SDK steps**: What can be automated via Python SDK or AWS CLI?
- **Action code**: Any Auth0 Actions that need to be written?

Draft the plan:
- **Objective**: One sentence
- **Approach Summary**: One paragraph
- **Steps**: Numbered, minimal but complete
- **Files to Modify/Create**: Expected file changes in `scripts/`, `terraform/`, `docs/`
- **Verification**: How to test each step (API calls, SSO login tests, log checks)

## Step 4: Task Graph

Break the plan into atomic tasks using `TodoWrite`. Each task must have:
- Clear acceptance criteria
- Dependencies (what must complete first)
- Whether it's a Dashboard step or API/CLI step
- Verification method

## Step 5: Self-Critique

Before presenting to the user, ask yourself:
- Does this break the existing SAML federation?
- Will this exceed Auth0 free tier limits?
- Will this exceed AWS Free Tier limits?
- Are there sensitive values that need to stay out of git?
- Does this work support interview talking points?

If any concern is critical, revise the plan before presenting.

## Step 6: User Approval

**STOP and ask the user** before proceeding:
- Present the acceptance criteria, task list, and any concerns
- Ask for approval or adjustments
- Do NOT proceed until user confirms

When user approves, begin execution with `/ralf`.
