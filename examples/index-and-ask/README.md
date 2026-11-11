# index-and-ask

Index the bundled `fixtures/shop-py` sample app, then ask a question and
build a context pack for a task — using the real CodeAtlas API
(`index_repo`, `search`, `get_symbol`, `build_context_pack`), the same
code the CLI calls. No mocks, no network, nothing leaves this machine.

## Run it

From the repo root or from this directory:

```bash
python3 run.py
python3 examples/index-and-ask/run.py
```

## What it shows

1. **Index** — 11 files, symbols and imports counted.
2. **Ask** — "Where is authentication handled?" The top hit is
   `Authenticator.authenticate` in `shop/auth.py:37`, with the reason
   ("exact symbol match; 5 caller(s) in the repo") printed next to it.
3. **Symbol lookup** — `charge` is defined in `shop/payments.py:12` and
   called by `create_order` in `shop/orders.py`.
4. **Context pack** — for the task "charge a customer after
   authentication" with a 400-token budget: the snippets that would be
   handed to an AI assistant, each with its file path, line range, token
   cost, and why it was included. The pack stays within budget.

## What it checks (self-checking, exits 0 on success)

- The index found all 11 files.
- The top search hit is `Authenticator.authenticate` in `shop/auth.py`.
- `charge` is defined in `shop/payments.py` and called by `create_order`.
- The context pack stays within its 400-token budget and covers both
  `shop/payments.py` and `shop/auth.py`.

## Equivalent CLI commands

```bash
python -m codeatlas index fixtures/shop-py
python -m codeatlas ask "Where is authentication handled?" fixtures/shop-py
python -m codeatlas context "charge a customer after authentication" fixtures/shop-py --budget 400
```

The script works on a temp copy of the fixture, so the repo itself is
never modified.
