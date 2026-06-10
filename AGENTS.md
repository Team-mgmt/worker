# AGENTS.md

Run lint and type check (`uv run -m ruff check worker/` and `uv run -m mypy worker/`) before committing.

## Dependencies

Use `uv add <package>` (or `uv add --group <group> <package>` for dev/test groups) to manage dependencies. Do not edit pyproject.toml directly for adding packages.

## Schema parsing

Use **pydantic** for all first-class schema parsing — anything that mirrors a zod schema on the shelfalign-web side, validates external JSON payloads (DB JSONB columns, API request bodies, S3 metadata blobs), or enforces structural invariants on untrusted input. Define a `BaseModel` subclass with explicit field types and let pydantic's `ValidationError` drive the "fall back / reject" branch; do not hand-roll `isinstance`/`if`-tree validators when a model would express the same intent.

- Use `StrictFloat`/`StrictInt`/`StrictBool` (or `ConfigDict(strict=True)`) when the source schema (e.g. zod's `z.number()`) rejects type coercion.
- For "all-or-nothing" semantics (zod `safeParse`), catch `ValidationError` at the call site and return the empty fallback — pydantic's whole-payload validation already matches this shape.
- Reject `bool` explicitly with a `mode="before"` field validator when the field is typed as a number: Python treats `bool` as a subclass of `int`, so strict numeric fields can still accept `True`/`False` unless guarded.

## Code committing

- Use conventional commit messages. For example: `feat: add new agent for data processing`.
- Run lint and type check before committing. Use `uv run -m ruff check worker/` for linting and `uv run -m mypy worker/` for type checking.
- Ensure that your code is well-documented and follows the project's coding standards.
- If your changes include new features or bug fixes, make sure to update the relevant documentation and add tests if necessary.
- Always pull the latest changes from the main branch before starting your work to avoid merge conflicts.