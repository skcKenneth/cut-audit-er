# V4 fixed constructed mechanism study

This is a prospective, finite synthetic mechanism study, authorized by the user
in the current V4 implementation request. It is not natural-error evidence,
external validation, a human study, a new selector, or a publication-readiness
claim. No sealed test, fitting, download, native comparator or parameter search
is authorized by this protocol. Previous failures and freezes remain unchanged.

## Observable construction and reference separation

Use IDs r0 through r8, inserted in sorted order. Blocks A={r0,r1,r2},
B={r3,r4,r5}, C={r6,r7,r8} are triangles. For k=1,2,3, insert the matching
connectors (r_i,r_(3+i)) and (r_(3+i),r_(6+i)), i=0,...,k-1. Insert all edges in
lexical order. There are nine vertices and 9+2k edges, at most fifteen.

k is the width of EACH designated boundary; the total gold-negative edge count
is 2k. A connected graph with just one negative edge cannot have positive
deletion-only FN headroom, so a literal one-total-negative-edge by positive-
headroom cell would be impossible.

The visible constructor takes only k and profile, never a reference partition.
Every within-block off-diagonal score is .95 and each other cross-block pair is
.10, except connectors. Uniform connectors have p=.70. Ranked connectors use
(.80,.70,.60) truncated to k, identically on the two boundaries. Diagonal=1.
These are deliberately specified synthetic inputs, not calibrated probabilities
or natural matcher errors. Ranked reuses the existing barrier fixture recipe;
it changes confidence and heterogeneity together for k<3 and is not an isolated
variance or calibration intervention. No score adjustment after outcomes.

Separate offline reference H0 labels A,B,C distinctly; H9 labels A=C and B
distinctly. H0 has initial FP27/FN0 and headroom0. H9 has FP18/FN0 and headroom9.
Both yield exactly the same answer to EVERY original-edge query. No H9 labels,
FN headroom, offline opportunity or optimum enters selection. Acquisition uses
the compatible A/B/C oracle partition required by the existing run_audit API;
its intermediate H0 metrics are not feedback. Offline code evaluates the same
stored partitions under both references. One transcript supports two dependent
reference evaluations, not two acquisitions or independent experimental units.

## Frozen grid and execution

Methods: edge_betweenness (weighted BC), cut_plan_fixed (Raw), and
cut_plan_fixed_singleton (Singleton). The latter generates the common depth<=4,
cap64 pool, caps/validates first, then filters to singletons without refill.
Keep lambda1, noise0, seed7, all paid costs, tie rules, fallback and committed
batch semantics. Do not change the selector, mincut, search depth or calibration.

Run order is budget [1,2,3,4,6], k [1,2,3], profile [uniform,ranked], then method
[BC,Raw,Singleton]. These are separately executed requested-budget runs, each
from the initial graph and a cold private cache. Ninety acquisition runs yield
at most 288 paid answers and 180 offline reference endpoints. B0 is an initial
state/bound check, not an additional acquisition. There is no permutation/seed
sweep, random replication, inference over independent populations or best-case
selection. Lexical ties and this limited deterministic graph family constrain
generalization.

CPU1; set PYTHONHASHSEED=0 and OMP_NUM_THREADS=OPENBLAS_NUM_THREADS=MKL_NUM_THREADS=1
before interpreter startup. The existing bounded_audit worker has a 30-second
result deadline. The 900-second acquisition suite cap is checked before each
launch; the final worker gets at most the remaining allowance. Startup, result
transfer, cleanup and actual wall time are reported separately. Synchronous
startup/IPC mean this is not a strict OS wall-time guarantee. Do not extend
limits or retry failed, timed-out or unstarted cells. An exclusive consumption
record prevents relaunch. The source/config/input freeze is checked before and
after each worker. A worker that cannot be stopped aborts subsequent launches.

## Offline mechanism analysis

Keep physical acquisitions/costs separate from the two reference evaluations.
For incomplete workers keep journal-confirmed paid lower/upper bounds; exact
total physical paid cost is null when uncertain. Events CSV contains completed
run receipts only, with incomplete cost bounds separately in acquisitions CSV.
Reconstruct every graph state and partition from saved answers. Replaying the
same selector on STORED answers checks action order, observations, complete
batch boundaries, logical score accesses, stop reason and semantic metadata;
it makes no new oracle query. Separate private diagnostic workspaces export
the full generated set, pre-cap order, cap, validated/scored orders and utility
ranking. Diagnostic score accesses/time never enter acquisition cost. For BC,
the common planner pool is explicitly a counterfactual diagnostic, not work
done by BC during acquisition.

