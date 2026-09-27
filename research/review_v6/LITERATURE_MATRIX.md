# V6 literature and claim boundaries

Checked 27 September2026. This is a source-based comparison, not proof that no
similar diagnostic has ever appeared. Original frozen V4/V5 matrices and their
full-text receipts remain unchanged. No cited paper is treated as reproduced.

| Primary work / inspected version | Established overlap | Defensible scope of this study; remaining limitation |
|---|---|---|
| Elmachtoub and Grigas, *Smart “Predict, then Optimize”*, Management Science68(1):9–26 (2022), DOI10.1287/mnsc.2020.3922. Publisher record inspected; mathematical discussion inspected in author arXiv1710.08005v5 (2020), sections1–3. | Prediction losses and downstream decision losses differ; task-aware training is established. | Our evaluator checks an unchanged ER acquisition proxy on saved states. It does not introduce decision-focused training. A realized one-batch oracle gap is not an estimate of conditional expected regret or a diagnosis of calibration failure. |
| Guo et al., *Limited Query Graph Connectivity Test*, AAAI38(18):20718–20725 (2024), DOI10.1609/aaai.v38i18.30059; author full text arXiv2302.13036v3. | Paid edge queries, cut verification, finite-horizon search and lower bounds have direct precedent. | Here certification concerns the implemented score maximum in one restricted candidate pool; it does not solve the adaptive connectivity policy or certify actual repair loss. |
| Whang et al., *Question Selection for Crowd Entity Resolution*, PVLDB6(6):349–360 (2013), DOI10.14778/2536336.2536337; preserved full text sections4.2.1,5,6.2.4. | Expected ER quality, question selection, pruning and multiple questions are established. | We empirically check whether a particular screening explanation can be excluded on saved verification-only states. General utility-aware querying is not new. |
| Leskovec et al., *Cost-effective Outbreak Detection in Networks*, KDD2007; author full text section4.2 (CELF). | Lazy/upper-bound selection avoids unnecessary objective evaluations. | Our elementary pool-maximum certificate is not a new screening principle and supplies no submodularity or approximation guarantee for true repair. |
| Meduri et al., *A Comprehensive Benchmark Framework for Active Learning Methods in Entity Matching*, inspected author text arXiv2003.13114v1 and preserved V4 publication audit. | Label cost, predictive quality and latency must be evaluated together. | Score-evaluation counts, logical matrix accesses and observed selector/worker times are separately measured. Counting reductions alone does not establish an efficiency contribution. |
| TransClean (IEEE Access2025), GraphCR (JDIQ2025), ALMSER (ISWC2021), and Alper (KDD2026). Publication/version details and full-text scope remain in the preserved V5 matrix. | Graph-based ER repair, active selection, cuts and label propagation overlap strongly. | Our adapters have changed action/supervision contracts; native TransClean/GraphCR comparisons remain incomplete. No native-reproduction or SOTA-superiority claim follows. |
| ALASKA provider and Crescenzi et al. full text arXiv2101.11259v2, sections3.3–5. | Annotated-record reference semantics and heterogeneous product matching benchmark. | Camera is a prospective source candidate, not an executed experiment. Retrieval, archive notices, actual mapping and membership must pass before any fit or result can exist. Products do not create a new semantic domain relative to WDC. |

## Specific contribution to assess

The potential empirical contribution is an auditable exclusion of particular
search explanations in verification-only ER, together with measured realized
single-batch differences, coverage and full computational costs. Exclusion is
conditional on source, state, pool, numeric semantics and deterministic tie
rules. This is stronger than counting beneficial unselected witnesses, but
its scientific usefulness and generality still require evidence. Correct
implementation, more figures or a new diagnostic name are not novelty evidence.

## Primary links and version disclosure

- SPO publisher: https://pubsonline.informs.org/doi/10.1287/mnsc.2020.3922
- SPO inspected author full text: https://arxiv.org/html/1710.08005 (v5,19Nov2020).
  Publisher online date12Mar2021; journal issue2022. Do not label it only a preprint.
- Guo publisher: https://ojs.aaai.org/index.php/AAAI/article/view/30059
- Guo inspected author full text: https://arxiv.org/html/2302.13036v3
- Whang: https://www.vldb.org/pvldb/vol6/p349-whang.pdf
- CELF author full text: https://cs.stanford.edu/people/jure/pubs/detect-kdd07.pdf
- Meduri inspected author full text: https://arxiv.org/html/2003.13114v1
- ALASKA provider: https://github.com/merialdo/research.alaska
- ALASKA inspected full text: https://arxiv.org/html/2101.11259v2
- ACIIDS current guidelines: https://aciids.pwr.edu.pl/2027/submit.html

An NSF repository copy of SPO timed out during this round. The accessible
author full text and publisher record above were inspected instead. Copyrighted
third-party full texts are not bundled in any delivery ZIP.
