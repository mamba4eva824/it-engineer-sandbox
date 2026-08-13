# Phase 1 — JSM Foundation

Short log of License Reclamation intake on Jira Service Management. Roadmap: [16-license-reclamation-human-in-the-loop-roadmap.md](../16-license-reclamation-human-in-the-loop-roadmap.md). Field IDs: `config/jira/field-mapping.json`.

**Site:** [buffett-dev.atlassian.net](https://buffett-dev.atlassian.net) · **Project:** Support (`SUP`) · **Sample:** [SUP-2](https://buffett-dev.atlassian.net/browse/SUP-2)

## What shipped

- Reused existing JSM project `SUP` (no `ITSD` project on this site).
- Request type **License Reclamation** (id `4`), hidden from the customer portal.
- Five agent fields: Leaver email, Okta user ID, Offboarding run ID, Apps requiring action, Hold / exception notes.
- Agent queue **License Reclamation** (`Request Type` = License Reclamation, unresolved).
- Allowlist stub: `config/licenses/apps.json`.
- MCP `getJiraIssue` returns the structured reclaim fields on SUP-2.
- Scoped Jira API token in the gitignored project `.env` (P1-R4): `JIRA_BASE_URL`, `JIRA_CLOUD_ID`, `JIRA_EMAIL`, `JIRA_API_TOKEN`. Cursor MCP still does not need it; Phase 2 scanner Lambda does. Do not commit the token.

## Configuration challenges

**JSM Admin is UI-only.** Atlassian MCP cannot create request types, custom fields, or queues (ADR-007). Cursor’s browser hit the Atlassian login wall, so those steps were done by hand.

**Field type mismatch.** Roadmap called for Paragraph on apps/notes. Jira Admin created all five as **Short text**. Scanner should write a comma-separated app list (`github, figma`), not a rich-text table.

**Screen association.** After each custom field, Jira asks which screens to attach. Only **SUP: Jira Service Management Screen** — Default Screen would leak fields onto FEATURES/SCRUM.

**Request type cannot be set by name via REST.** `customfield_10010: "License Reclamation"` returns “Invalid customer request value”. Create the issue first, then set the numeric request-type id. On this site: `1` Submit a request, `2` Ask a question, `3` Emailed request, `4` License Reclamation.

**Queues are filters, not folders.** SUP-2 still appears under **All open** (whole Support project). Click **License Reclamation** in the sidebar. Top-bar **+ Create** opens a ticket; the **+** next to Queues creates the queue.

**Create-queue form defaults to all of Support.** The New queue JQL starts as `project = "Support"`. Without adding `"Request Type" = "License Reclamation"`, the queue looks like All open.

**`.env` is invisible in Git / this worktree.** It is gitignored and lives in the main checkout (`Documents/Projects/IT Operations Sandbox /.env`), not in the Cursor worktree. Copy or symlink it into the worktree root before running Phase 2 scripts here. Use **Create API token with scopes** (`read:jira-work`, `write:jira-work`); leave the existing Claude MCP token alone.

## IDs for Phase 2

| Field | ID |
|---|---|
| Request Type | `customfield_10010` (value `"4"`) |
| Leaver email | `customfield_10138` |
| Okta user ID | `customfield_10139` |
| Offboarding run ID | `customfield_10140` |
| Apps requiring action | `customfield_10141` |
| Hold / exception notes | `customfield_10142` |
