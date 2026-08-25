# license_reclaim_orchestrator

Lambda `ohmgym-license-reclaim-orchestrator`. Plans a License Reclamation ticket with GPT-5.6 Luna via the OpenAI API (`gpt-5.6-luna`, key in Secrets Manager `ohmgym-licenses/openai`), intersects the plan with hard-deny policy, then POSTs the existing reclaim broker Function URL. It never holds SaaS write credentials.

CLI: `python scripts/licenses/orchestrate.py --issue SUP-n --dry-run|--apply`

```bash
bash lambdas/license_reclaim_orchestrator/build.sh
python -m pytest lambdas/license_reclaim_orchestrator/tests -v
```

EventBridge `license.scan.complete` no-ops when `ORCHESTRATOR_AUTO_RUN` is false. CLI invokes always run. Fixture ticket `SUP-2` is refused.
