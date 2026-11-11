# Changelog

All notable changes to CodeAtlas will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
from v0.1.0 onward. Pre-1.0 releases may make breaking changes to the
index format (`.codeatlas/index.json`, currently version 1) and to the
internal Python APIs; the CLI commands and the read-only tool surface
in `codeatlas/tools.py` are intended to stay stable.

## [Unreleased]

<!-- Add new entries here, under the relevant heading. Keep entries
     user-visible: what changed, not how it was implemented. -->

### Added

- **`.codeatlas/config.json` is now read back** (`indexer.load_config`):
  the ignore list, the language filter, and the default context
  budget (`context_budget_tokens`) take effect on every index and
  `context` run. Missing, corrupt, or invalid entries fall back to
  the built-in defaults, per key. `.git` and `.codeatlas` are always
  ignored regardless of the config.
- **JS/TS parser coverage**: return-type-annotated arrow functions
  and methods, getters, interfaces, type aliases, enums, `const x =
  function …` expressions, single-identifier arrow params, and
  module-level `UPPER_SNAKE_CASE` consts (mirroring the Python
  rule) are now extracted as symbols.
- **Security hardening in the indexer**: the walk never follows
  symlinks, and index records whose paths would escape the repo
  root are rejected on load and on read, so a crafted
  `.codeatlas/index.json` cannot make the reader open files outside
  the repository.

### Changed

- **Test suite: 25 → 160 tests.** Every documented CLI command is
  now exercised verbatim by the suite, and the retrieval eval
  (17 cases) is re-measured below.
- **Retrieval eval** (`python3 tests/retrieval_eval.py`, 17 cases):
  mean search precision 0.337, mean search recall 1.000, hit@1
  0.824; mean context-pack precision 0.320, mean pack recall 1.000;
  **empty-text snippets in TS context packs: 12 → 0** (the JS
  line-number fix). Precision is unchanged and still low by design
  of the strict single-file relevance metric (see the eval module
  docstring).

### Fixed

- **JS/TS definition lines are now exact.** The regexes used
  `^\s*`, and `\s` matches newlines, so any definition preceded by
  blank line(s) was reported at the first preceding blank line --
  which also leaked the definition site as a self-call and made
  context packs read a blank line as the symbol snippet. The
  patterns now use `[ \t]` at line starts. The tests that pinned
  the wrong lines now assert the true lines.
- **README/indexer no longer claim git status drives indexing.**
  Change detection is SHA-256 only; the dead `_git_changed_files`
  helper is removed. Git is used only by the diff view.
- **Documentation audit**: fixed the `ask` example output in
  `docs/getting-started.md` (real output is `(106) charge` with
  3 callers, not `(100) billing.charge` with 1), the search
  docstring (six signals, not five), the read-only tool name
  (`build_context_pack_tool`), the "no CI workflow" claim in
  `CONTRIBUTING.md` (CI exists), the JS/TS gap lists (re-export
  imports *are* extracted; JSX components *are* found as plain
  functions/classes), and the stale "25 tests" counts everywhere.

## [0.1.0] — 2026-11-11

The initial release: a Python standard-library reference implementation
of the CodeAtlas blueprint (section 1), verified by a 134-test suite
at publication. Python 3.10+, no third-party dependencies, no network calls, no account,
no API key. The index lives in `.codeatlas/` inside the indexed repo.

### Added

- **CLI** (`python -m codeatlas`, or `codeatlas` after `pip install -e .`;
  entry point `codeatlas = "codeatlas.__main__:main"` in `pyproject.toml`):
  `init`, `index` (`--force` to re-parse every file), `map`
  (`--format mermaid|dot|json`, default `mermaid`), `ask`
  (`--limit`, default 10), `context` (`--budget`, default 4000 tokens;
  `--json` for machine-readable output), and `diff` (`--ref` to diff
  against a git ref, `--files` to name changed files explicitly).
  `codeatlas --version` prints `codeatlas 0.1.0`.
