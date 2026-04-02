---
name: session-report
description: "Generate an interview-ready report from logged activity. Usage: /session-report [today|week|all]"
user_invocable: true
---

# Session Report Skill

Generate an interview preparation report from the activity logs captured by Claude Code hooks.

## Parse Arguments
- `scope` (optional) — `today` (default), `week`, or `all`

## Steps

1. **Read the log files**:
   - `logs/activity.jsonl` — all tool calls (Auth0 MCP, Bash commands)
   - `logs/sessions.jsonl` — session start/end times

2. **Filter by scope**:
   - `today`: entries from today only
   - `week`: entries from the last 7 days
   - `all`: all entries

3. **Analyze and categorize** activity into IT operations domains:
   - **Identity & Access Management**: Auth0 user creation, role assignments, access reviews
   - **Lifecycle Automation**: Onboarding, transfers, offboarding operations
   - **Infrastructure**: AWS CLI commands, Terraform operations
   - **Security**: MFA configuration, log analysis, policy audits
   - **Compliance**: Access reviews, audit reports, policy changes

4. **Generate the report** in this format:

   ```
   IT OPERATIONS LAB — SESSION REPORT
   Date: {date range}
   Sessions: {count}

   ACTIVITY SUMMARY
   ─────────────────
   Total Operations: {count}
   Auth0 MCP Calls: {count}
   Infrastructure Commands: {count}
   Failed Operations: {count}

   BY DOMAIN
   ─────────────────
   Identity & Access: {list of notable operations}
   Lifecycle Automation: {list of notable operations}
   Infrastructure: {list of notable operations}
   Security: {list of notable operations}

   INTERVIEW TALKING POINTS
   ─────────────────
   Based on today's work, here are key points you can discuss:

   1. {Talking point tied to specific operations performed}
   2. {Talking point with Auth0 ↔ Okta translation}
   3. {Talking point connecting to resume experience}

   SKILLS DEMONSTRATED
   ─────────────────
   - {Skill 1}: {Evidence from activity}
   - {Skill 2}: {Evidence from activity}

   PHASE PROGRESS
   ─────────────────
   Current Phase: {phase from it_ops_lab.md}
   Tasks Completed: {relevant tasks}
   Next Steps: {upcoming tasks}
   ```

5. **Save the report** to `docs/reports/session-report-{YYYY-MM-DD}.md`

## Interview Framing
Read `docs/Senior IT Engineer Resume .md` for Christopher's exact resume. Map every technical action to:
- The equivalent Okta terminology (from the Auth0 ↔ Okta mapping in it_ops_lab.md)
- A specific resume bullet point — use the exact mapping from CLAUDE.md's "Resume Reference" section
- A compliance framework reference where applicable (SOC 2, HIPAA, NIST)

### Resume → Sandbox Quick Reference
- **JML workflows** → "At Headspace, I engineered zero-touch Joiner/Mover/Leaver workflows with attribute-mapping automations, cutting onboarding/offboarding time by 90%"
- **Access reviews** → "I partnered with Security to conduct quarterly access reviews and entitlement audits, supporting SOC 2 Type II readiness"
- **RBAC / least-privilege** → "I enforced HIPAA-compliant PHI access controls with least-privilege policies" (Headspace) + "Enforced least-privilege IAM across 48 resources" (Buffett AI)
- **MFA / zero-trust** → "Supported organization-wide rollout of Okta FastPass passwordless authentication"
- **Terraform / CI/CD** → "Built CI/CD pipelines with GitHub Actions + Terraform, branch-based promotion, commit-SHA-tagged deployments"
- **Endpoint management** → "Managed Jamf Pro configuration profiles for automated software deployment, OS patch management, and device compliance across 800 devices"
- **AI / LLM ops** → "Built LLM-powered Slack chatbot using LangChain RAG, Python, and Confluence APIs"
