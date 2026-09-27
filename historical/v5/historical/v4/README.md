# CUT-AUDIT-ER · V4 evidence package

**Opportunity → actual use → incremental value in verification-only cluster repair.**
[繁體中文](README.zh-Hant.md)

This local inspection package contains first-party code, saved research evidence,
finite replay assets, six figures and a lightweight bilingual website. The full
English paper, Overleaf source and private review materials are delivered in
separate ZIPs. This release does not claim a conference-ready contribution or
general superiority. No GitHub push, remote workflow or Pages deployment is part
of this local delivery.

## Read the evidence in three groups

| Evidence | Fixed scope | What it can establish |
|---|---|---|
| Exposed development graphs | The previous 18 WDC/DBLP–ACM requested-budget runs | Local mechanism contrasts and failure cases; these graphs already informed development. |
| Controlled synthetic family | 90 planned selector executions; 180 dependent offline reference evaluations | Whether a cut opportunity exists, is used and changes an endpoint in this constructed family. Two references reuse the same acquisition and never count as independent observations. |
| Previously unused DBLP–ACM cohort | Eligibility review of all 910 omitted records; at most nine frozen method–budget runs | A limited same-benchmark check conditional on qualification, not a second semantic domain or a sealed-test result. |

Read `evidence/manifest.json` for actual completion/qualification status and paid
cost bounds. The planned grid is not a claim that every run completed. Missing
endpoints remain missing; stored prefixes do not replace them. The website builds
its counts and tables from that manifest and the canonical CSVs.

The recorded V4 cycle completed **89/90 synthetic acquisitions and 178/180
reference evaluations**. One interrupted acquisition was not retried; its
unknown cost leaves total physical paid answers at **287–288**. The qualified
DBLP cohort completed **9/9** cases. Completion alone is not evidence of benefit.

The primary outcome remains **FP+FN**. Raw-minus-singleton and raw-minus-BC
contrasts retain zero differences, losses and FN trade-offs. Gold structure and
clairvoyant bounds are offline diagnostics. An exact diagnostic does not pay
answer-discovery costs and is not an adaptive policy guarantee. Basic accounting,
bounded cuts and caching are not claimed as new contributions.

## Inspect and verify locally

Use **Python 3.12** and the pinned dependencies. From this package root:

```sh
python -m pip install -r requirements-public.txt
python -m pip install --no-deps -e .
python -m pytest -q
python scripts/validate_evidence.py --evidence evidence
python scripts/check_bundled_replays.py --root . --receipt build/replay_check.json
python scripts/make_figures.py --evidence evidence --out build/figures
python scripts/build_site.py --out _site --figures build/figures
python -m http.server 8765 --directory _site
```

Open `http://localhost:8765` for the bilingual reading view. The generated HTML
also works without network access when opened directly. Use a fresh output path
for a second site build. Commands fail on mismatched evidence hashes, broken
figure provenance or inconsistent saved replay; no new answer may be obtained to
repair a replay failure.

For deterministic replay, set `PYTHONHASHSEED=0` and
`OMP_NUM_THREADS=OPENBLAS_NUM_THREADS=MKL_NUM_THREADS=1` before starting Python.
In PowerShell:

```powershell
$env:PYTHONHASHSEED='0'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
```

The included CI definition uses these settings with Python 3.12. It checks tests,
evidence, replay, figures and the site. It does not acquire labels, download
benchmark records, fit models or rerun the research grid. Its optional Pages job
requires a separate explicit manual deployment request and defaults to disabled;
local verification is not evidence of a remote CI or deployment result.

## File guide and replay boundary

- `evidence/`: canonical natural and synthetic tables, historical missing cases,
  manifests and cost/completion status. Synthetic acquisition cost is counted once.
- `replay/synthetic/{study,analysis}/`: saved constructed inputs, answers and full
  offline evidence; checks reconstruct candidate order, partitions and both
  reference evaluations without new queries.
- `replay/dblp_exposed/`: the declared DBLP saved-answer replay bundle.
- `replay/dblp_unused/`: present only when that cohort has qualified, completed
  replay cases. A missing bundle is disclosed, not replaced by another cohort.
- `src/cut_audit_er/` and `tests/`: actual first-party engine and finite correctness
  tests. Synthetic software tests are separate from the formal synthetic study.
- `figures/`: `fig01_contract`, `fig02_structure`, `fig03_outcomes`,
  `fig04_events`, `fig05_controlled`, `fig06_use` in PDF/SVG/PNG.
- `site/` and `scripts/build_site.py`: static bilingual presentation generated
  from verified evidence; no accounts, tracking or paid service.

Qualified DBLP bundles use order-preserving aliases, frozen scores, paid answers
and a separate offline evaluator reference. They omit original record IDs and
bibliographic text. WDC pair identities and full reconstruction assets are not
redistributed; its public event arithmetic does not independently verify the
private identity-level divergence claim. See [reproduction scope](REPRODUCTION_SCOPE.md)
and [source notices](THIRD_PARTY_NOTICES.md) for the precise included assets.

The compact package cannot independently recompute every historical experiment.
Historical freezes, source assets and permissions remain external where listed.
All historical failures and 42 unrun comparison cells remain visible.
`mincut_proxy` is **not a complete TransClean reproduction**; incomplete native
GraphCR/TransClean comparisons do not support a state-of-the-art ranking.
