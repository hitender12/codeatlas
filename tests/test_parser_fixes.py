"""Regression tests for the 2026-11-11 CodeAtlas fix round.

One class per fixed defect (see CHANGELOG.md [Unreleased]):

* Defect 3 -- README/indexer claimed git status drove indexing;
  indexing is SHA-256 only and the dead ``_git_changed_files`` is gone.
* Defect 4 -- ``.codeatlas/config.json`` is now read back: ignore list,
  language filter, and the default context budget.
* Defect 5 -- every CLI command in the docs runs verbatim.
* Defect 6 -- path traversal: crafted index entries and symlinks
  cannot make the indexer/readers touch files outside the repo.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from codeatlas.__main__ import main as cli_main  # noqa: E402
from codeatlas.context import build_context_pack  # noqa: E402
from codeatlas.graph import Graph  # noqa: E402
from codeatlas.indexer import (  # noqa: E402
    Index,
    IndexConfig,
    index_repo,
    init_repo,
    load_config,
)
from codeatlas.search import search  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")


class TempRepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="codeatlas-fix-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, rel, content):
        full = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
        return full

    def write_config(self, config: dict):
        cfg_dir = os.path.join(self.tmp, ".codeatlas")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "config.json"), "w") as fh:
            json.dump(config, fh)

    def index(self):
        index, stats = index_repo(self.tmp)
        return index, stats, Graph.build(index)


# ---------------------------------------------------------------------------
# Defect 3: indexing is SHA-256 only; no git-status code path remains
# ---------------------------------------------------------------------------


class TestIndexingIsSha256Only(unittest.TestCase):
    def test_no_git_changed_files_helper_in_indexer(self):
        import codeatlas.indexer as indexer_mod

        self.assertFalse(
            hasattr(indexer_mod, "_git_changed_files"),
            "dead git-status helper must be gone; indexing is SHA-256 only",
        )

    def test_indexer_module_docstring_does_not_claim_git_status(self):
        import codeatlas.indexer as indexer_mod

        self.assertIn("SHA-256", indexer_mod.__doc__)
        self.assertNotIn("prefers", indexer_mod.__doc__)
        self.assertIn("NOT used for indexing", indexer_mod.__doc__)


# ---------------------------------------------------------------------------
# Defect 4: config.json is read back
# ---------------------------------------------------------------------------


class TestConfigIsRead(TempRepoCase):
    def test_defaults_when_no_config_exists(self):
        config = load_config(self.tmp)
        self.assertEqual(config, IndexConfig())
        self.assertEqual(config.context_budget_tokens, 4000)
        self.assertIn("python", config.languages)

    def test_init_writes_a_config_that_loads_back_identically(self):
        init_repo(self.tmp)
        config = load_config(self.tmp)
        self.assertEqual(config.context_budget_tokens, 4000)
        self.assertEqual(sorted(config.languages),
                         ["javascript", "python", "typescript"])
        self.assertIn("node_modules", config.ignore)

    def test_corrupt_config_falls_back_to_defaults(self):
        cfg_dir = os.path.join(self.tmp, ".codeatlas")
        os.makedirs(cfg_dir, exist_ok=True)
        with open(os.path.join(cfg_dir, "config.json"), "w") as fh:
            fh.write("{not json")
        self.assertEqual(load_config(self.tmp), IndexConfig())

    def test_non_dict_config_falls_back_to_defaults(self):
        self.write_config(["not", "a", "dict"])
        self.assertEqual(load_config(self.tmp), IndexConfig())

    def test_invalid_values_fall_back_per_key(self):
        self.write_config({
            "languages": "python",          # wrong type: ignored
            "ignore": "node_modules",       # wrong type: ignored
            "context_budget_tokens": -5,    # invalid: ignored
        })
        config = load_config(self.tmp)
        self.assertEqual(config, IndexConfig())
        # ...but a valid key alongside invalid ones is still honoured.
        self.write_config({
            "languages": ["python"],
            "context_budget_tokens": "lots",  # wrong type: ignored
        })
        config = load_config(self.tmp)
        self.assertEqual(config.languages, ["python"])
        self.assertEqual(config.context_budget_tokens, 4000)

    def test_unknown_language_names_are_dropped(self):
        self.write_config({"languages": ["python", "klingon"]})
        self.assertEqual(load_config(self.tmp).languages, ["python"])

    def test_ignore_list_is_honoured(self):
        self.write("keep.py", "def keep():\n    return 1\n")
        self.write("skipme/dropped.py", "def dropped():\n    return 2\n")
        self.write_config({"ignore": ["skipme"]})
        index, stats, _ = self.index()
        self.assertEqual(sorted(index.files), ["keep.py"])
        self.assertEqual(stats.indexed, 1)

    def test_config_ignore_replaces_the_default_list(self):
        # Editing the ignore list must actually change behaviour: with
        # an empty ignore list, node_modules is indexed (except that
        # .git/.codeatlas are always ignored).
        self.write("node_modules/x.js", "function hidden() {}\n")
        self.write_config({"ignore": []})
        index, _, _ = self.index()
        self.assertIn("node_modules/x.js", index.files)

    def test_always_ignored_dirs_cannot_be_unignored(self):
        self.write(".git/g.py", "def hidden(): pass\n")
        self.write("real.py", "def real():\n    return 1\n")
        self.write_config({"ignore": []})
        index, _, _ = self.index()
        self.assertEqual(sorted(index.files), ["real.py"])

    def test_language_filter_is_honoured(self):
        self.write("a.py", "def f():\n    return 1\n")
        self.write("b.js", "function g() {}\n")
        self.write_config({"languages": ["python"]})
        index, _, _ = self.index()
        self.assertEqual(sorted(index.files), ["a.py"])

    def test_cli_context_uses_config_budget_by_default(self):
        self.write("a.py", "def ok():\n    return 1\n")
        self.index()
        self.write_config({"context_budget_tokens": 100})
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["context", "ok", self.tmp])
        self.assertEqual(code, 0)
        self.assertIn("budget: 100 tokens", buf.getvalue())
        # An explicit --budget still wins over the config value.
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["context", "ok", self.tmp, "--budget", "250"])
        self.assertEqual(code, 0)
        self.assertIn("budget: 250 tokens", buf.getvalue())


# ---------------------------------------------------------------------------
# Defect 5: every documented CLI command runs verbatim
# ---------------------------------------------------------------------------


class TestDocumentedCliCommands(TempRepoCase):
    def setUp(self):
        super().setUp()
        shutil.copytree(os.path.join(FIXTURES, "sample-py"),
                        os.path.join(self.tmp, "sample-py"))
        self.repo = os.path.join(self.tmp, "sample-py")
        index_repo(self.repo)

    def _run(self, args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                code = cli_main(args)
            except SystemExit as exc:  # --version / --help exit via argparse
                code = exc.code
        return code, buf.getvalue()

    def test_readme_quickstart_commands(self):
        # Run the full sequence on a FRESH copy: setUp already indexed
        # self.repo, so `index` here would report 0 parsed files.
        fresh = os.path.join(self.tmp, "fresh-py")
        shutil.copytree(os.path.join(FIXTURES, "sample-py"), fresh)
        for args, needle in (
            (["init", fresh], "initialized codeatlas"),
            (["index", fresh], "indexed 5 file(s)"),
            (["map", fresh], "billing --> auth"),
            (["map", fresh, "--format", "dot"], "digraph codeatlas"),
            (["map", fresh, "--format", "json"], '"billing"'),
            (["ask", "charge", fresh], "billing.py"),
            (["context", "Add rate limiting to the public API", fresh,
              "--budget", "400"], "budget: 400 tokens"),
            (["diff", fresh, "--files", "billing.py"],
             "tests/test_billing.py"),
        ):
            code, out = self._run(args)
            self.assertEqual(code, 0, args)
            self.assertIn(needle, out, args)

    def test_getting_started_commands(self):
        for args, needle in (
            (["ask", "Where is authentication handled?", self.repo],
             "auth.py"),
            (["ask", "charge", self.repo, "--limit", "3"], "billing.py"),
            (["context", "charge a customer", self.repo, "--budget", "100"],
             "budget: 100 tokens"),
            (["context", "charge a customer after authentication", self.repo,
              "--budget", "400", "--json"], '"budget_tokens": 400'),
        ):
            code, out = self._run(args)
            self.assertEqual(code, 0, args)
            self.assertIn(needle, out, args)

    def test_version_and_help(self):
        code, out = self._run(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("codeatlas 0.1.0", out)

    def test_diff_without_git_and_without_files_fails_cleanly(self):
        code, out = self._run(["diff", self.repo])
        self.assertEqual(code, 1)

    def test_cli_ask_output_matches_the_documented_shape(self):
        # docs/getting-started.md shows this exact shape (line, score,
        # qualified name, exact-match reason, caller count).
        code, out = self._run(["ask", "charge", self.repo])
        self.assertEqual(code, 0)
        self.assertIn("[symbol] billing.py:12  (106)  charge", out)
        self.assertIn("why: exact symbol match", out)
        self.assertIn("why: 3 caller(s) in the repo", out)


# ---------------------------------------------------------------------------
# Defect 6: path traversal / unsafe file handling
# ---------------------------------------------------------------------------


class TestPathTraversal(TempRepoCase):
    def _craft_index(self, entries):
        self.write("real.py", "def real():\n    return 1\n")
        index, _, _ = self.index()
        payload = {
            "version": 1,
            "root": self.tmp,
            "files": {},
        }
        for rel, rec in index.files.items():
            payload["files"][rel] = rec.to_dict()
        for rel in entries:
            payload["files"][rel] = {
                "path": rel, "language": "python", "sha256": "x",
                "mtime": 0, "size": 1,
                "parsed": {"path": rel, "language": "python", "symbols": [],
                           "imports": [], "calls": [], "parse_error": None},
            }
        cfg_dir = os.path.join(self.tmp, ".codeatlas")
        with open(os.path.join(cfg_dir, "index.json"), "w") as fh:
            json.dump(payload, fh)

    def test_crafted_index_entries_escaping_the_root_are_dropped(self):
        self._craft_index(["../outside.py", "/etc/passwd", "..\\windows.py",
                           "sub/../../escape.py"])
        loaded = Index.load(self.tmp)
        self.assertEqual(sorted(loaded.files), ["real.py"])

    def test_read_lines_refuses_paths_outside_the_root(self):
        self.write("real.py", "def real():\n    return 1\n")
        index, _, _ = self.index()
        for bad in ("../outside.py", "/etc/passwd", "sub/../../escape.py"):
            with self.assertRaises(ValueError, msg=bad):
                index.read_lines(bad, 1, 1)

    def test_search_ignores_crafted_paths(self):
        # Even if a bad record somehow reached the index dict, search
        # must not open files outside the repo.
        self._craft_index(["../outside.py"])
        loaded = Index.load(self.tmp)
        self.assertNotIn("../outside.py", loaded.files)
        graph = Graph.build(loaded)
        results = search(loaded, graph, "real")
        self.assertTrue(all(r.path == "real.py" for r in results))

    def test_symlinked_file_is_not_indexed(self):
        # Target lives in a *different* directory: only the symlink
        # itself is inside the repo.
        other_dir = tempfile.mkdtemp(prefix="codeatlas-outside-")
        try:
            outside = os.path.join(other_dir, "outside-secret.py")
            with open(outside, "w") as fh:
                fh.write("SECRET = 'do-not-index-me'\n")
            os.symlink(outside, os.path.join(self.tmp, "linked.py"))
            self.write("real.py", "def real():\n    return 1\n")
            index, _, _ = self.index()
            self.assertEqual(sorted(index.files), ["real.py"])
            self.assertNotIn("linked.py", index.files)
        finally:
            shutil.rmtree(other_dir, ignore_errors=True)

    def test_symlinked_file_pointing_outside_is_not_indexed(self):
        secret = tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, dir="/tmp")
        try:
            secret.write("PASSWORD = 'hunter2'\n")
            secret.close()
            os.symlink(secret.name, os.path.join(self.tmp, "evil.py"))
            self.write("real.py", "def real():\n    return 1\n")
            index, _, _ = self.index()
            self.assertEqual(sorted(index.files), ["real.py"])
        finally:
            os.unlink(secret.name)


@unittest.skipUnless(shutil.which("git"), "git not installed")
class TestGitRefOptionInjection(TempRepoCase):
    """A `diff --ref` value starting with `-` must not be parsed as a
    git option (e.g. `--output=<file>` would make git write a file)."""

    def test_dash_ref_is_not_treated_as_an_option(self):
        import subprocess

        self.write("a.py", "def f():\n    return 1\n")
        subprocess.run(["git", "-C", self.tmp, "init", "-q"], check=True)
        subprocess.run(["git", "-C", self.tmp, "add", "."], check=True)
        subprocess.run(
            ["git", "-C", self.tmp, "-c", "user.email=t@t",
             "-c", "user.name=t", "commit", "-qm", "init"],
            check=True,
        )
        from codeatlas.archmap import git_changed_files

        # With --end-of-options, git treats this as an (unknown)
        # revision, not as the --output option: it fails safely and
        # writes no file, instead of parsing it as an option.
        self.assertIsNone(git_changed_files(self.tmp, ref="--output=/tmp/pwned"))
        self.assertFalse(os.path.exists("/tmp/pwned"))
        self.assertEqual(git_changed_files(self.tmp, ref="HEAD"), [])


if __name__ == "__main__":
    unittest.main()
