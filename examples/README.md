# CodeAtlas examples

Runnable, self-checking examples. Each one lives in its own directory
with a README and a `run.py` that prints PASS/FAIL and exits 0 on
success. Every example works from the repo root **and** from its own
directory, uses the real CodeAtlas CLI/API (no mocks), runs on a temp
copy of a bundled fixture (the repo itself is never modified), and needs
nothing beyond the Python standard library.

| Example | What it shows |
| --- | --- |
| [index-and-ask](index-and-ask/) | Index `fixtures/shop-py`, ask "Where is authentication handled?", look up `charge` with its callers, and build a 400-token context pack. |
| [incremental-index](incremental-index/) | Index `fixtures/sample-py` three times through the CLI: first run parses 5 files, second run re-parses 0, editing one file re-parses exactly that file. |
| [impact-of-a-change](impact-of-a-change/) | What a change to `shop/payments.py` affects (narrow) vs `shop/auth.py` (wide), plus who calls `charge()`. |

Run any of them with:

```bash
python3 examples/<name>/run.py
```

or from inside its own directory:

```bash
cd examples/<name> && python3 run.py
```
