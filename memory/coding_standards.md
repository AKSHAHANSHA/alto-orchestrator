# Coding standards

## Python

**Version**: 3.11. No PEP 695 generic syntax (`class Foo[T]:` — 3.12+). Use
classic `TypeVar` and `Generic`.

**Formatter and linter**: `ruff` (100-char lines, target `py311`). Rule set
is `E W F I N UP B C4 SIM RUF ANN TID`. Test files ignore `ANN`;
Arabic-heavy files ignore `RUF001/002/003` (which flag confusable Unicode).

**Type checker**: `mypy --strict`. Plugins: `pydantic.mypy`. Vendor SDKs
without stubs (`openai`, `anthropic`, `qdrant_client`, `fastembed`,
`langgraph`, `langchain_core`, `fitz`, `langdetect`) are marked
`ignore_missing_imports`.

**Naming**:
- `snake_case` for functions, methods, module names.
- `PascalCase` for classes, TypedDicts, enums, Pydantic models.
- `SCREAMING_SNAKE` for module-level constants.
- Private helpers prefixed `_`.
- Kebab-case file names in `data/knowledge/policies/` (e.g. `02-test-drive-procedure.md`).

**Type hints**: everywhere. Union with `|` (PEP 604). Optional as `T | None`.
Generic containers as `list[T]`, `dict[K, V]`, `tuple[T, ...]`.

**Pydantic**: v2 idioms. `BaseModel` for values crossing boundaries.
`ConfigDict(extra="forbid")` on domain value objects. `frozen=True` for
immutable values.

**Comments and docstrings**:
- Every module has a docstring stating its purpose *and* the reason it
  exists in the layer it does.
- Short comments where the *why* is non-obvious. No `# TODO` littering —
  either fix it or track it in `future_tasks.md`.
- Avoid comments that describe *what* the code does when the code says so.

**Error handling**:
- Domain errors are typed subclasses of `AltoError` in `core/errors.py`.
  Each has `status_code` and `code`; the API layer maps them to HTTP.
- `except Exception` is acceptable at genuine boundaries (adapter calls,
  external services) with `# noqa: BLE001` and a `logger.warning` — never
  a bare `except:`.
- Graceful degradation is preferred over hard failure for infrastructure:
  Qdrant down → `NullRetriever`; Postgres down → skip structured lookup
  and log a warning. The customer must never see an opaque 500.

**Async**:
- Everything I/O-bound is `async def`. FastAPI routes, DB access, LLM
  calls, embeddings (via `asyncio.to_thread` around FastEmbed's sync API).
- No sync `sleep()`; use `asyncio.sleep()`.
- Never call `asyncio.run()` inside a running loop.

**Dependency injection**:
- `composition/container.py` is the composition root. Nothing else builds
  the same graph of concrete adapters.
- Services take collaborators via `__init__`. Never a module-level
  singleton for a stateful client.

## TypeScript / React

**Version**: React 19, Next.js 15, TypeScript strict mode.

**Naming**:
- `PascalCase` for components and types.
- `camelCase` for variables, functions, hooks.
- `use` prefix for hooks.
- File names match component names for co-located files, kebab-case for
  route folders (`app/workflow/page.tsx`).

**Component style**:
- Function components only, no class components.
- `use client` at the top of any interactive component; server components
  by default for static pages.
- Props typed inline for one-off components, exported `interface Props` for
  shared components.

**Styling**:
- Tailwind utility classes. Custom design tokens live in
  `tailwind.config.ts`.
- Swiss/International style throughout: 12-column grid (`grid-field`),
  restrained colour, tabular numbers on data (`class="tabular"`).
- Two brand accents: **Karva amber** (`karva`) and **Renzo indigo**
  (`renzo`). One Swiss red (`signal`) for single-emphasis moments.
- Arabic text uses `dir="rtl"` and picks up the `font-arabic` stack
  automatically via the `[dir="rtl"]` selector in `globals.css`.

**API client**:
- `src/lib/api.ts` — hand-written types mirroring the backend DTOs. Not
  generated. When the backend changes, hand-edit both.
- Base URL from `NEXT_PUBLIC_API_BASE_URL` (read at build time — the
  frontend must be restarted after changing it).

## Testing

**Backend**: `pytest`, async by default (`asyncio_mode=auto`). Tests live
in `backend/tests/{unit,integration,e2e}/`.

- **Unit tests**: fast, no I/O, hit domain and pure services.
- **Integration tests**: real FastAPI app via `ASGITransport`, real DI
  container. Uses the mock or live provider depending on `.env`.
- Table-driven: `pytest.mark.parametrize` for language and normaliser cases.
- Architecture fitness: `tests/unit/test_architecture.py` asserts the
  dependency rule. Any violation fails the build.
- Regression tests are added for every real bug. Named for the scenario
  they pin (e.g. `test_answering_a_clarification_advances_the_conversation`).

**Frontend**: no test framework wired yet — planned as part of Module 14.

## File organisation

Prefer one class or one closely-related family of functions per file.
Split when a file exceeds ~500 lines or serves two responsibilities.

## Refactoring principles

- **The dependency rule is not optional.** If you find yourself wanting to
  import infrastructure from services, define a Protocol port instead.
- **Move to a repository pattern** when a service needs SQL — put the SQL
  in `infrastructure/persistence/`, keep a thin service in `services/`,
  connect via a Protocol.
- **Don't rewrite a whole file for a small change.** Use `Edit` with
  precise anchors.
- **When a real bug is found, write the regression test first** and land
  it with the fix. Both go in the same change.
