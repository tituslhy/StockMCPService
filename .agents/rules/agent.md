---
trigger: always_on
---

# Agent System Rules & Governance

## Terminal Execution Guardrails
- **Pre-load Routine**: Before initializing any terminal task loop, you are pre-authorized to silently execute `source .venv/bin/activate`. 
- **Binary Targeting**: To prevent environment leaks, always call Python tools directly using the relative local path (`./.venv/bin/python`, `./.venv/bin/pytest`, `./.venv/bin/ruff`) instead of running naked global strings (`python`, `pytest`).

## Technology Stack Context
- This repository uses **FastMCP** and **PrefabUI** for building reactive, UI-driven Model Context Protocol apps.
- Always consult the official schemas via `fastmcp discover` or the [FastMCP Docs CLI tool](https://gofastmcp.com) to verify code compliance before writing handlers.

## Code Quality & Static Analysis
Activate the virtual environment, then run and pass the following quality verification checks from the root directory before declaring any coding task complete:

1. **Imports Sorting (`isort`)**:
   - Ensure imports are cleanly separated and grouped.
   - **Command**: Run `isort .` to automatically arrange imports across the workspace.

2. **Linting & Formatting (`ruff`)**:
   - Use `ruff` for ultra-fast codebase linting and style validation.
   - **Linter Command**: Run `ruff check --fix .` to catch errors and apply automatic corrections.
   - **Formatter Command**: Run `ruff format .` to maintain uniform code style layouts.

3. **Static Type Checking (`mypy`)**:
   - Strictly enforce type hints across all Python functions and handlers to catch type mutations.
   - **Command**: Run `mypy --ignore-missing-imports .` to execute the type safety evaluation pass.

## Testing Requirements
- **Location**: Every new or modified function MUST have a corresponding unit test file located inside the `tests/` directory.
- **Coverage**: Project threshold requires at least **90% test coverage**.
- **Verification Command**: Run `pytest --cov=src tests/` to explicitly verify your coverage metrics before declaring a task finished.

## Documentation Standards
- **Style Guide**: Strictly follow standard Python PEP 8 layout formatting.
- **Docstrings**: Include Google-style docstrings for every class, function, and endpoint handler.
- **Inline Comments**: Avoid redundant, self-explanatory comments. Only comment on highly nested logical loops or unexpected data mutations.