# Cut Audit ER — V6

**Certified proxy search in verification-only entity repair: coverage, realized value, and cost.** This local research release independently checks saved planner states. It does not propose another selector or claim state-of-the-art superiority, acceptance, or external validation.

V6 audits the searched pools at all 241 saved natural and 60 saved synthetic Full batch starts. A separate evaluator measures hindsight gain from completing each fixed batch, deleting only negative edges and paying for positive answers too. Synthetic H0/H9 references share the same 60 visible states; the 361 reference slots and related budgets are not independent samples. Consult `evidence/summary.json` for actual completion and gap counts. Unknown and failed states remain in the tables.

The ALASKA Camera branch stopped because the official data sharing link expired. All 21 V6 slots remain `not_started_download_blocked`: no archive, model fit, or acquisition. V5's separate 21 `not_started_gate` slots remain unchanged under `historical/v5`. Neither set is an executed benchmark result.

## Finite local checks

Use Python 3.12 and `requirements-public.txt`. Set `PYTHONPATH=src`, `PYTHONHASHSEED=0`, `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, and `NUMEXPR_NUM_THREADS=1`. From this root:

```sh
python -m pip install -r requirements-public.txt
python -m pytest -q
python -m scripts.review_v6.validate_evidence --evidence evidence
python scripts/make_figures_v6.py --out build/figures
python scripts/build_site_v6.py --out build/site
```

Run historical saved-answer replay with its preserved first-party engine, from its own release root:

```sh
cd historical/v5
python -m scripts.review_v5.public_replay check --bundle replay/synthetic
python -m scripts.review_v5.public_replay check --bundle replay/dblp_exposed
python -m scripts.review_v5.public_replay check --bundle replay/dblp_unused
cd ../..
```

The public V5 comparison fixture has one documented path adaptation: it also finds the unchanged V4 source at `historical/v5/historical/v4/src`. Its assertions and compared engine sources remain unchanged.

The exact figure and site commands used for delivery are recorded in the extraction receipt. Use fresh output directories. Synthetic unit fixtures test correctness and do not create research observations. Replay reads recorded answers and refuses any unrecorded query; it is not a new acquisition.

Six figures use the same public evidence as the private paper. The website offers English and Traditional Chinese, figure enlargement, tables, limitations, and reproduction scope. This release is local; no repository push or Pages deployment is claimed. The paper full text stays in the private/Overleaf delivery.

See `REPRODUCTION_SCOPE.md`, `THIRD_PARTY_NOTICES.md`, and `README.zh-Hant.md`. The public tables omit pair identities, gold mappings, graph topology, partition hashes, and pair scores. Complete public replay assets for synthetic and order-preserving pseudonymized DBLP are retained in the historical release. WDC remains aggregate-only. These public scalar checks cannot independently reconstruct WDC candidate identities or all 301 private audits.
