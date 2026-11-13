# CodeAtlas architecture (v0.1.0)

This document describes the architecture **as actually implemented**
in this repository. The root [`ARCHITECTURE.md`](../ARCHITECTURE.md)
is a short summary; this is the detailed version. Anything described
here as a future or production step is labelled as such — it is not
built yet.

## Status in one paragraph

v0.1.0 is a **Python standard-library reference implementation** of
the CodeAtlas blueprint (section 1). The blueprint's production stack
is Rust + Tree-sitter + Tantivy + SQLite; this repo implements the
same engine and the same module boundaries in Python, so the behaviour
is verifiable today and the port is mechanical. Python 3.10+, no
third-party dependencies, no network calls, no account, no API key.
The test suite is 189 `unittest` tests, all offline.

## Module map

```text
codeatlas/
  __main__.py    CLI: init / index / map / ask / context / diff
  __init__.py    version (0.1.0)
  indexer.py     file walk, SHA-256 hashing, incremental re-index,
                 .codeatlas/index.json persistence
  parsers.py     Python (ast) + JS/TS (regex) symbol/import/call extraction
  graph.py       import edges, reverse dependents, test links, modules
  search.py      hybrid search: symbol, text, path, graph + reasons
  context.py     bounded context packs (token budget enforced)
  archmap.py     architecture map (Mermaid/DOT/JSON) + diff impact
  tools.py       read-only tool surface (the MCP contract, plain functions)
fixtures/        small Python + JS repos used by tests and demo.py
tests/           189 tests, unittest, no network
```

## Data flow

```text
repo files --walk + SHA-256--> indexer --parse--> ParsedFile
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

The shared data shapes are plain dataclasses with `to_dict()` /
`from_dict()` round-trips, because the whole index is persisted as
JSON (see "Persistence" below). Every field must be JSON-serialisable.

## The indexer (`indexer.py`)

`index_repo(root, force=False) -> (Index, IndexStats)` is the entry
point; `init_repo(root)` only writes `.codeatlas/config.json`.

### Walk

`_iter_source_files` walks the repo with `os.walk`, pruning any
directory in `DEFAULT_IGNORES` (`.git`, `.codeatlas`, `__pycache__`,
`node_modules`, `.venv`, `venv`, `.tox`, `.mypy_cache`,
`.pytest_cache`, `dist`, `build`, `.eggs`, `target`, `.idea`,
`.vscode`) or starting with `.`, and yields only files whose
extension is recognised by `parsers.language_for_path`.

### Incremental re-indexing

Change detection is by **content hash, not mtime**:

1. Read the file bytes, compute SHA-256.
2. If `force` is false and a previous record exists with the same
   SHA-256, skip re-parsing (only the stored `mtime` is updated) and
   count the file as `unchanged`.
3. Otherwise decode as UTF-8 (falling back to `errors="replace"`),
   parse it, store a `FileRecord(path, language, sha256, mtime, size,
   parsed)`, and count it as `indexed`. A parse failure increments
   `parse_errors` but does not stop indexing.
4. Files present in the old index but no longer on disk are deleted
   from the index and counted as `removed`.

`IndexStats` therefore reports exactly `indexed` / `unchanged` /
`removed` / `parse_errors` for the run. The test suite pins this:
indexing `fixtures/sample-py` parses 5 files the first time, 0 the
second time, and exactly 1 after appending a comment to one file.

Change detection is by SHA-256 only. Git status is used only by the
diff view (see "Diff impact" below), never by indexing.

### Persistence

`Index.save()` writes `.codeatlas/index.json`:

```json
{"version": 1, "root": "<absolute path>", "files": {"<rel path>": {…}}}
```

`Index.load()` returns an empty index if the file is missing,
unparseable, or has a `version` other than `INDEX_VERSION` (1).
Individual corrupt file records are skipped, not fatal. Each
`FileRecord` stores the parsed file (`ParsedFile.to_dict()`), so
loading an index never re-parses source.

`Index` also provides `total_symbols`, `total_imports`,
`all_symbols()`, `find_symbol(name)` (exact match on `name` or
`qualified_name`), and `read_lines(rel_path, start, end)` — a 1-based
inclusive line slice read from disk, used by context packs.

### Configuration

`init_repo` writes `.codeatlas/config.json` with `version`,
`languages: ["python", "javascript", "typescript"]`, the sorted
ignore list, `context_budget_tokens: 4000`, and a `privacy` note.
**That file is read back on every index** by `load_config` in
`indexer.py`: the ignore list, the language list, and the default
context budget all take effect. Missing, corrupt, or invalid entries
fall back to the built-in defaults, per key (an invalid
`context_budget_tokens` does not discard a valid `languages` list,
and unknown language names are dropped). Two directories are always
ignored no matter what the config says: `.git` and `.codeatlas`
(the index must never index itself). The walk also never follows
symlinks, and index records whose paths would escape the repo root
are rejected on load and on read, so a crafted `index.json` cannot
make the reader open files outside the repository.

## The parsers (`parsers.py`)

### Shared shape

```python
@dataclass
class ParsedFile:
    path: str
    language: str
    symbols: list[Symbol] = ...   # definitions, exact line numbers
    imports: list[Import] = ...   # module names the file depends on
    calls: list[Call] = ...       # (caller, callee, line) triples
    parse_error: str | None = None

