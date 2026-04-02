---
name: access-review
description: "Run an access review across Auth0 users. Usage: /access-review [department] — omit department to review all users"
user_invocable: true
---

# Access Review Skill

The user wants to run an access review / audit of user permissions in the NovaTech Auth0 tenant.

## Parse Arguments
- `department` (optional) — filter to a specific department. If omitted, review all users.

## Steps

1. **Pull all users** from Auth0 (via MCP or Management API), filtered by department if specified
2. **For each user**, collect:
   - Name, email, department (from user_metadata)
   - Assigned Auth0 roles
   - App metadata (aws_permission_set, github_team, jira_role)
   - Account status (active/blocked)
   - Last login date
3. **Analyze for anomalies**:
   - Users with roles that don't match their department mapping
   - Blocked users that still have active role assignments
   - Users missing required metadata fields
   - Users who haven't logged in for 30+ days (stale accounts)
   - Users with admin/it-admin roles (privileged access review)
4. **Generate report**:

   ```
   ACCESS REVIEW REPORT — NovaTech Solutions
   Date: {today}
   Scope: {department or "All Departments"}

   Total Users: {count}
   Active: {count} | Blocked: {count}

   FINDINGS:
   - {finding 1}
   - {finding 2}

   PRIVILEGED ACCESS:
   - {admin users list}

   RECOMMENDATIONS:
   - {recommendation 1}
   ```

## Interview Value
This skill demonstrates:
- Access certification workflows (SOC 2 CC6.1, CC6.3)
- Least-privilege enforcement
- Automated compliance reporting
- Orphaned account detection