- **Incremental indexer** (`codeatlas/indexer.py`): walks the repo,
  skips configured ignore directories (`.git`, `.codeatlas`,
  `__pycache__`, `node_modules`, `.venv`, `dist`, `build`, `target`,
  and others), and re-parses only files whose SHA-256 hash changed
  since the last index; unchanged files are skipped even if their
  mtime moved, and deleted files are removed from the index. The
  index is persisted as plain JSON in `.codeatlas/index.json`
  (format version 1) and `init` writes `.codeatlas/config.json`.
- **Language-aware parsing** (`codeatlas/parsers.py`): Python via the
  real `ast` module (functions, methods, classes, module-level
  constants, imports, call references, docstrings, exact line
  numbers); JavaScript/TypeScript (`.js`, `.jsx`, `.ts`, `.tsx`,
  `.mjs`, `.cjs`) via targeted regex extraction (functions, arrow
  functions, classes, methods, `import`/`require`/re-export imports,
  call references). A file that fails to parse is recorded with
  `parse_error` and empty symbols instead of crashing indexing.
- **Repository graph** (`codeatlas/graph.py`): file → file import
  edges with resolution to files inside the repo, reverse dependents,
  symbol lookup by name and qualified name, callers of a symbol, and
  test-file linking (by import edges and by name, e.g.
  `tests/test_auth.py` → `auth.py`). Modules are top-level
  directories (a root-level file is its own module, named after the
  file stem).
- **Hybrid search** (`codeatlas/search.py`): exact symbol lookup,
  symbol substring and token match, full-text search over file lines,
  file-path ranking, and graph relevance (dependents/callers), with a
  small stemmer (so `authentication` matches `authenticate`) and
  stopword removal for natural-language questions. Every result
  carries `reasons` explaining why it ranked where it did.
- **Context packs** (`codeatlas/context.py`): bounded, explainable
  snippet sets for a task description, with exact file paths and
  line ranges and a `why` on every snippet. Token budgets are
  strictly enforced (tokens approximated as characters / 4); a
  snippet that would exceed the remaining budget is truncated at a
  line boundary, and the pack reports tokens used and bytes.
- **Architecture map** (`codeatlas/archmap.py`): module boundaries
  and dependency edges rendered as Mermaid, Graphviz DOT, or JSON —
  the same data in three views.
- **Git-aware change view** (`codeatlas/archmap.py`, `codeatlas diff`):
  given changed files (from `git status` / `git diff <ref>`, or an
  explicit `--files` list), reports the changed files, the affected
  modules, the affected files (the changed files plus everything
  that transitively depends on them), and the affected tests. It
  deliberately does *not* flag the modules a changed file imports.
- **Read-only tools** (`codeatlas/tools.py`): plain-function
  equivalents of the blueprint's MCP tools — `search_code`,
  `get_symbol`, `get_file_outline`, `build_context_pack_tool`,
  plus `get_architecture_map` and `get_change_impact` — as the
  stable contract a future MCP adapter, HTTP API, or editor
  extension will call. Nothing in them writes, executes, or
  uploads code.
- **Demo and fixtures**: `python demo.py` indexes the bundled
  fixture repos (`fixtures/sample-py`, `fixtures/sample-js`) and
  answers the blueprint's question — "If I change the billing
  interface, what code and tests are likely affected?" — with a
  Mermaid map, a search, a diff-impact view, and a context pack.
- **Documentation**: `README.md` (quickstart, honest status),
  `ARCHITECTURE.md` (module map, data flow, parser gaps, production
  path), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`,
  and `docs/` (architecture and getting-started tutorial).

### Known limitations in 0.1.0

- **No Rust core, no Tree-sitter, no Tantivy, no SQLite.** This is a
  Python reference implementation; the production stack is documented
  in `ARCHITECTURE.md`.
- **No semantic/embedding search.** Ranking is deterministic signals
  only.
- **No MCP server, VS Code extension, or HTTP API.**
- **No real tokenizer.** Token budgets use the documented
  approximation of 4 characters per token.
- **JS/TS parsing is approximate.** Regex extraction misses dynamic
  imports, re-exports, destructured methods, and JSX components.
- **In-memory index + JSON on disk.** No persistence beyond
  `.codeatlas/index.json`; huge monorepos have not been benchmarked.

<!-- Release links intentionally omitted: the project has not been
     published to GitHub yet (see pyproject.toml). Add the real
     repository compare/release URLs here on first publication. -->