@dataclass
class Symbol:
    name: str; kind: str          # function | method | class | variable |
                                  # constant | interface | type | enum
    line: int; end_line: int      # 1-based
    qualified_name: str = ""      # e.g. Authenticator.authenticate
    signature: str = ""
    docstring: str = ""

@dataclass
class Import:
    module: str; names: list[str] = ...
    line: int = 0; level: int = 0  # 0 = absolute, >0 = relative (dots)

@dataclass
class Call:
    caller: str                   # qualified name, "" for module level
    callee: str; line: int
```

Dispatch is `language_for_path(path)` (extension lookup in
`SUPPORTED_EXTENSIONS`: `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`,
`.cjs`) followed by `parse_file(path, source)`, which returns
`ParsedFile(path, language="unknown")` for an unsupported extension,
`_parse_python` for Python, and `_parse_javascript` for JS/TS.
See [CONTRIBUTING.md](../CONTRIBUTING.md) for how to add a language
behind this same interface.

### Python — real `ast` parsing

`_PythonVisitor(ast.NodeVisitor)` records classes (with base-class
signatures), functions and async functions (kind `method` when the
enclosing scope is a class, otherwise `function`), imports
(`import x` and `from x import …`, with `level`), and calls
(`ast.Name` and dotted `ast.Attribute` callees, with the current
scope as caller). Module-level `UPPERCASE` assignments are added
afterwards as `constant` symbols. Docstrings are captured via
`ast.get_docstring`. `line`/`end_line` come from the AST nodes, so
they are exact. On `SyntaxError`, the file gets
`parse_error = "SyntaxError line <n>: <msg>"` and empty symbols.
Parsing uses `ast.parse` only — indexed code is never imported or
executed.

### JavaScript / TypeScript — regex approximation

`_parse_javascript` first runs the source through
`_strip_js_comments_and_strings`, which replaces comments, string
literals, template literals and regex literals with spaces while
preserving newlines — so code-like text inside a template literal or
a block comment can never be indexed as a real symbol, and calls
inside comments, strings and template literals are never recorded.
Import module names are recovered from the original source at the
match spans (the quotes survive the pass; only their contents are
blanked). The regexes then extract `import` (including `import
type`), `require(…)`, `export … from …`, `function` declarations
(including `export default function` and generics), `const name =
(…) =>` arrow functions (including return-type annotations,
single-identifier params, and `<T>` type parameters), `const name =
function …` expressions, `class` declarations, `interface` / `type` /
`enum` declarations, module-level `UPPER_SNAKE_CASE` consts,
indented `name(…) {` method lines (including return-type
annotations, getters, generics, `#private` and computed
`['name']`/`[Symbol.iterator]` methods), and class-field arrow
functions (`handler = (e) => {}` — accepted only inside a class
body) — all filtered against a keyword set. Line numbers are exact
for real code: the patterns use `[ \t]` at line starts, never `\s`
(which matches newlines and used to mis-report definitions after
blank lines), and definitions may also start mid-line after a `;`
or `{` boundary, so minified single-line code is parsed. Calls are
every `name(` occurrence that is not a definition site, with the
caller attributed to the nearest preceding function/method/class
symbol — best-effort, not scope-accurate. Interfaces, type aliases,
enums, and constants are not call scopes. `end_line` is set to the
definition line for every JS/TS symbol: there is no real end line,
because there is no syntax tree.

