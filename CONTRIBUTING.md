# Contributing to CodeAtlas

Thank you for considering a contribution. CodeAtlas is a local-first
codebase-intelligence tool: it indexes a repository on the user's own
machine, builds a symbol/import graph, and answers questions about the
code — with no account, no API key, and no uploads. Contributions that
keep that promise — fast, explainable, private, and honest about their
limits — are welcome.

Please read the [Code of Conduct](CODE_OF_CONDUCT.md) before
contributing. By participating, you agree to follow it.

## What this project is (v0.1.0)

This is a **Python standard-library reference implementation** of the
CodeAtlas blueprint (section 1 of the project blueprint). The
blueprint's production stack is Rust + Tree-sitter + Tantivy + SQLite;
this repository implements the same engine and module boundaries in
Python so the behaviour is verifiable today. Do not assume the Rust
stack, a Tree-sitter parser, an HTTP API, an MCP server, or a VS Code
extension exists yet — none of those is in this repo (see
[README.md](README.md) "Honest status" and [ARCHITECTURE.md](ARCHITECTURE.md)).

The package layout is:

```text
codeatlas/
  __main__.py    CLI: init / index / map / ask / context / diff
  __init__.py    version (currently 0.1.0)
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

## Local setup

Requirements: **Python 3.10 or newer** (see `requires-python = ">=3.10"`
in `pyproject.toml`). No third-party dependencies: the package is
standard library only, so **no `pip install` of project dependencies
is needed and no network access is required** to develop or test.

```bash
git clone <repository-url>   # use the URL of this repo once published
cd codeatlas
python --version             # must be 3.10+ (use `python3` where `python` is absent)
python demo.py               # indexes the bundled fixtures, no setup
python -m unittest discover -s tests
```

That is the whole setup. The fastest way to use the tool without
installing it is `python -m codeatlas …` from the repo root:

```bash
python -m codeatlas init
python -m codeatlas index
python -m codeatlas map
python -m codeatlas ask "Where is authentication handled?"
python -m codeatlas context "Add rate limiting to the public API" --budget 400
python -m codeatlas diff --files billing.py
```

If you want the `codeatlas` command on your `PATH`, install the
package in editable mode (this only needs `setuptools`, which ships
with most Python installs; it installs no project dependencies):

```bash
pip install -e .
codeatlas --version          # prints: codeatlas 0.1.0
```

The entry point is defined in `pyproject.toml` as
`codeatlas = "codeatlas.__main__:main"`.

## How to run the tests

```bash
python -m unittest discover -s tests
```

Expected output: `Ran 189 tests … OK`. All tests are offline. Each
test copies the fixture repositories under `fixtures/` into a
temporary directory and indexes the copy, so tests never touch the
real repo and never need network access. Run the full suite before
submitting a PR, and run `python demo.py` as a smoke check that the
end-to-end flow (index → map → ask → diff impact → context pack)
still works.

To run a single test class:

```bash
python -m unittest tests.test_codeatlas.TestSearch -v
```

## How to add support for a new language parser

This is the most common contribution, and there is exactly one seam
for it: `codeatlas/parsers.py`. Read that file first — the
instructions below describe it as it actually is in v0.1.0.

### The parser interface

Every parser produces the same shape, `ParsedFile`, defined in
`codeatlas/parsers.py`:

```python
@dataclass
class ParsedFile:
    path: str                          # repo-relative path
    language: str                      # e.g. "python", "javascript"
    symbols: list[Symbol] = ...        # definitions, exact line numbers
    imports: list[Import] = ...        # module names the file depends on
    calls: list[Call] = ...            # (caller, callee, line) triples
    parse_error: str | None = None     # set on failure; symbols stay empty
