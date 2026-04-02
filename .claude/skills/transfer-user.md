---
name: transfer-user
description: "Transfer a user to a new department. Usage: /transfer-user <email> <new_department> [new_role_title]"
user_invocable: true
---

# Transfer User Skill

The user wants to transfer an employee to a different department (Mover workflow).

## Parse Arguments
- `email` (required) — the user's Auth0 email
- `new_department` (required) — must be one of: Engineering, IT-Ops, Finance, Executive, Data, Product, Design, HR, Sales, Marketing
- `new_role_title` (optional) — new job title; if omitted, keep existing

## Steps

1. **Look up the user** via Auth0 MCP or Management API by email
2. **Record current state** (department, roles, app_metadata) for audit
3. **Remove old Auth0 roles** associated with previous department
4. **Update user_metadata**:
   - `department` → new department
   - `role_title` → new title (if provided)
   - `cost_center` → new department cost center
   - `transfer_date` → today's ISO date
   - `previous_department` → old department
5. **Assign new Auth0 roles** based on new department mapping
6. **Update app_metadata** with new entitlements:
   - `aws_permission_set` → based on new department
   - `github_team` → based on new department
   - `jira_role` → based on new department
7. **Output** a summary:
   ```
   Transferred: {name} ({email})
   From: {old_department} → To: {new_department}
   Roles Removed: {old_roles}
   Roles Assigned: {new_roles}
   AWS Permission Set: {old} → {new}
   ```

## Important
- This is a sensitive operation — always show the before/after state
- Warn if transferring TO or FROM IT-Ops/Executive (privilege escalation/de-escalation)
