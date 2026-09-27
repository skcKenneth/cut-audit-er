# Cut Audit ER — V5

Finite research on candidate coverage and proxy-aligned scoring in verification-only entity-cluster repair. This is a local reproducibility release, not a claim of acceptance, deployment or state-of-the-art superiority. Read `README.zh-Hant.md` for Traditional Chinese.

**Outcome: REFRAME.** Full and Raw have identical losses and paid sequences in all nine matched natural conditions, with added computational cost. Coverage repairs the known synthetic k3/B6 counterexample but ties BC and the new singleton control. The prespecified development gate failed: all21 ALASKA slots remain unstarted; no Camera download, model fit or external acquisition occurred. These are unattempted slots, not failed benchmark runs.

The study compares weighted BC, the original fixed and adaptive planners, coverage with the old BC cap, upper-bound screening of the old pool, the combined method, and its pre-screening singleton control. The query contract permits deletion only after a paid negative answer. Positive answers do not cancel an already committed fixed batch. Gold-based diagnostics are separate from selection.

## Run the finite checks

Use Python3.12 and the pinned `requirements-public.txt`. From this directory:

```sh
python -m pip install -r requirements-public.txt
python -m pytest -q
python scripts/validate_evidence.py --evidence evidence
python scripts/check_public_release.py
python -m scripts.review_v5.public_replay check --bundle replay/synthetic
python -m scripts.review_v5.public_replay check --bundle replay/dblp_exposed
python -m scripts.review_v5.public_replay check --bundle replay/dblp_unused
python scripts/make_figures.py --evidence evidence --out build/figures
python scripts/build_site.py --out build/site
```

Set `PYTHONPATH=src`, `PYTHONHASHSEED=0`, `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1` and `NUMEXPR_NUM_THREADS=1` before running. The test configuration also sets the local source path. Use fresh output directories. Tests use synthetic correctness fixtures; these are not additional research experiments.

`evidence/manifest.json` pins the scalar tables for all150 synthetic acquisitions,63 natural development slots and21 conditional external slots. The300 H0/H9 evaluations share150 acquisitions and are dependent. Requested budgets are separately executed runs, not independent samples. Every missing endpoint remains missing; a saved timeout prefix is not a completed endpoint. The six figures are generated from these public tables and their preserved historical sources.

`replay/` contains synthetic data and order-preserving pseudonymized DBLP topology, complete scores, paid answers and a separate evaluator reference. Replay refuses an unrecorded answer. It rechecks saved decisions, not a fresh oracle study. WDC remains aggregate-only; aggregate event positions cannot independently verify original pair identities. The complete unchanged V4 public release is retained under `historical/v4`; do not combine runtimes across engine versions as a fair speed ranking.

See `REPRODUCTION_SCOPE.md` for scope and `THIRD_PARTY_NOTICES.md` for attribution. The paper full text, original record text/IDs, reverse alias tables, WDC graphs, credentials and sealed test are excluded. The software LICENSE does not relicense third-party data.