Known gaps (also in the root `ARCHITECTURE.md`): dynamic imports,
destructured methods, parameter lists with parentheses nested more
than three levels deep, methods inside a minified single-line class
body, calls inside template-literal interpolations (`${...}` is
blanked along with the literal, so they are not tracked), a `/`
treated as a regex literal only by heuristic, and JSX syntax
(components are found only as plain functions/classes). Re-export
*imports* (`export … from`) are extracted, but re-exported names
are not symbols. The parser degrades gracefully — partial results,
never a crash — and those gaps are part of the contract, not bugs
to paper over.

## The graph (`graph.py`)

`Graph.build(index)` computes, once per loaded index:

- `import_edges`: file → set of files it imports, via
  `_resolve_import`. Resolution rules, in order: relative imports
  (`./billing` → `billing.js/.ts/.jsx/.tsx`, `…/index.js/.ts`,
  `….py`, `…/__init__.py`); Python-style dotted modules
  (`pkg.mod` → `pkg/mod.py`, `pkg/__init__.py`, trying longest
  prefix first); same-directory fallback (`billing` imported from
  `api.py` in the same folder → `billing.py`). Bare specifiers with
  a path that are not relative (e.g. `lodash/fp`) and anything that
  matches no file in the repo resolve to `None` — external
  dependencies produce no edge.
- `dependents`: the reverse of `import_edges`.
- `symbols_by_name`: keyed by both `name` and `qualified_name`.
- `test_links`: test file → source file(s) under test, from (1)
  direct import edges out of the test file to non-test files, and
  (2) name matching — the test filename with `test_`, `_test`, or
  `.test` stripped must equal a source file's stem
  (`test_auth.py` / `auth.test.js` → `auth.py` / `auth.js`).

Queries:

- `dependents_of(path)` / `dependencies_of(path)`: transitive
  closure over reverse / forward edges.
- `tests_for(path)`: test files directly linked to the path, plus
  any test file among its transitive dependents.
- `callers_of(symbol_name)`: `(file, caller, line)` triples whose
  callee equals the name or ends with its last dotted segment.
  Matching is by name string, not by resolved symbol identity —
  two same-named functions in different files both count.

### Modules

`module_of(rel_path)` defines the architecture-map boundary: the
top-level directory of the file, except that for `src/`, `lib/`,
`app/`, `packages/`, and `pkg/` the *second* component is the module
(`src/auth.py` → `auth`), and a file at the repo root is its own
module named after the file stem (`billing.py` → `billing`).
`is_test_file` recognises `test_*.py`, `*_test.py`, `*.test.*`,
and paths under `test/` or `tests/`.

## Hybrid search (`search.py`)

`search(index, graph, query, limit=10) -> list[SearchResult]`
combines six signals, in priority order, and every result carries
`reasons` (a list of strings) explaining its score. There is no
embedding model; ranking is deterministic.

1. **Exact symbol lookup** — `name` or `qualified_name` equals the
   query (case-insensitive): score `100 + min(20, 2 × callers)`,
   reason `"exact symbol match"` plus `"<n> caller(s) in the repo"`
   when there are callers.
2. **Symbol substring** — query contained in the symbol name:
   score `60`.
3. **Symbol token match** — all content tokens of the query appear
   in the identifier's tokens (camelCase/snake_case split, stemmed):
   score `55`.
