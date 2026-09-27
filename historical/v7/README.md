# Cut Audit ER — V7

**Certified Proxy Search in Verification-Only Entity Repair: Coverage, Realized Value, and Cost.** This local research release adds fixed known-law controls and same-pool accounting to preserved V6 state audits. It changes no selector and adds no natural acquisition, model fit, benchmark, or sealed-test access. It does not claim acceptance, broad superiority, or new external validation.

Four predeclared controls separate hindsight information advantage from an expected decision gap. Three small graph distributions contain twenty legal partition worlds; a fourth problem uses an analytic formula. Exact pair marginals describe these constructed laws, not an empirically perfect matcher. Natural hindsight gaps do not identify an expected error rate or the mechanism demonstrated by these controls.

Original V6 scalar evidence remains under `evidence/`. New named tables contain exact-control actions/worlds and same-pool counters. All V6 public bytes remain at the paths recorded in `HISTORICAL_V6_MANIFEST.json`; immutable V5 history is stored only once. Original V6 figures/site are under `historical/v6/`.

## Finite local verification

Use Python 3.12 and pinned `requirements-public.txt`. Set `PYTHONPATH=src`, `PYTHONHASHSEED=0`, and `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS` to `1`.

```sh
python -m pip install -r requirements-public.txt
python -m pytest -q
python -m scripts.review_v7.validate_evidence --evidence evidence
python scripts/make_figures_v7.py --evidence evidence --legacy historical/v5/evidence --out build/figures
python scripts/build_site_v7.py --root . --out build/site
```

Use fresh output directories. Finite fixtures, exact control checks and figure projections do not rerun natural research acquisitions. Full workspace and clean-package tests have different scope, recorded separately in delivery receipts.

Historical saved-answer replay uses its preserved engine, from its historical root:

```sh
cd historical/v5
python -m scripts.review_v5.public_replay check --bundle replay/synthetic
python -m scripts.review_v5.public_replay check --bundle replay/dblp_exposed
python -m scripts.review_v5.public_replay check --bundle replay/dblp_unused
```

Replay refuses an unrecorded query and never fills answers from evaluator gold. Permitted synthetic and pseudonymized DBLP replay assets are historical. WDC remains aggregate-only: public tables cannot establish private pair identity, reconstruct natural graphs, or rerun all historical audits.

The manuscript is delivered privately and through an Overleaf source ZIP; it is not in this repository. No remote CI, GitHub deployment, submission or cloud Overleaf execution is implied by local checks. See `REPRODUCTION_SCOPE.md`, `THIRD_PARTY_NOTICES.md`, and `README.zh-Hant.md`.
