# Security Policy

## Supported versions

Only the latest release is supported with security fixes. Earlier
releases receive no security updates — please upgrade to the latest
release before reporting an issue, and state the version you tested
against.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: Yes (latest 0.1.x release) |
| < 0.1   | :x: No             |

The current version is **0.1.0** (`codeatlas.__version__` in
`codeatlas/__init__.py`). There are no earlier releases.

## How to report a vulnerability

**Do not open a public GitHub issue for a security vulnerability.**
Public issues expose the flaw to everyone, including people who would
exploit it, before a fix exists.

Instead, report it privately using one of these routes:

1. **GitHub Security Advisory (preferred, once the project is
   published on GitHub):** open a private vulnerability report via
   the repository's **Security** tab → **Report a vulnerability**.
   This keeps the report private until a fix is ready.
2. **Email (placeholder — see below):** send a report to the
   security contact address below.

> **⚠️ PLACEHOLDER — NOT A REAL CONTACT YET.**
> The address below is a placeholder. It must be replaced with a real,
> monitored security contact address before this project is published
> publicly. Do not assume mail to it is read by anyone.
>
> Placeholder address: `security@codeatlas.example`
> (`codeatlas.example` is a reserved example domain; it is not a real
> mailbox.)

A good report includes:

- The CodeAtlas version you tested (`codeatlas --version` or
  `python -m codeatlas --version`).
- A minimal reproduction: the command run, the input (a small fixture
  repo or file, not a full private codebase), and the observed vs.
  expected behaviour.
- The impact as you understand it: what an attacker could do, and
  what they would need (e.g. a malicious repository to index, a
  crafted file, local access).
- Whether the issue is already public, and if so, where.

### What happens after you report

Maintainers will:

1. Acknowledge receipt of the report as soon as reasonably possible.
2. Investigate privately and confirm whether the issue is a real
   vulnerability in CodeAtlas.
3. Prepare a fix, and coordinate disclosure with you — the issue
   will not be disclosed publicly until a fixed release is available,
   unless the issue is already public or is being actively exploited.
4. Publish the fix in a new release, note it in `CHANGELOG.md`, and
   credit you in the release notes if you would like to be credited.
   Please say in your report whether you want to be credited, and
   under what name.

No fixed response time is promised: this is a small, volunteer-run
project. If you have not received an acknowledgement within a
reasonable time, you may disclose responsibly through the public
issue tracker, noting that you first reported privately.

## What is in scope

In v0.1.0, CodeAtlas is a local command-line tool and library. The
following components are in scope for security reports:

- **The indexer** (`codeatlas/indexer.py`) — file walking, hashing,
  incremental re-indexing, and persistence of `.codeatlas/index.json`.
  This includes how it handles symlinks, unreadable or non-UTF-8
  files, very large files, and files that disappear mid-index.
- **The parsers** (`codeatlas/parsers.py`) — Python `ast` parsing and
  JavaScript/TypeScript regex extraction. A crafted source file must
  not crash the indexer, execute code, or corrupt the index; a parse
  failure must be recorded as `parse_error`, not raised.
- **The graph, search, context-pack, and architecture-map code**
  (`codeatlas/graph.py`, `search.py`, `context.py`, `archmap.py`) —
  including import resolution, diff-impact computation, and the
  token-budget enforcement in context packs.
- **The CLI** (`codeatlas/__main__.py`) — argument handling and the
  `git` subprocess calls used by the diff view (`git diff` /
  `git status --porcelain` in `codeatlas/archmap.py`).
- **The read-only tool surface** (`codeatlas/tools.py`) —
  `search_code`, `get_symbol`, `get_file_outline`,
  `build_context_pack_tool`, `get_architecture_map`, and
  `get_change_impact`. These functions are read-only by construction:
  nothing in them writes, executes, or uploads code, and a report
  showing otherwise is in scope.

### Out of scope / not yet built

The following do **not** exist in v0.1.0, so vulnerabilities in them
cannot be reported against this release — but design concerns about
them are welcome as ordinary issues:

- A local HTTP API, an MCP server, or a VS Code extension (the
  blueprint's production path). The plain functions in
  `codeatlas/tools.py` are the stable contract those adapters will
  call; they are not themselves a network service.
- The Rust core, Tree-sitter grammars, Tantivy, and SQLite from the
  blueprint. Reports about those technologies as such belong to
  their own projects.
- Any hosted or team service. CodeAtlas has none.

Reports about vulnerabilities in Python itself, in `git`, or in a
third-party tool should be reported to those projects, unless the
issue is specifically in how CodeAtlas invokes or handles them.

## Privacy stance: local-first, no code upload

CodeAtlas is local-only by design, and that is a security property,
not just a feature:

- It reads the files you point it at and writes an index inside that
  repository (`.codeatlas/index.json`, plus `.codeatlas/config.json`
  on `init`). It makes **no network requests at all** — there is no
  telemetry, no account, and no code path that uploads source code.
- It does **not execute the code it indexes**. Python files are read
  with `ast.parse` only; JavaScript/TypeScript files are scanned with
  regular expressions. Indexing an untrusted repository must not run
  that repository's code.
- The index itself (`.codeatlas/index.json`) contains file paths,
  SHA-256 hashes, symbols, imports, and call names from the indexed
  repository. Treat it as a derivative of your source: do not publish
  or share it for a private codebase, and add `.codeatlas/` to
  `.gitignore` if you do not want it committed (the repo's own
  `.gitignore` already excludes it).
- The diff view shells out to `git` (`git diff --name-only`,
  `git status --porcelain`) with a fixed argument list and a timeout;
  it does not pass user-controlled strings to a shell.

If you find a place where CodeAtlas sends data over the network,
executes indexed code, or writes outside the target repository's
`.codeatlas/` directory, that is a security-relevant bug — please
report it as above.

## Secure use

- Only index repositories you trust to the extent that you trust
  their *contents to be read*: indexing parses file contents, and a
  malicious file should be handled gracefully (see scope above), but
  do not index a repository you believe is actively hostile without
  first inspecting it.
- Keep Python up to date: CodeAtlas requires Python 3.10+ and uses
  only the standard library, so its dependency surface is the Python
  runtime itself.