4. **Full-text** — for each file, lines whose content tokens overlap
   the query's content tokens score `5 × overlap` per line (at most
   3 line hits per file), and the file itself scores
   `min(30, 5 × total_overlap)`.
5. **Path ranking** — `25 × overlap` when query tokens appear in the
   file path.
6. **Graph relevance** — a file result's score is boosted by
   `min(20, 2 × dependents)`, with reason `"imported by <n> file(s)"`.

Results with the same `(kind, path, line)` are merged, keeping the
highest score and the union of reasons, then sorted by
`(-score, path, line)` and truncated to `limit`.

Query processing: `tokenize` extracts `[A-Za-z_][A-Za-z0-9_]*`
tokens; `content_tokens` lowercases, removes a fixed stopword set
(`the`, `where`, `is`, …), and applies a tiny suffix stemmer
(`stem`: `-ation` → strip 5, `-ing`/`-ate` → strip 3, `-ies` → `y`,
trailing `-es`/`-e`/`-s` stripped with guards). That is why the
natural-language question "Where is authentication handled?"
reduces to `{authentic, handl}` and finds `auth.py`. The stemmer is
deliberately small and documented as such — a production search
would use a real stemmer or embeddings.

`SearchResult` fields: `kind` (`symbol | text | file`), `path`,
`line` (0 for file-level results), `name`, `score`, `snippet`
(signature, or the matching line truncated to 160 chars), `reasons`.

## Context packs (`context.py`)

`build_context_pack(index, graph, task, budget_tokens=4000)
-> ContextPack` assembles a bounded, explainable set of snippets.

Candidates are ranked, then added in order until the budget is
exhausted:

- **One candidate per matching symbol** — the symbol's definition
  body (`read_lines(sym.line, sym.end_line)`), scored
  `10 × token_overlap + min(10, dependents)`, where overlap is
  between the task's content tokens and the symbol name tokens plus
  its docstring tokens. `why` names the symbol, the overlap count,
  and the file's dependent count.
- **One candidate per top text hit** — a single line from hybrid
  search (limit 20), scored `5.0`, with the matching text in `why`.

Duplicate `(path, start_line, end_line)` candidates are dropped.
Budget enforcement is strict: if a snippet would exceed the
remaining budget, it is truncated to `remaining × 4` characters and
cut back to the previous line boundary, with `"(truncated to fit
budget)"` appended to its `why`; if nothing fits, it is skipped.
`ContextPack.tokens` is the sum of snippet tokens and never exceeds
`budget_tokens` — the test suite pins this at budgets of 400, 100,
and 10 tokens.

Tokens are approximated as `max(1, len(text) // 4)` — 4 characters
per token (`CHARS_PER_TOKEN = 4`, `estimate_tokens` in `context.py`).
This is documented, not hidden: the pack reports both its token
estimate and its byte size. A real tokenizer plugs in behind
`estimate_tokens` without changing callers.

## Architecture map and diff impact (`archmap.py`)

`build_architecture_map(index, graph)` groups files into modules
(`module_of`) and derives module edges from the import graph,
dropping intra-module edges. Each `ModuleEdge` records the
`source → target` module pair and the file-level edges behind it.
Rendering is the same data in three views: `to_mermaid()`
(`flowchart LR`, `a --> b`, isolated modules listed bare),
`to_dot()` (`digraph codeatlas`, `rankdir="LR"`), and `to_json()`.

`diff_impact(index, graph, changed_files)` answers "what does this
change affect?":

- `changed_files`: only the given files that are actually in the
  index.
- `affected_files`: the changed files plus their **transitive
  dependents** — everything that imports them, directly or
  indirectly.
- `affected_tests`: tests covering any affected file
  (`Graph.tests_for`), plus any changed file that is itself a test.
- `affected_modules`: the modules of the affected files.

Dependencies — things the changed files import — are deliberately
**not** included: changing a caller does not change the code it
calls. (This was a real bug found by the test suite during
development; the tests pin that changing `billing.py` affects
`api.py` and `tests/test_billing.py` but not `tests/test_auth.py`,
and that changing `auth.py` reaches both test files.)

