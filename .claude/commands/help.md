---
description: "Explain available commands and workflows for the IT Operations Sandbox"
---

# IT Operations Sandbox — Command Reference

## Planning & Execution Workflows

### /gsd — Get Stuff Done (Planning)
Run the full planning workflow before starting any new task:
1. **Audit** — Gather context from codebase and live Auth0/AWS/GWS/Slack environments
2. **Acceptance Criteria** — Define testable, interview-ready success conditions
3. **Implementation Plan** — Dashboard steps vs API/CLI steps, files to modify
4. **Task Graph** — Break into atomic tasks with dependencies
5. **Self-Critique** — Check for free tier limits, security issues, breaking changes
6. **User Approval** — Present plan and wait for confirmation

### /ralf — Review-Audit-Loop-Fix (Execution)
Execute the TodoWrite task list with a strict loop per task:
1. **Implement** — Dashboard instructions or API/CLI execution
2. **Verify** — Confirm state via Management API, AWS CLI, or log checks
3. **Review** — Check against acceptance criteria and existing functionality
4. **Learn** — Note failures as interview talking points
5. **Complete** — Mark done and move to next task

### /verify — Run All Sandbox Gates
Run verification checks across all connected systems:
- Auth0 connectivity and user count
- AWS connectivity and IAM Identity Center status
- Permission Sets and Actions deployment
- Python dependencies
- Google Workspace API connectivity (when configured)
- Slack API connectivity (when configured)

### /ship — Commit & PR
Final verification, commit, and pull request creation:
1. Run all gates
2. Summarize changes and check for sensitive data
3. Commit with phase-tagged message
4. Create PR with interview talking points

## Ralph Wiggum Technique

### /ralph-loop \<PROMPT\> [OPTIONS]
Start an iterative development loop where the same prompt is fed repeatedly. Claude sees its own previous work in files and git history, building incrementally.

Options:
- `--max-iterations <n>` — Max iterations before auto-stop
- `--completion-promise <text>` — Promise phrase to signal completion

### /cancel-ralph
Cancel an active Ralph loop.

## Project Context

- **Auth0 Tenant**: See AUTH0_DOMAIN in .env (100 NovaTech users, RBAC, SAML federation)
- **AWS Account**: See AWS_ACCOUNT_ID in .env (IAM Identity Center, 3 Permission Sets)
- **Google Workspace**: Cloud Identity Free (Phase 2+)
- **Slack**: Developer sandbox (Phase 3+)
- **Phase Roadmap**: See `it_ops_lab.md`
- **Session Reports**: `docs/reports/`
