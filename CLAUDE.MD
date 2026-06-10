# Stock MCP Service

## What this is
A FastMCP service providing stock market tools and prefab UI dashboards.
See `prd.md` for the full spec and task list.

## Stack
- Python 3.13, FastMCP, yfinance, pandas, numpy, ta, prefab UI
- `main.py` — server entry point
- `tools/` — one file per MCP tool
- `ui/` — prefab UI app definitions

## Rules
- Type hints everywhere
- Never hardcode tickers or dates
- Validate inputs before calling yfinance
- Ask before deleting files or installing new dependencies

## Skills
- `.claude/skills/stock-data-viz/SKILL.md` — read before writing ANY chart or dashboard code
- `.claude/skills/skill-creator/SKILL.md` — read when creating or improving agent/skill definitions

## How to work

**Always use subagents. Never implement in this context.**

For every task in `prd.md`:
1. Spawn **planner** — task description + relevant context → returns spec + file manifest
2. Spawn **code-developer** — spec only → returns implemented files
3. Spawn **code-reviewer** — implemented files → returns findings
4. If findings are non-trivial, spawn **code-developer** again with the diff
5. Spawn **unit-tester** — implemented files → returns test results
6. Mark task `"passes": true` in `prd.md` only when reviewer approves and tests pass
7. Log completion in `activity.md`

Do not paste implementation, specs, or test output into this context.
Return one-line summaries only.