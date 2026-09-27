# CUT-AUDIT-ER

[繁體中文](README.zh-Hant.md) · [Source repository](https://github.com/skcKenneth/cut-audit-er) · [Pages website](https://skcKenneth.github.io/cut-audit-er/)

Research code and evidence for **Certified Proxy Search in Verification-Only Entity Repair: Coverage, Realized Value, and Cost**. The task repairs entity clusters with paid pair queries and deletion of verified negative edges. This public release retains V7.1 evidence and six figures, with finite correctness checks and saved-answer replay.

All 241 retained natural-data Full choices are certified computed-proxy maximizers within their searched pools. Full and Raw have identical outcomes and paid sequences in the nine retained natural cohort–budget comparisons. Certification does not establish optimal repair quality. Four fixed constructed controls distinguish hindsight information advantage from an expected decision gap; their exact pair marginals do not imply a perfectly calibrated natural matcher. The research decision remains **REFRAME**, with no claim of acceptance, general superiority or successful new external validation.

Repository cleanup changes presentation and publishing support only. It adds no selector, natural acquisition, model fit, dataset, tuning or sealed-test access. The paper and private review materials are excluded.

## Contents and limits

- `src/`, `scripts/`, `tests/`: first-party code, finite fixtures and evidence checks.
- `evidence/`, `figures/`: retained scalar evidence and six figure families, including failures and missing slots.
- `historical/v5/`: preserved engine and permitted synthetic / pseudonymized DBLP saved-answer replay.
- `site/`: bilingual public website; Actions rebuilds and checks it before Pages deployment.
- [Reproduction scope](REPRODUCTION_SCOPE.md), [third-party sources and rights](THIRD_PARTY_NOTICES.md), and [archival inventories](provenance/archive_manifests/).

WDC is aggregate-only. Public tables cannot establish private pair identities, reconstruct WDC graphs or independently rerun all historical audits. Known-law controls are constructed examples, not natural data or independent statistical samples. Native TransClean / GraphCR comparisons remain incomplete; an adapter is not a full original-method reproduction.

## Finite verification

Use Python 3.12 and the pinned direct dependencies in `requirements-public.txt`. Set `PYTHONPATH=src`, `PYTHONHASHSEED=0`, and `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS` to `1`.

```sh
python -m pip install -r requirements-public.txt
python -m pytest -q
python -m scripts.review_v7.validate_evidence --evidence evidence
python scripts/make_figures_v7_1.py --evidence evidence --legacy historical/v5/evidence --out build/figures
python scripts/build_site_v7_1.py --root . --out build/site
python scripts/check_release.py --root . --rebuilt-figures build/figures --site build/site
```

Use fresh output directories. These commands check finite fixtures, exact control arithmetic, retained evidence, numeric figure projections and site assets. They do not rerun natural research acquisitions. Rendering can differ across operating systems; the release check compares complete numerical projections rather than claiming cross-platform PDF byte identity.

From the historical engine's own root, replay recorded answers:

```sh
cd historical/v5
python -m scripts.review_v5.public_replay check --bundle replay/synthetic
python -m scripts.review_v5.public_replay check --bundle replay/dblp_exposed
python -m scripts.review_v5.public_replay check --bundle replay/dblp_unused
```

Replay refuses unrecorded queries; evaluator references never supply missing answers. Preserve this engine's source files because replay checks their hashes and complete ordered traces.

## Publishing and licenses

The [Actions workflow](.github/workflows/ci.yml) runs Python 3.12 finite checks, evidence validation, three saved-answer replays, six-figure rebuilding and website verification. Pages deployment depends on those checks and is limited to `main`. The workflow does not download research data, fit models or launch a repair matrix. A successful build alone does not establish that remote deployment has completed; inspect Actions / Pages status for the current commit.

The retained [MIT license](LICENSE) covers first-party software. Dataset-derived DBLP replay retains CC BY 4.0 and its required attribution; other sources keep their own terms. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). No third-party paper full text, credentials, environment, sealed-test asset or private manuscript is published here.