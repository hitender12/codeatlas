# Getting started with CodeAtlas

A hands-on tutorial. In about five minutes you will index a small
codebase, search it, map its architecture, see what a change would
affect, and build a token-budgeted context pack — all locally, with
no account, no API key, and no uploads.

**Requirements:** Python 3.10 or newer. No third-party packages:
CodeAtlas is standard library only, so there is nothing to install
to follow this tutorial. (On systems where the `python` command does
not exist, use `python3` in every command below — the two are
interchangeable here.)

## 1. Try the demo first (no setup)

From the repo root:

```bash
python demo.py
```

This copies the bundled fixture repo (`fixtures/sample-py`: three
source files, `api.py`, `auth.py`, `billing.py`, plus tests) into a
temporary directory, indexes it, and runs the blueprint's demo
question — *"If I change the billing interface, what code and tests
are likely affected?"* You should see output like this:

```text
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

Nothing was uploaded anywhere, and the temporary copy is deleted
when the demo finishes.

## 2. Index your own repo (or a copy of a fixture)

To work through the commands yourself, use a scratch copy of the
fixture so you can edit files freely:

```bash
cp -r fixtures/sample-py /tmp/my-repo
cd /tmp/my-repo
python -m codeatlas init            # create .codeatlas/config.json
python -m codeatlas index           # index the current repo
```

(`python -m codeatlas` works from the CodeAtlas repo root; if you
installed the package with `pip install -e .`, the `codeatlas`
command works anywhere. See [CONTRIBUTING.md](../CONTRIBUTING.md)
for setup.)

Expected output:

```text
initialized codeatlas in /tmp/my-repo/.codeatlas/config.json
privacy: local-only -- codeatlas never uploads source code.
indexed 5 file(s), 0 unchanged, 0 removed
total: 5 files, … symbols, … imports
```

The index is stored as plain JSON in `.codeatlas/index.json` inside
the repo. You can inspect it with any JSON tool — it holds file
paths, SHA-256 hashes, symbols, imports, and calls.

Run `index` again without changing anything:

```bash
python -m codeatlas index
```

```text
indexed 0 file(s), 5 unchanged, 0 removed
```

That is incremental indexing: only files whose content (SHA-256)
changed are re-parsed. Edit one file — add a comment to
`billing.py` — and re-run: exactly 1 file is re-parsed, 4 are
unchanged. Delete a file and re-run: it is removed from the index.

## 3. Ask a question

```bash
python -m codeatlas ask "Where is authentication handled?"
python -m codeatlas ask "charge"
```

Output is one line per result, with a `why:` line under each:

```text
[symbol] billing.py:12  (106)  charge
    why: exact symbol match
    why: 3 caller(s) in the repo
```

Every result explains itself: exact symbol match, symbol name
contains the query, full-text match on a line, query tokens in the
file path, or imported-by-N-files graph relevance. Natural-language
questions work because stopwords are removed and words are stemmed
(`authentication` matches `authenticate`). See
[architecture.md](architecture.md) ("Hybrid search") for the exact
scoring.

Try `--limit` to control how many results you get:

```bash
python -m codeatlas ask "charge" --limit 3
```

## 4. See the architecture map

```bash
python -m codeatlas map
python -m codeatlas map --format dot
python -m codeatlas map --format json
```

The default Mermaid output can be pasted into a Markdown file or a
Mermaid viewer; DOT goes to Graphviz; JSON is for other tools.
Modules are top-level directories (a root-level file is its own
module), and an edge `billing --> auth` means code in `billing`
imports code in `auth`. Edges inside a single module are not drawn.

## 5. See what a change would affect

```bash
python -m codeatlas diff --files billing.py
```

This lists the changed file, the affected modules and files (the
changed file plus everything that transitively *depends* on it), and
the affected tests. Note what it does **not** list: the modules
`billing.py` itself imports. Changing a caller does not change the
code it calls, so upstream modules are not flagged.

If you are in a git repo, you can omit `--files` and CodeAtlas will
use `git status` (working tree + staged changes), or `git diff
--name-only <ref>` with `--ref`:

```bash
python -m codeatlas diff
python -m codeatlas diff --ref HEAD~1
```

## 6. Build a context pack for a task

```bash
python -m codeatlas context "Add rate limiting to the public API" --budget 400
python -m codeatlas context "charge a customer after authentication" --budget 400 --json
```

A context pack is a set of snippets — each with an exact file path,
line range, and a `why:` explaining why it was chosen — that fits
inside a token budget you set. The default budget is 4000 tokens, or
`context_budget_tokens` from `.codeatlas/config.json` when that file
sets it. Tokens are approximated as 4 characters per token (documented in
[architecture.md](architecture.md)); a snippet that would exceed
the remaining budget is truncated at a line boundary, and the pack
never exceeds its budget. The `--json` form is the machine-readable
version to hand to an AI coding tool.

Try a tiny budget to see enforcement in action:

```bash
python -m codeatlas context "charge a customer" --budget 100
```

## 7. Use the read-only tools from Python

The CLI is a thin wrapper over plain functions in
`codeatlas/tools.py` — the same surface a future MCP adapter or
editor extension will call. From Python:

```python
from codeatlas.indexer import index_repo
from codeatlas.graph import Graph
from codeatlas.tools import search_code, get_symbol, build_context_pack_tool

index, _stats = index_repo(".")
graph = Graph.build(index)

print(search_code(index, graph, "charge"))
print(get_symbol(index, graph, "charge"))
print(build_context_pack_tool(index, graph, "charge a customer", 200))
```

These functions are read-only by construction: they never write,
execute, or upload code.

## Troubleshooting

| Symptom | What it means / what to do |
| ------- | -------------------------- |
| `no index found -- run \`codeatlas index\` first` | You ran `map`, `ask`, `context`, or `diff` before indexing. Run `python -m codeatlas index` first. |
| `not a git repository and no files given` | `diff` without `--files` needs a git repo. Pass `--files <name>…` explicitly, or run it inside a git checkout. |
| `warning: N file(s) failed to parse` after `index` | Those files have a parse error (e.g. a Python syntax error). They are recorded in the index with `parse_error` and empty symbols; indexing continues. Fix the file, or inspect `.codeatlas/index.json` for the recorded error. |
| A JS/TS symbol is missing, or a call is attributed to the wrong function | JS/TS parsing is regex-based and approximate: it misses dynamic imports, destructured methods, parameter lists with nested parentheses, and JSX syntax (components are found only as plain functions/classes). Interfaces, type aliases, enums, return-annotated arrows/methods, getters, and module-level constants *are* extracted. See [architecture.md](architecture.md) for the full list of gaps. |
| Results look thin on a large repo | Check that the files are not under an ignored directory (`.git`, `node_modules`, `.venv`, `dist`, `build`, … — see `indexer.py: DEFAULT_IGNORES`) and that their extensions are supported (`.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs`). |
| `python -m codeatlas` says `No module named codeatlas` | Run it from the CodeAtlas repo root, or install with `pip install -e .`. |

## Next steps

- Read [architecture.md](architecture.md) for how the indexer,
  graph, search, and context packs actually work — including the
  known gaps.
- Run the test suite: `python -m unittest discover -s tests`
  (160 tests, all offline).
- To contribute — especially to add a language parser — read
  [CONTRIBUTING.md](../CONTRIBUTING.md).
