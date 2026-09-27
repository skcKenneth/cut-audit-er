# V7 primary-work comparison and inspection record

Checked 27 September 2026. This records a response to simulated reviewer feedback,
not an actual conference review or an exhaustive novelty proof. Full-text access,
publication metadata, and scientific claims are kept separate. No third-party
full text is added to the local release packages.

| Primary work and text actually inspected | Existing result relevant to V7 | Narrow role and remaining limitation |
|---|---|---|
| Whang, Lofgren and Garcia-Molina, *Question Selection for Crowd Entity Resolution*, PVLDB 6(6):349--360, 2013, DOI 10.14778/2536336.2536337. Archived author/publisher PDF text re-read at sections 3.2--3.3 and Algorithm 1; official PDF open failed this round. | Possible worlds, answer-conditioned ER outputs and expected quality already drive question choice; exhaustive expected accuracy and its complexity precede this project. | V7 cannot claim first exact world evaluation, first conditioning, or a generally new expected-quality query method. Its controls isolate a particular frozen deletion-only proxy's expected ordering failure under an explicitly legal partition law; they do not claim Whang's method has the same flaw. |
| Elmachtoub and Grigas, *Smart “Predict, then Optimize”*, Management Science 68(1):9--26, 2022, DOI 10.1287/mnsc.2020.3922; author HTML full text available and section 4 inspected. | Predictive accuracy and downstream decision loss differ; decision-aware objectives have an established theory. | Exact marginal scores do not certify this ER batch utility. No new predictor, training loss or general decision-focused theory is introduced. |
| Higham, *The Accuracy of Floating Point Summation*, SIAM J. Sci. Comput. 14(4):783--799, 1993. Author 17-page PDF inspected, especially sections 1--3, Eq. (1.2), Eq. (2.6) and general addition trees in section 3. | Classical signed summation-error bounds and order-dependent arithmetic are established. Page 784 expressly assumes no underflow. | Cite the gamma summation foundation; preserve separate project derivation for endpoint changes, orientation asymmetry, gradual-underflow additions, exact operation order and outward final operations. A citation alone does not prove the binary64 certificate. |
| Guo et al., *Limited Query Graph Connectivity Test*, AAAI 38(18):20718--20725, 2024, DOI 10.1609/aaai.v38i18.30059; retained V6 author full-text inspection. | Paid edge tests, complete cut/path certification, limited planning and query bounds. | Here certification concerns the computed score in a saved candidate pool, not a new limited-query connectivity principle. |
| Leskovec et al., *Cost-effective Outbreak Detection in Networks*, KDD 2007, pp.420--429; retained full-text CELF comparison. | Lazy upper-bound screening and reducing complete evaluations are established. | Same-pool counts demonstrate what this certificate skips; they are not a new lazy-search principle, submodular guarantee or wall-time speedup. |
| Meduri et al., *A Comprehensive Benchmark Framework for Active Learning Methods in Entity Matching*, SIGMOD 2020, pp.1133--1147, DOI 10.1145/3318464.3380597; retained full-text comparison. | Quality, labeling effort and computational cost are already evaluated jointly. | Report complete costs transparently; additional access counts or logs alone are not a research contribution. |
| Peeters et al., *WDC Products: A Multi-Dimensional Entity Matching Benchmark*, EDBT 2024, pp.22--33, DOI 10.48786/edbt.2024.03; original dataset source and frozen source manifests retained. | Corner-case fraction, unseen entities and training-size variants define distinct evaluation conditions. | State the actual 50% corner-case, multiclass, zero-unseen (fully seen), large release. Provider parts are pooled and whole entities reassigned; provider fully seen does not mean role leakage. Automatic WDC cluster labels are benchmark references, not certified product identity. |
| TransClean, ALMSER, GraphCR, Alper, PERC and batched-oracle ER | Query scoring, graph-based ER, repair, clustering reliability and changed supervision/oracle units have close precedents. | Their detailed version/status limitations remain in review_v6/LITERATURE_MATRIX.md and earlier full-text records. Native TransClean/GraphCR evaluation is incomplete; mincut_proxy stays an adapter and no SOTA superiority is claimed. |

## Exact new claims to test, not novelty by naming

1. A fixed-pool certificate can exclude additional full scoring as a means to
   alter the current proxy winner, while saying nothing about expected value.
2. An exact-marginal four-node tree law witnesses a specific conditionalization
   limitation of this proxy, without candidate omission, batch product error or
   new FN confounding. The claim requires execution against the frozen source.
3. A Bayes-optimal fixed-pool control demonstrates why a high positive hindsight
   gap frequency is not an error rate. The EVPI identity itself is standard
   algebra and receives no novelty claim.
4. Natural saved-state evidence remains retrospective and dependent, with unknown
   conditional laws and incomplete large-component coverage. It cannot inherit
   the constructed world's mechanism diagnosis by analogy.

The scientific risk remains that a correct diagnosis of one local heuristic may
have insufficient wider importance for a full paper. Demonstrating correct
implementation, adding a proposition, or accumulating artifact tests does not
resolve that judgment. No acceptance prediction is supplied.

## Source links and limitations

- Whang official source: https://www.vldb.org/pvldb/vol6/p349-whang.pdf
  Retained first-party inspection input:
  `research/literature/sources_other_20260914/whang2013.txt`.
- SPO author text: https://arxiv.org/html/1710.08005
- Higham author PDF: https://nhigham.com/wp-content/uploads/2023/10/high93s.pdf
- ACIIDS official submission requirements checked at
  https://aciids.pwr.edu.pl/2027/submit.html: standard full-paper length12--15pages
  including references. No reduction of scientific standards follows from that
  formatting target.

The proposal mentioned Birge (1982) but the earlier full-text request was403.
V7 does not pretend to have inspected that full text and need not cite it for a
self-contained elementary identity. No exhaustive exclusion claim is made.
