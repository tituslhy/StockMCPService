---
name: docstring-skill
description: Writes docstrings for Python code.
---

## When to Use This
Every single time you write or edit a Python function or class. No exceptions. Not even for "obvious" functions.

## Format
Always use Google-style docstrings:

```python
def my_function(param1: str, param2: int = 10) -> pd.DataFrame:
    """Short one-line description of what this does.

    Longer explanation if needed. What does it return?
    What edge cases does it handle?

    Args:
        param1: Description of param1.
        param2: Description of param2. Defaults to 10.

    Returns:
        A DataFrame with columns: Date, Open, High, Low, Close.

    Raises:
        ValueError: If param1 is empty or ticker not found.
    """
```

## Rules
- First line: one sentence, verb-first ("Fetch", "Run", "Render", "Calculate")
- Always document every parameter — no skipping
- Always document the return value
- Always document exceptions that can be raised
- If a function calls another skill (fetch_data, run_ta, etc.) — mention it in the docstring body

## Never Do This
- Never write `# TODO: add docstring`
- Never write docstrings AFTER the code is done — write them first
- Never use reStructuredText (`:param:`, `:type:`) — Google style only