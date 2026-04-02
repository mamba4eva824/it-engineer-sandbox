---
name: bulk-provision
description: "Bulk provision users from the mock user data. Usage: /bulk-provision [count] — defaults to all 100 users"
user_invocable: true
---

# Bulk Provision Skill

The user wants to bulk-create users in the Auth0 tenant from the NovaTech mock user dataset.

## Parse Arguments
- `count` (optional) — number of users to provision; defaults to all remaining unprovisioned users

## Steps

1. **Load the user dataset** from `scripts/auth0/novatech_users.json`
2. **Check existing Auth0 users** to avoid duplicates (match by email)
3. **For each new user**, execute the onboarding workflow:
   - Create user with Auth0 Management API
   - Set user_metadata and app_metadata
   - Assign appropriate Auth0 role
4. **Respect rate limits**: Batch in groups of 10 with 1-second delays between batches
5. **Track progress**: Report after each batch completes
6. **Output final summary**:
   ```
   BULK PROVISIONING COMPLETE
   Total Attempted: {count}
   Successfully Created: {count}
   Skipped (already exists): {count}
   Failed: {count}

   By Department:
   - Engineering: {count}
   - IT-Ops: {count}
   - Finance: {count}
   ...
   ```

## Important
- If Auth0 MCP tools are available, use them directly
- If not, generate and run a Python script using `auth0-python`
- Always check for existing users first to make this operation idempotent
- The Auth0 free tier supports 25,000 MAU — 100 users is well within limits
- M2M token budget: ~100 API calls for 100 users (well within 1,000/month limit)
