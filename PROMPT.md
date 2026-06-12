# Ralph Wiggum Loop — Stock MCP Service

You are running an autonomous development loop on the **Stock MCP Service**, a
FastMCP + prefab UI showcase. The full spec and task list live in `prd.md`.
Read `CLAUDE.md` for the architecture and the mandatory subagent workflow.

## Each iteration
1. Read `activity.md` to find the current state.
2. Open `prd.md` and find the **first** task with `"passes": false`.
3. Execute it via the subagent workflow (never implement in this context):
   - **planner** → spec + file manifest
   - **code-developer** → implementation (spec only)
   - **code-reviewer** → findings
   - **code-developer** again if findings are non-trivial
   - **unit-tester** → test results
4. Mark the task `"passes": true` in `prd.md` only when the reviewer approves and
   tests pass.
5. Append a dated one-line entry to `activity.md`.
6. Stop when every task is `"passes": true`.

Return one-line summaries only. Do not paste specs, code, or test output here.

## Project rules (from CLAUDE.md)
- Type hints everywhere. Validate inputs before calling yfinance.
- Never hardcode tickers or dates.
- Read `.claude/skills/stock-data-viz/SKILL.md` before writing ANY chart/dashboard code.
- Ask before deleting files or installing new dependencies.
- Simple read-only tools → `tools/<name>.py` with `@mcp.tool(app=True)`.
- Interactive apps → `ui/<name>.py` as `FastMCPApp`, mounted in `main.py`.

## Commands
- **Run the server:** `uv run fastmcp run main.py`
  (or `uv run python main.py`)
- **Install/sync deps:** `uv sync`
- **Run tests:** `uv run pytest`
- **Coverage:** `uv run coverage run -m pytest && uv run coverage report`
- **Lint:** `uv run ruff check .`
- **Format check:** `uv run ruff format --check .`
- **Type check:** `uv run mypy .`
- **Import sort:** `uv run isort --check-only .`

## Definition of done
All four features (price history, technical analysis, portfolio tracker, multi-ticker
compare) run and render correctly, with validated inputs, graceful yfinance failure
handling, polished visuals per the stock-data-viz skill, passing unit tests with
reasonable coverage, and clean ruff/mypy/isort.
