# CodeAtlas architecture

This is the v0.1.0 reference implementation of the CodeAtlas blueprint
(`5-oss-projects-100k-stars-blueprint.md`, section 1). The blueprint's
production stack is Rust + Tree-sitter + Tantivy + SQLite; this repo is
a Python standard-library implementation of the same engine, with the
same module boundaries, so the port is mechanical and the behavior is
verifiable today.

## Module map

```text
codeatlas/
  __main__.py    CLI: init / index / map / ask / context / diff
  __init__.py    version
  indexer.py     file walk, SHA-256 hashing, incremental re-index,
                 .codeatlas/index.json persistence
  parsers.py     Python (ast) + JS/TS (regex) symbol/import/call extraction
  graph.py       import edges, reverse dependents, test links, modules
  search.py      hybrid search: symbol, text, path, graph + reasons
  context.py     bounded context packs (token budget enforced)
  archmap.py     architecture map (Mermaid/DOT/JSON) + diff impact
  tools.py       read-only tool surface (MCP contract, plain functions)
fixtures/        small Python + JS repos used by tests and the demo
tests/           189 tests, unittest, no network
```

## Data flow

```text
repo files --walk+hash--> indexer --parse--> ParsedFile (symbols/imports/calls)
                                                        |
                                              Graph.build (edges)
                                                        |
                       +--------------------------------+------------------+
                       |                                |                  |
                 hybrid search                   context packer     architecture map
              (symbol/text/path/graph)         (budgeted snippets)  (Mermaid/DOT/JSON)
                       |                                |
                 read-only tools (tools.py) <------------+
                       |
                 CLI / future MCP adapter / future HTTP API
```

## Key design decisions

1. **Incremental by content hash, not mtime.** A file is re-parsed only
   when its SHA-256 changes. Git status is used only by the diff view,
   not by indexing, so the indexer is correct on non-git trees too.
2. **Deterministic ranking, no embeddings.** Every search result and
   context snippet carries a `why`. Semantic search is an explicit
   future add-on, disabled by default, per the blueprint.
3. **Tokens approximated as chars/4.** Documented in `context.py`. A
   real tokenizer plugs in behind `estimate_tokens` without changing
   callers.
4. **Diff impact walks dependents, not dependencies.** Changing a caller
   does not change the code it calls, so a change flags the changed
   files, their transitive dependents, and the tests covering those --
   never the upstream modules. (This was a real bug found by the test
   suite during development.)
5. **Read-only tools are plain functions.** `tools.py` is the contract
   an MCP adapter, HTTP API, or editor extension calls. Nothing in it
   writes, executes, or uploads code.

## What the parsers do and do not understand

| Language | Method | Understood | Known gaps |
|---|---|---|---|
| Python | `ast` | functions, methods, classes, constants, imports, calls, docstrings, exact lines | dynamic imports (`importlib`), decorators' runtime effects |
| JavaScript / TypeScript | regex | function/class/method defs (incl. return-annotated arrows and methods, getters, `export default function`, generics, class-field arrows, `#private`/computed methods), interfaces, type aliases, enums, module-level constants, `import`/`require`, calls, exact lines for real code (comments/strings/templates stripped first) | dynamic imports, destructured methods, parameter lists nested more than three levels, methods in minified single-line class bodies, calls inside template interpolations, regex-literal heuristic, JSX syntax |

Parser failures never crash indexing: a file that fails to parse is
recorded with `parse_error` and its symbols are empty, and the index
stats report the count.

## Production path (from the blueprint, not built here)

- **Rust core** (Tokio, `petgraph`, Tantivy, SQLite via SQLx) for the
  performance-sensitive work: file walking, parsing orchestration,
  graph ops, query serving.
- **Tree-sitter grammars** replacing `parsers.py` behind the same
  `ParsedFile` shape (symbols / imports / calls with line numbers).
- **Axum localhost API** + TypeScript MCP adapter calling `tools.py`'s
  contract; VS Code extension on top.
- **Benchmark corpus** and public performance reports; monorepo,
  generated-folder, symlink, and partial-parse-failure tests.

## Testing

`python -m unittest discover -s tests` -- 189 tests, all offline.
Fixtures live in `fixtures/` and are copied to temp dirs per test, so
tests never touch the real repo. Coverage includes: incremental
re-indexing (only changed files), symbol search with line numbers,
budget enforcement, real import edges in the map, diff impact listing
the affected test, parser edge cases, and the CLI end to end.
