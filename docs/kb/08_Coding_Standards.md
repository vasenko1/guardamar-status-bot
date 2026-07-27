# Coding Standards

## Style

- Target a supported modern Python version available in Termux.
- Follow PEP 8 and use type hints for public boundaries.
- Prefer clear, direct code over abstraction for its own sake.
- Keep functions and modules focused.
- Use comments to explain decisions, not restate code.

## Module boundaries

- Keep source collection separate from normalization.
- Keep domain records separate from transport-specific payloads.
- Keep digest selection and formatting separate from Telegram delivery.
- Keep the future feature isolated from Morning Digest internals.
- Put shared code in shared modules only when it has multiple real consumers.

## Naming

- Use descriptive `snake_case` for modules, functions, and variables.
- Use `PascalCase` for classes and typed domain records.
- Name adapters after the source or external system they represent.
- Avoid ambiguous names such as `data`, `utils`, or `manager` when a specific
  term exists.

## Error handling

- Set timeouts for network operations.
- Use bounded retries with backoff only for transient failures.
- Isolate source failures and preserve partial useful output.
- Log concise context without secrets or full sensitive payloads.
- Never silently convert unknown data into a valid-looking default.

## Dependencies and state

- Prefer the standard library when it remains clear and maintainable.
- Keep third-party dependencies few and pinned.
- Use `asyncio` for concurrent I/O; keep concurrency bounded.
- Prefer SQLite for small structured state and simple files for small static
  configuration.
- Keep state migrations simple, explicit, and recoverable.

## Tests

- Test normalization, prioritization, formatting, and failure behavior.
- Use small fixtures; do not require live network access for routine tests.

