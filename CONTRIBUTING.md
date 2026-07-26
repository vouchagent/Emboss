# Contributing to Emboss

Thank you for your interest in contributing to Emboss. This document covers the conventions and processes to follow when working on this project.

## Getting Started

```bash
git clone https://github.com/GGChamp85/Emboss.git
cd Emboss
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
pytest
```

## Pre-commit Hooks

This project uses [pre-commit](https://pre-commit.com/) to enforce code quality before every commit. Once installed (`pre-commit install`), hooks run automatically on `git commit`. They include:

- **Ruff** lint + format
- **Mypy** type checking
- Trailing whitespace, YAML/TOML validation, large file guard, merge conflict detection, debug statement detection

To run all hooks manually against the full codebase:

```bash
pre-commit run --all-files
```

## Code Standards

### Style

- **Formatter/linter**: [Ruff](https://docs.astral.sh/ruff/) with a line length of 88 characters
- **Type hints**: All public functions must have type annotations. Run `mypy src/emboss/` to verify.
- **Python version**: Target Python 3.10+. Do not use features from 3.11+ without a fallback.

### Conventions

- **No comments by default.** Only add a comment when the *why* is non-obvious: a hidden constraint, a workaround for a specific bug, behavior that would surprise a reader. Do not explain *what* the code does.
- **No docstring essays.** Public functions get a one-line docstring. Internal functions need none unless the behavior is surprising.
- **Prefer editing over creating.** Extend existing modules rather than creating new files unless the feature is genuinely orthogonal.
- **No unnecessary abstractions.** Three similar lines are better than a premature helper function. Do not design for hypothetical future requirements.
- **Imports**: Use relative imports within the `emboss` package (`from .spec import Document`, not `from emboss.spec import Document`).

### Naming

- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions and variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private members: `_single_leading_underscore`

### Testing

- Every new feature must include tests.
- Tests go in `tests/test_<module>.py`.
- Run the full suite before submitting: `pytest`
- All tests must pass. No skipped tests without a documented reason.
- Use `@dataclass`-based fixtures, not elaborate setUp/tearDown.

```bash
# Run all tests
pytest

# Run a specific test file
pytest tests/test_emboss.py

# Run with verbose output
pytest -v

# Run tests matching a pattern
pytest -k "test_table"
```

### Commits

- Write concise commit messages that explain *why*, not *what*.
- One logical change per commit.
- Do not include `Co-Authored-By` lines.
- Do not reference competitor or external tool names in commit messages or filenames.

### Pull Requests

- Keep PRs focused. One feature or fix per PR.
- Include a summary of what changed and why.
- Add a test plan with steps to verify.
- Ensure all tests pass and linting is clean before requesting review.

## Architecture Principles

### Determinism

Output must be byte-identical across runs and machines. This means:
- No `datetime.now()`, `uuid4()`, or `random()` in the render pipeline
- No iteration over `dict` or `set` where order matters (use sorted or ordered collections)
- The PDF `/ID` is derived from content, not timestamps

### Measure Before Place

The layout engine follows a strict pipeline:
1. **Validate** - check constraints, auto-fix repairable issues
2. **Measure** - compute exact dimensions for every block using font metrics
3. **Paginate** - assign blocks to pages with widow/orphan control
4. **Render** - draw measured blocks at their assigned positions
5. **Tag** - build the PDF/UA structure tree from the same elements
6. **Assemble** - write byte-exact PDF output

Never skip a stage. Never place content without measuring it first.

### Accessibility Is Not Optional

Every content element must produce both visual output and a structure tree node. There is no "render without tags" mode. Decorative content (rules, watermarks, page numbers) must be marked as `/Artifact`.

### No External Service Dependencies

Emboss must work offline. No network calls during rendering. External dependencies are limited to `fonttools` (required) and optional extras (`pydantic`, `pikepdf`, `cryptography`).

## File Organization

```
src/emboss/
  spec.py               # Document data model - add new elements here
  writer.py             # Render pipeline - add drawing methods here
  styles.py             # Style presets - add new presets here
  layout/engine.py      # Measurement + pagination
  typography/            # Font metrics, line breaking, hyphenation
  pdf/                   # Low-level PDF assembly
  adapters/              # Export formats (HTML, Markdown, DOCX, Pydantic)
```

When adding a new block element:
1. Define the dataclass in `spec.py`
2. Add measurement logic in `layout/engine.py`
3. Add rendering logic in `writer.py`
4. Add structure tree tagging in the same render method
5. Update adapters (`html_export.py`, `markdown_export.py`, `pydantic_schema.py`)
6. Add to `__init__.py` exports
7. Write tests

## Reporting Issues

Open an issue on GitHub with:
- What you expected vs. what happened
- A minimal document spec that reproduces the problem
- The PDF output (if applicable)
- Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the Apache-2.0 License.
