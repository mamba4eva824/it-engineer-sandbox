---
description: "Start Ralph Wiggum loop in current session"
argument-hint: "PROMPT [--max-iterations N] [--completion-promise TEXT]"
hide-from-slash-command-tool: "true"
---

# Ralph Loop Command

Start an iterative development loop. The same prompt is fed to Claude repeatedly — Claude sees its own previous work in files and git history, building incrementally toward the goal.

**Usage:**
```
/ralph-loop "Configure adaptive MFA with risk-based step-up" --max-iterations 10
/ralph-loop "Provision all departments to AWS Identity Store" --completion-promise "ALL PROVISIONED"
```

**How it works:**
1. Creates `.claude/.ralph-loop.local.md` state file
2. You work on the task
3. When you try to exit, stop hook intercepts
4. Same prompt fed back
5. You see your previous work in files
6. Continues until promise detected or max iterations

**CRITICAL RULE:** If a completion promise is set, you may ONLY output it when the statement is completely and unequivocally TRUE. Do not output false promises to escape the loop.
