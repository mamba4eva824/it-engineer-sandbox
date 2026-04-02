---
name: onboard-user
description: "Onboard a new user to the NovaTech Auth0 tenant. Usage: /onboard-user <first> <last> <department> [role_title]"
user_invocable: true
---

# Onboard User Skill

The user wants to onboard a new employee to the NovaTech Solutions Auth0 tenant.

## Parse Arguments
Extract from the user's input:
- `first_name` (required)
- `last_name` (required)
- `department` (required) — must be one of: Engineering, IT-Ops, Finance, Executive, Data, Product, Design, HR, Sales, Marketing
- `role_title` (optional, defaults to department-appropriate title)

## Steps

1. **Generate user details**:
   - Email: `{first_name}.{last_name}@novatech.io` (lowercase)
   - Password: Generate a secure random password (20 chars, mixed case, numbers, symbols)
   - Map department to Auth0 role and AWS permission set

2. **Create via Auth0 MCP** (preferred) or generate a Python script:
   - Create user with email, name, password, and `email_verified: true`
   - Set `user_metadata`: department, role_title, cost_center, start_date (today)
   - Set `app_metadata`: aws_permission_set, github_team, jira_role
   - Assign the appropriate Auth0 role

3. **Output** a summary:
   ```
   Onboarded: {name}
   Email: {email}
   Department: {department}
   Auth0 Role: {role}
   AWS Permission Set: {permission_set}
   ```

## Department → Role Mapping
| Department | Auth0 Role | AWS Permission Set | Cost Center |
|-----------|-----------|-------------------|-------------|
| Engineering | engineer | PowerUser | ENG-100 |
| IT-Ops | it-admin | Admin | IT-200 |
| Finance | finance | ReadOnly | FIN-300 |
| Executive | executive | ReadOnly | EXEC-400 |
| Data | data-engineer | PowerUser | DATA-500 |
| Product | product | ReadOnly | PROD-600 |
| Design | designer | ReadOnly | DES-700 |
| HR | hr | ReadOnly | HR-800 |
| Sales | sales | ReadOnly | SALES-900 |
| Marketing | marketing | ReadOnly | MKT-1000 |
