# CodeAtlas — local-first codebase intelligence

> A fast, private, cross-language codebase map that helps a human or AI
> coding assistant understand a repository before editing it.

```bash
codeatlas init
codeatlas index
codeatlas map
codeatlas ask "Where is authentication handled?"
codeatlas context "Add rate limiting to the public API"
```

No account. No API key. No uploads. The index lives in `.codeatlas/`
inside your repo, and CodeAtlas never sends your code anywhere.

## What it does

- **Incremental indexer** — re-indexes only files whose SHA-256
  hash changed (Git status is used only by the diff view, not by
  indexing, so it works on non-git trees too).
- **Language-aware parsing** — Python via the real `ast` module;
  JavaScript/TypeScript via targeted regex extraction (functions,
  return-annotated arrows and methods, getters, classes, interfaces,
  type aliases, enums, module-level constants, imports, `require`,
  call references). Tree-sitter grammars are the production path
  (see Architecture).
- **Repository graph** — files, symbols, imports, call edges, and test
  links, with module boundaries and reverse dependencies.
- **Hybrid search** — exact symbol lookup, full-text search, path
  ranking, and graph relevance, with a `why` on every result.
- **Context packs** — bounded, token-budgeted snippets with exact file
  paths and line ranges for a task description.
- **Architecture map** — module boundaries and dependency edges as
  Mermaid, DOT, or JSON.
- **Git-aware change view** — given a diff, which modules and tests are
  likely affected.
- **Read-only tools** — `search_code`, `get_symbol`, `get_file_outline`,
  `build_context_pack_tool` as plain functions, ready for an MCP adapter.

## Quickstart

```bash
python -m codeatlas init            # create .codeatlas/config.json
python -m codeatlas index           # index the current repo
python -m codeatlas map              # architecture map (Mermaid)
python -m codeatlas map --format dot
python -m codeatlas ask "charge"     # hybrid search
python -m codeatlas context "Add rate limiting to the public API" --budget 400
python -m codeatlas diff --files billing.py
```

Or run the demo (indexes the bundled fixture repos, no setup):

```bash
python demo.py
python -m unittest discover -s tests
```

Python 3.10+, standard library only. No dependencies, no network calls.

## The demo that should make developers share it

```text
$ python demo.py
== 2. architecture map (Mermaid) ==
flowchart LR
    api --> auth
    api --> billing
    billing --> auth
    tests --> auth
    tests --> billing

== 4. diff impact: if I change the billing interface ==
Changed files:
  - billing.py
Affected modules:
  - api
  - billing
  - tests
Affected files:
  - api.py
  - billing.py
  - tests/test_billing.py
Affected tests:
  - tests/test_billing.py
```

## Honest status (v0.1.0)

What genuinely works, verified by the test suite (`160 tests, OK`):

- Incremental re-indexing (only changed files re-parsed, verified).
- Python parsing via `ast` (functions, methods, classes, constants,
  imports, call references, exact line numbers).
- JS/TS parsing via regex (functions, return-annotated arrows and
  methods, getters, classes, interfaces, type aliases, enums,
  module-level constants, imports, `require`, call references, exact
  line numbers).
- `.codeatlas/config.json` is read back: the ignore list, the
  language filter, and the default context budget are honoured
  (invalid entries fall back to the built-in defaults).
- Import-edge resolution, reverse dependents, test-file linking.
- Hybrid search with explainable ranking and callers for every symbol.
- Context packs that strictly enforce their token budget.
- Architecture maps (Mermaid / DOT / JSON) and diff impact views.

What it does **not** do yet (stated plainly, not hidden):

- **No Rust core, no Tree-sitter, no Tantivy, no SQLite.** This is a
  Python reference implementation of the blueprint's engine. The
  production stack (Rust + Tree-sitter + Tantivy + SQLite) is documented
  in `ARCHITECTURE.md` and this package mirrors the blueprint's module
  boundaries so the port is mechanical.
- **No semantic/embedding search.** Ranking is deterministic signals
  only. Semantic search is an optional, disabled-by-default add-on in
  the blueprint, not a prerequisite.
- **No MCP server, VS Code extension, or HTTP API.** The read-only tool
  functions in `codeatlas/tools.py` are the stable contract those
  adapters will call.
- **No real tokenizer.** Token budgets use the documented approximation
  of 4 characters per token.
- **JS/TS parsing is approximate.** Regex extraction misses dynamic
  imports, destructured methods, and parameter lists with nested
  parentheses. Re-export *imports* (`export … from`) are extracted,
  but re-exported names are not symbols; JSX is not parsed (a
  component is found only as a plain function/class). It degrades
  gracefully (partial results, never a crash) and the gaps are
  listed in `ARCHITECTURE.md`.
- **In-memory index + JSON on disk.** No persistence beyond
  `.codeatlas/index.json`; huge monorepos have not been benchmarked.

## Privacy

Local-only by design. CodeAtlas reads the files you point it at, writes
an index inside that repo, and makes no network requests at all. There
is no telemetry, no account, and no code path that uploads source.

## License

MIT. See `LICENSE`.
