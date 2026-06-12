---
active: true
iteration: 1
session_id: 14dd62ba-aa0f-4455-bd77-71816376ec0e
max_iterations: 15
completion_promise: "ALL TASKS COMPLETE"
started_at: "2026-06-12T01:07:48Z"
---

Read PROMPT.md and follow it. Each iteration: find the first task in prd.md
  with "passes": false, execute it via the CLAUDE.md subagent workflow (planner -> code-developer ->
  code-reviewer -> unit-tester), mark it "passes": true only when the reviewer approves and tests
  pass, then append a dated line to activity.md. When EVERY task in prd.md is "passes": true, output
  <promise>ALL TASKS COMPLETE</promise>.