At each batch state enumerate all eligible all-negative bonds of width at most
min(4, remaining budget), independently of the bounded generator. Report the
existence of multiedge completion opportunities separately from positive
immediate FP+FN gain. For each reference retain opportunity-to-generated,
capped/validated, scored and selected membership. After trajectories diverge,
run-wide candidate totals do not have common denominators. Singleton can
complete multiedge cuts using repeated single queries; it is not a general
optimal-single-step comparator.

Primary contrasts remain L_raw-L_singleton and L_raw-L_BC, with FP/FN components
and first paid sequence divergence. Retain ties, BC/Singleton wins, generator
misses and negative effects. The post-cap action-set intervention supports only
this controlled family, not a causal explanation of all WDC/DBLP differences.
Timing is descriptive under fixed order; no speed superiority claim.

## Exact diagnostic and analytic expectations

Reuse finite_budget.diagnose_graph with caps16 nodes/16 edges and B0..6. There
are at most six negative edges and 64 subsets per structural/reference case.
Check the result against independent NetworkX/direct-pair exhaustive enumeration
and the following analytic expectations (these are predictions, not results):

H0: L*(B)=27 for B<k, 9 for k<=B<2k, 0 for B>=2k.
H9: L*(B)=18 for B<2k, 9 for B>=2k.

Completing one boundary at H9 removes nine FP but adds nine FN. Both boundaries
eventually reduce loss. Thus absence of a positive immediate-gain bond is not
absence of an eventual repair opportunity. H0 at k>1 has multiedge opportunity
without headroom; H9 at k1 has headroom without requiring multiedge actions.

Bounds know every answer without paying discovery costs. They are clairvoyant
optimistic diagnostics, not deployable/adaptive attainability guarantees. A
method-to-bound gap is not a pure sorting error or a causal decomposition.

## Validation, provenance and commands

Before formal acquisition, run full workspace pytest and graph/policy smoke;
include their actual receipts in the V4 root validation record. This module's
freeze pins a successful command receipt, its stdout/stderr hashes, all current
first-party src files, this script/test/config/protocol, exact-bound dependencies
and the command wrapper. It generates and hashes six observable inputs and two
separate reference maps before any formal outcome. No human approval is claimed.

Required tests cover constructor independence, paired edge-answer identity,
independent bounds including true pairs across components, B0/monotonicity,
headroom vs opportunity, post-cap filtering, positive and non-split negative
answers, committed batches, budget boundaries, gold-blind replay, deterministic
cache isolation, source/hash rejection, missing outcomes and no retry. Bounded
unit-test executions are software validation, not formal study counts.

From repository root (use the project Python executable in place of `python`):

```text
python -m pytest -q tests/test_review_v4_synthetic.py
python scripts/review_v4/synthetic.py freeze --config configs/review_v4_synthetic.json --out outputs/session_20260927_v4/synthetic/scientific_freeze.json --snapshot outputs/session_20260927_v4/synthetic/source_snapshot --validation outputs/session_20260927_v4/baseline_pinned/command.json
python scripts/run_logged.py --out outputs/session_20260927_v4/synthetic/run_command --timeout 1100 -- python scripts/review_v4/synthetic.py run --config configs/review_v4_synthetic.json --freeze outputs/session_20260927_v4/synthetic/scientific_freeze.json --out outputs/session_20260927_v4/synthetic/study
python scripts/run_logged.py --out outputs/session_20260927_v4/synthetic/analyze_command --timeout 300 -- python scripts/review_v4/synthetic.py analyze --study outputs/session_20260927_v4/synthetic/study --out outputs/session_20260927_v4/synthetic/analysis
python scripts/run_logged.py --out outputs/session_20260927_v4/synthetic/check_command --timeout 300 -- python scripts/review_v4/synthetic.py check --study outputs/session_20260927_v4/synthetic/study --analysis outputs/session_20260927_v4/synthetic/analysis
```

Run only after the root task coordinates the single-CPU study slot. Analysis
and check are offline; finite public replay is distinct from full historical
recomputation. Preserve previous outputs and never promote a prefix to a missing
requested-budget endpoint. CSV tables, complete replay JSON, failure inventory,
commands and hashes accompany any manuscript figures.
