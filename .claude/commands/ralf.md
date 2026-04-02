---
description: "Run the RALF (Review-Audit-Loop-Fix) execution workflow on TodoWrite tasks"
---

# RALF (Review-Audit-Loop-Fix) — IT Operations Execution Workflow

You are entering the RALF execution phase. Execute the tasks in the TodoWrite list following this strict loop.

## Ground Rule
> "Done" is not a feeling. Done = acceptance criteria met + gates pass + live environment verified.

## Execution Loop

For each task in the TodoWrite list:

### 1. IMPLEMENT

- Mark task as `in_progress`
- Determine the implementation approach:
  - **Dashboard step**: Provide clear console instructions to the user, wait for confirmation
  - **API/CLI step**: Execute via Python SDK, AWS CLI, or Auth0 MCP server
  - **Action code**: Write and deploy Auth0 Actions via Management API
- If the task requires understanding unfamiliar Auth0/AWS APIs, research the SDK signatures first

### 2. VERIFY

Run the relevant verification for the completed task:
- **Auth0 changes**: Query the Management API to confirm state (users, roles, actions, clients)
- **AWS changes**: Use AWS CLI to confirm state (Permission Sets, Identity Store, IAM)
- **SAML/SSO changes**: Check Auth0 logs for successful auth events (`type=s`)
- **MFA changes**: Verify factor configuration via Guardian API
- **Script changes**: Run the script with `--dry-run` or limited scope first

If verification fails, diagnose the issue (check Auth0 logs, AWS errors) and fix before proceeding.

### 3. REVIEW

Check the completed task against:
- Does it satisfy the acceptance criteria?
- Does it break existing functionality (SAML federation, user provisioning)?
- Are there security issues (exposed secrets, over-permissioned access)?
- Does it follow project conventions (CLAUDE.md)?
- Is the local code copy in sync with the deployed state (Actions, configs)?

### 4. LEARN

- If a failure occurred, note the lesson (e.g., NameID format mismatch, missing M2M scopes)
- These lessons become interview talking points — note them for the session report

### 5. COMPLETE

- Mark task as `completed` in TodoWrite
- Move to next task

## Parallelism Rules

When multiple tasks have no dependencies and touch different systems (e.g., Auth0 vs AWS):
- Execute them in parallel using concurrent API calls
- Each still gets its own verification step

Otherwise, execute serially.

## Completion

When all tasks are done:
1. Run `/verify` to confirm all gates pass
2. Summarize what was accomplished with interview talking points
3. Ask if the user wants to `/ship` (commit + PR) or continue with the next phase task
