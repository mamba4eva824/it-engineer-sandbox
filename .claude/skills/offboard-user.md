---
name: offboard-user
description: "Offboard a user from the NovaTech Auth0 tenant. Usage: /offboard-user <email>"
user_invocable: true
---

# Offboard User Skill

The user wants to offboard (deprovision) an employee from the NovaTech Solutions Auth0 tenant.

## Parse Arguments
- `email` (required) — the user's Auth0 email address

## Steps

1. **Look up the user** via Auth0 MCP or Management API by email
2. **Revoke all refresh tokens** for the user
3. **Remove all role assignments**
4. **Block the user account** (do NOT delete — retain for audit compliance)
5. **Update app_metadata**:
   - Set `deprovisioned: true`
   - Set `deprovisioned_date` to today's ISO date
   - Set `deprovisioned_by` to "claude-offboard-skill"
6. **Output** a summary:
   ```
   Offboarded: {name} ({email})
   Tokens Revoked: Yes
   Roles Removed: {list of removed roles}
   Account Status: Blocked
   Audit Record: Retained
   ```

## Important
- NEVER delete the user — blocking preserves the audit trail
- Always confirm with the user before executing if the user has admin/it-admin roles
- If the user is not found, report the error clearly