```

The three element types, also in `parsers.py`, are:

- `Symbol(name, kind, line, end_line, qualified_name="", signature="", docstring="")`
  where `kind` is one of `function | method | class | variable |
  constant | interface | type | enum`.
  `qualified_name` is the dotted path (`Authenticator.authenticate`);
  `line`/`end_line` are 1-based. All four types round-trip through
  `to_dict()` / `from_dict()` — the index is persisted as JSON in
  `.codeatlas/index.json`, so every field you add must be JSON-serialisable
  and must survive that round-trip.
- `Import(module, names=[], line=0, level=0)` where `level` is `0` for an
  absolute import and `> 0` for a relative import (number of dots).
- `Call(caller, callee, line)` where `caller` is the qualified name of
  the enclosing symbol, or `""` for module-level code.

The dispatch is:

```python
def language_for_path(path: str) -> str | None: ...
def parse_file(path: str, source: str) -> ParsedFile: ...
```

`language_for_path` looks up the file extension in
`SUPPORTED_EXTENSIONS` (currently `.py`, `.js`, `.jsx`, `.ts`, `.tsx`,
`.mjs`, `.cjs`). `parse_file` returns `ParsedFile(path, language="unknown")`
for an unsupported extension, calls `_parse_python` for Python, and
`_parse_javascript` for JavaScript/TypeScript.

### Steps to add a language

1. **Add the extension(s)** to `SUPPORTED_EXTENSIONS` in
   `codeatlas/parsers.py`, mapping each to the language name.
2. **Add a branch in `parse_file`** for the new language (do not
   shoehorn it into `_parse_javascript` unless it genuinely shares
   that syntax), and implement `_parse_<language>(path, source)` —
   for example `_parse_go(path, source)` — returning a `ParsedFile`.
   Model it on `_parse_python` (real parser, exact `end_line`) where a
   stdlib parser exists, or on `_parse_javascript` (targeted regex,
   `end_line` set to the definition line) where it does not. The
   production path for every language is a Tree-sitter grammar; this
   module is the seam that adapter replaces, so keep your parser
   behind the same `ParsedFile` shape and do not change the shape to
   suit one language.
3. **Never raise on bad input, and never execute the target code.**
   A file that fails to parse must be recorded with `parse_error`
   set (e.g. `"SyntaxError line 3: …"`) and empty symbols — exactly
   as `_parse_python` does on `ast.parse` failure — so indexing
   degrades gracefully and the index stats can report the count.
   Python parsing uses `ast.parse` only; it never imports or runs the
   file being indexed. Keep it that way for every language.
4. **Add fixtures** under `fixtures/sample-<language>/` — a few small
   files that exercise functions, classes/methods, imports, and calls,
   plus a test file that imports the source (see
   `fixtures/sample-py/` for the pattern).
5. **Add tests** in `tests/test_codeatlas.py`: a parser test (symbols,
   kinds, imports, calls, line numbers), an indexer/graph test if the
   language has resolvable imports, and a parse-failure test
   (`parse_error` set, symbols empty). Tests must be offline and must
   index copies of fixtures in temp dirs, as the existing tests do.
6. **Document the gaps.** Update the parser table in
   `ARCHITECTURE.md` (and `docs/architecture.md`) with what the new
   parser understands and what it misses, and update the supported
   languages wherever they are listed. Do not claim support the
   parser does not have: the JS/TS regex parser, for example, is
   documented as missing dynamic imports, destructured methods,
   parameter lists nested more than three levels deep, methods
   inside a minified single-line class body, calls inside
   template-literal interpolations, and JSX syntax.

### What the graph needs from a parser

`codeatlas/graph.py` resolves imports to files in the repo
(`_resolve_import`: relative `./…` paths, Python dotted modules,
same-directory fallback) and links tests to source files by import
edges and by name (`test_auth.py` → `auth.py`). If your language's
imports cannot be resolved by those rules, say so in your PR and in
the docs — do not silently add a second, incompatible resolution
scheme. If a new resolution rule is genuinely needed, extend
`_resolve_import` with a test that pins the behaviour.

## Code style

CI (`.github/workflows/ci.yml`) runs a stdlib-only style check on
every push and pull request: no tab indentation, no trailing
whitespace. There is no formatter or linter configured beyond that
(no `ruff`/`black` config). Until one is adopted, follow the
existing code:

- **Standard library only.** Do not add a third-party dependency
  without discussing it in an issue first — "no dependencies, no
  network calls" is a core promise of this project.
- **Type hints** on public functions, `dataclasses` for data shapes,
  `from __future__ import annotations` at the top of package modules.
- **Deterministic behaviour.** Search ranking and context packs are
  deterministic signals only (no embeddings, no randomness, no wall
  clock in scoring). Every search result and context snippet must
  carry a `why` explaining it.
- **Docstrings** on modules and public functions that state what the
  code does *and* what it does not do. Known limitations belong in
  the docstring and in `ARCHITECTURE.md`, not hidden.
- **No network, no telemetry, no writes outside the index.**
  The indexer reads repo files and writes only
  `.codeatlas/index.json` (and `.codeatlas/config.json` on `init`).
  The tools in `codeatlas/tools.py` are read-only by construction:
  nothing in them writes, executes, or uploads code. Keep it that way.
- **Small, focused changes.** One concern per PR; keep the diff
  reviewable.

## How to submit a PR

1. Open an issue first for anything larger than a typo or a small
   bug fix, so design (especially a new parser, a ranking change, or
   a new output format) can be agreed before you write the code.
2. Fork the repo, create a branch from `main` with a descriptive name
   (`add-go-parser`, `fix-diff-impact-tests`), and make your change.
3. Run the full test suite (`python -m unittest discover -s tests`)
   and `python demo.py`; both must pass. Add or update tests for
   every behaviour change — a parser or ranking change without a
   test will not be merged.
4. Update the docs that describe the behaviour you changed:
   `ARCHITECTURE.md` / `docs/` for design, and `CHANGELOG.md`
   (add an entry under `## [Unreleased]`).
5. In the PR description, say what changed, why, what you tested
   (paste the test output), and what the change deliberately does
   *not* do. If the change alters search ranking, context-pack
   contents, or the architecture-map output, show a before/after
   example on the fixtures.
6. Be prepared for review to ask for narrower scope or more tests,
   particularly for new parsers: a small parser with documented gaps
   and tests is preferred over a large one with untested claims.

## Reporting bugs and security issues

- **Bugs:** open an issue with the command you ran, the fixture or
  minimal repo that reproduces it, the expected vs. actual output,
  and your Python version (`python --version`).
- **Security issues:** do **not** open a public issue. Follow
  [SECURITY.md](SECURITY.md) instead.

## Licence

CodeAtlas is MIT licensed (see `LICENSE`). By contributing, you agree
that your contributions will be licensed under the same MIT licence.
