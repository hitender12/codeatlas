# impact-of-a-change

Answer "if I change this, what breaks?" for the bundled
`fixtures/shop-py` sample app, using the real CodeAtlas API
(`get_change_impact`, `get_symbol`).

## Run it

From the repo root or from this directory:

```bash
python3 run.py
python3 examples/impact-of-a-change/run.py
```

## What it shows

1. **Narrow change — `shop/payments.py`.** The impact reaches
   `shop/orders.py` and `shop/api.py` (they depend on it through the
   import chain) and one test, `tests/test_orders.py`. It does *not*
   reach `tests/test_auth.py`.
2. **Symbol level — who calls `charge()`?** `create_order` in
   `shop/orders.py`. So changing `charge()`'s behaviour or signature
   means reviewing `create_order()` first.
3. **Wide change — `shop/auth.py`, for contrast.** Auth is imported
   almost everywhere, so its blast radius is strictly larger: more
   affected files and both test files. The point is that the tool
   distinguishes a narrow change from a wide one instead of always
   answering "everything".

## What it checks (self-checking, exits 0 on success)

- A payments change reaches `shop/orders.py` and `tests/test_orders.py`.
- A payments change does not reach `tests/test_auth.py`.
- `charge()` is called by `create_order` in `shop/orders.py`.
- An auth change affects strictly more files and tests than a payments
  change.

## Equivalent CLI command

```bash
python -m codeatlas diff fixtures/shop-py --files shop/payments.py
```

## Honest note

Impact is computed from the static import/call graph — it is "likely
affected", not a proof. A change can also affect code the graph cannot
see (dynamic imports, config, runtime behaviour), and CodeAtlas does not
run your tests; it only tells you which ones to run.

The script works on a temp copy of the fixture, so the repo itself is
never modified.