`git_changed_files(root, ref=None)` supplies the changed-file list
when the caller does not: with `ref`, `git diff --name-only <ref>`;
without, `git status --porcelain -uall` (working tree + staged).
It returns `None` when git is unavailable or the directory is not a
repo. Rename entries (`old -> new`) are resolved to the new path,
and results are de-duplicated and sorted. All git calls have a
30-second timeout and never go through a shell.

## Read-only tools (`tools.py`)

The MCP contract, as plain functions — the stable surface a future
MCP adapter, local HTTP API, or editor extension calls. Nothing in
this module writes, executes, or uploads code.

| Function | What it returns |
| -------- | --------------- |
| `search_code(index, graph, query, limit=10)` | Hybrid search results as dicts |
| `get_symbol(index, graph, name)` | Exact symbol lookup: definition, signature, docstring, and callers with file/line |
| `get_file_outline(index, rel_path)` | Symbols, imports, size, and `parse_error` for one file, or `None` |
| `build_context_pack_tool(index, graph, task, budget_tokens=4000)` | A context pack as a dict (note: the `…_tool` suffix distinguishes it from `context.build_context_pack`) |
| `get_architecture_map(index, graph, fmt="json")` | Map as JSON, Mermaid, or DOT |
| `get_change_impact(index, graph, changed_files=None, ref=None)` | Diff impact as a dict; when git is unavailable and no files are given, an empty impact with a `note` |

## CLI (`__main__.py`)

`python -m codeatlas <command> [path] [options]`, or `codeatlas`
after `pip install -e .`. Commands: `init`, `index` (`--force`),
`map` (`--format mermaid|dot|json`), `ask` (`--limit`, default 10),
`context` (`--budget`, default from `.codeatlas/config.json`
`context_budget_tokens`, or 4000 when there is no config; `--json`),
`diff` (`--ref`, `--files …`). `map`, `ask`, `context`, and `diff`
load `.codeatlas/index.json` and fail with exit code 1 and
`"no index found -- run \`codeatlas index\` first"` when there is
nothing indexed; `diff` additionally fails when the target is not a
git repo and no files were given.

## Testing

`python -m unittest discover -s tests` — 189 tests, all offline.
Fixtures are copied to temp dirs per test, so tests never touch the
real repo. Coverage includes incremental re-indexing (only changed
files re-parsed, deletions removed), symbol search with verified
line numbers, the canonical question "Where is authentication
handled?", budget enforcement at several sizes, real import edges
in the map, diff impact listing the affected test, parser edge cases
(including a syntax error recorded, not raised), and the CLI end to
end. Run `python demo.py` as a smoke check of the whole flow.

## Known gaps and divergences

Honest list, so contributors do not "fix" the wrong thing:

1. **No Rust core, no Tree-sitter, no Tantivy, no SQLite, no HTTP
   API, no MCP server, no VS Code extension.** The blueprint's
   production stack is documented in the root `ARCHITECTURE.md`
   under "Production path". The `tools.py` functions are the
   contract those adapters will call.
2. **No real tokenizer** — token budgets are `chars / 4`.
3. **JS/TS parsing is regex-based and approximate** — see the gaps
   listed under "JavaScript / TypeScript" above; `end_line` is the
   definition line, not a real end line. Line numbers are exact for
   real code, with the documented exceptions (template-literal
   interpolations are not tracked; regex literals are detected by
   heuristic).
4. **In-memory index + JSON on disk** — no database; huge monorepos
   have not been benchmarked.
5. **No semantic/embedding search** — ranking is deterministic
   signals only, by design.

Two former divergences were fixed on 2026-11-11 and are no longer
gaps: indexing is SHA-256 only (the old README/`indexer.py` claim
that it prefers `git status` was wrong; the dead helper is removed),
and `.codeatlas/config.json` is now read back (ignore list, language
filter, default context budget).
