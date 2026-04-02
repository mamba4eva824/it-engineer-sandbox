---
description: "Final verification, commit, and PR creation workflow"
---

# Ship — Final Verification & PR Creation

Prepare the current work for shipping. Follow these steps in order.

## Step 1: Final Gate Check

Run `/verify` to confirm all sandbox gates pass. If any gate fails, fix the issue before proceeding. Do NOT ship with failing gates.

## Step 2: Change Summary

Run the following in parallel:
- `git diff --stat` and `git log --oneline` for the current branch vs main
- Review all changed files for sensitive data (.env values, client secrets, ARNs that should be gitignored)

Produce a summary:
- List all modified/created/deleted files
- Summarize the purpose of each change
- Flag any sensitive data that should NOT be committed
- Note which phase/task this work relates to

## Step 3: Commit

Stage and commit all changes with a descriptive commit message. Ask the user for approval of the commit message before committing.

Commit message format:
```
phase-N: <short description>

<details of what was done>
- Auth0: <changes>
- AWS: <changes>
- Scripts: <changes>

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

## Step 4: Create PR

Create a pull request using `gh pr create` with:
- A concise title (under 70 characters)
- Body with Summary (bullet points), Phase reference, Test Plan, and interview talking points

## Step 5: Report

Share the PR URL with the user.
