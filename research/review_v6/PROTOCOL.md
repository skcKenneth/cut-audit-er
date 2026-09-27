# V6: certified proxy search, realized single-batch value, and cost

Status: user-authorized local development protocol, 27 September 2026.
The direct implementation request authorizes this new mechanism study. It does
not rewrite V5's failed method-progression gate, reopen sealed test, authorize
publication, or create a human approval record. All historical evidence and
archives remain preserved. The manuscript target is an aspirational full paper,
not a finding of novelty or acceptance readiness.

## Question and fixed scope

When an unchanged planner certifies its implemented proxy maximum in a fixed
candidate pool, which realized repair opportunities remain, which search
explanations are excluded, and which explanations remain unidentified?
Prediction quality versus downstream decision quality, bounded querying,
candidate enumeration and upper-bound screening have prior work. Neither this
distinction nor a correct numerical certificate is independently claimed new.

No selector, utility, depth, cap, calibration recipe, seed or batch commitment
is changed. Existing acquisitions are not repeated. Source hashes are checked
against the V5 scientific snapshot, rather than silently replacing that freeze.

## Offline visible-state audit

The declared existing scope is all Full (`cut_plan_cover_fixed`) batch-start
states: 241 natural states (WDC73, DBLP84, V4 DBLP cohort84) and 60 synthetic
states, in separately executed budget runs. Synthetic states are acquired
once and evaluated under both H0 and H9; no additional query is purchased.
Order is requested budget, original dataset/condition order, then batch index.

A visible-only entry point reads the initial ordered graph, scores, ordered
purchased answers, saved candidate stages, selected action, remaining budget,
and source manifest. It must not accept evaluator gold, headroom or outcomes.
It reconstructs actual states with the saved answers, fully scores every legal
member of the searched pool without the online64-evaluation limit, and checks
each computed upper bound, the original binary64 score/tie order, the selected
action and the saved certificate. Preserve graph/node/adjacency and correction
iteration order. Gold never supplies an unrecorded replay answer.

Separate three scopes: complete scoring of the searched pool; complete eligible
bonds in components with at most16nodes/16edges and width<=min(4,remaining);
and all graph-wide actions, which are not certified on oversized components.
Independently enumerate vertex bipartitions for the small-component coverage
check. Distinguish strict-UB pruning, score-limit exhaustion, method filtering,
nonpositive-pool fallback, and execution failure. A fallback is not certified
as the positive-pool argmax. Close ties cannot pass strict separation.

The elementary corollary is conditional on unchanged state, candidate pool,
computed score and tie rule: a valid strict certificate means scoring more
members of that same pool cannot change that decision. It says nothing about
omitted candidates, deeper search, a changed proxy, or the optimal adaptive policy.

## Independent reference evaluation

Only after the visible audit is saved and hashed may a separate evaluator
process load a reference. For each legal fixed batch Q, it retains positive
edges, deletes only reference-negative edges Q-, counts every |Q| answer, and
directly recomputes connected-component FP/FN on all record pairs:

    g_y(Q) = L_y(H) - L_y(H minus Q-)
    v_y(Q) = g_y(Q) / |Q|.

Report FP removed, FN added, signed net gain, width, per-query gain, selected
action value and the best value over the comparison pool including selected
action and the no-action value0. Fallbacks are separately marked. A positive
but unselected witness alone is not evidence of a worse choice. A partial audit
only gives a witnessed lower bound on the best gain/gap, never an exact maximum.
These are clairvoyant realized one-batch comparisons, not expected regret,
calibration-error estimates, deployable decisions, or additive causal parts of
whole-trajectory loss. Synthetic H0/H9 are dependent evaluations, not real data.

Keep every declared state and missing reason. Also report deterministic unique
visible-state summaries using ordered graph, scores, complete ordered purchased
history, remaining budget and candidate pool/rules. Repeated prefixes/budgets,
multiple witnesses and both references are not independent samples; no pooled
significance test or population failure-rate claim is made. States are those
visited by Full, not an outcome-independent sample of all reachable states.

## Offline resources and stopping

CPU1; PYTHONHASHSEED0; BLAS/OpenMP1 before worker startup. Natural audit worker
result deadline120seconds, cumulative suite2700seconds per cohort; synthetic
worker30seconds and suite900seconds. The visible audit and evaluator share the
declared cohort allowance; record actual startup/IPC/cleanup and wall time.
Each declared state is consumed once. Do not retry a timed-out state, substitute
a prefix, increase enumeration limits, or select replacement states. Save all
unstarted/failed/partial rows. Offline time and score accesses are separate
from the historical online selector costs.

A certificate, replay, source or isolation inconsistency blocks external
acquisition pending a documented correction and passing correctness checks;
it is not interpreted as a research finding. A pure offline timeout remains
unknown and does not change the prespecified external matrix. Preparation and
correctness fixtures are not additional research acquisitions.

## New prospective ALASKA mechanism branch

V5's21 `not_started_gate` rows remain unchanged. This protocol asks a different
question and does not assert that the V5 progression gate passed. Only official
ALASKA Camera is eligible; inspect provider, exact version/archive hashes,
license scope/notices, annotation completeness/conflicts and prior exposure.
Expected official version:29787records,24sources,3865annotated records and
103annotated entities. A version/qualification mismatch stops this branch;
do not change category, benchmark, cohort or seed. Unannotated records are
excluded, never treated as singleton entities. This is another product
benchmark, not a new semantic domain relative to WDC.

Retain the existing deterministic whole-entity allocator: seed20260919,
normalized-file-hash ordering,4000record capacity, floor entity role counts
45%train/15%calibration/20%completion/remainder evaluation, exact UTF-8 ties
and record order, intact evaluation including isolates capped at1500records.
Capacity failure is ineligible, not permission to redraw. Page title only;
character2-4gram TF-IDF with the existing four-feature logistic matcher and
independent Platt calibration; matcher seed7/maxpairs50000; threshold0.6;
top10 character-cosine blocking. Fit the new train/calibration recipe once,
never refit old models. Completion remains unused. Matcher stage900seconds;
graph stage600seconds; failed stages are not retried.

Freeze methodology, source and fixed slots before acquisition of Camera;
freeze provenance/membership before fitting; freeze graph/scores/config before
repair. No formal test data are accessed. No self-approved HUMAN_APPROVAL.

Seven methods in order: weighted BC, raw fixed, existing adaptive,
coverage+BCcap, bound-only, Full, Full singleton. Budgets12,24,48, budget then
method order,21cold-start one-attempt slots. CPU1/BLAS1,120second worker result
deadline and2700second suite limit. These are not strict OS wall-time guarantees.
Keep all timeouts, failure and unstarted rows; no retries or prefix completion.
Primary metric remains FP+FN with separate FP/FN, paid answers, trajectories,
completion and full costs. Existing V5 four-arm costs remain contemporary to
one another; cross-round runtimes are not a robust speed comparison.

Apply the same audit/evaluator to every completed external Full batch under
its own natural-cohort2700second offline allowance. The external conclusion
can support existence of a certified-choice/realized-gap pattern, fail to
reproduce it on fully audited informative states, or remain inconclusive from
no initial error, insufficient opportunity/coverage or missing runs. If Full
changes trajectories or improves quality, report that honestly. A positive
clairvoyant gap does not uniquely identify miscalibration or prove a bad
expected decision. No universal generalization follows from one cohort.

## Validation, writing and local delivery

Run full pytest before and after substantive implementation and graph/policy
smoke. Test bound/full-score agreement, >64/ties/cancellation/nonpositive and
fallback cases, independent partition FP/FN accounting, fixed-batch payment,
gold isolation, source tampering, membership overlap, missing/zero-denominator
states and cold-cache separation. Existing finite fixtures are correctness
checks, not new scientific results. Do not add settings after viewing outcomes.

The main English LNCS manuscript is14-15pages, normal layout, with six figures,
schematic bypage2 and empirical figure bypage5. Put the essential binary64
bound assumptions/proof and excluded-versus-unexcluded explanations in main.
Correct the residual-bridge generator description. Distinguish score count,
logical accesses and measured time; nested timers are not additive and single
observations do not establish robust speed ratios. Keep native-method fidelity
limits, incomplete large components and dependent-state limits visible.

Deliver Overleaf, public-repository and private-handoff V6 ZIPs, main/supplement/
combinedPDF, Traditional-Chinese decision and simulated-review response,
GPT audit prompt, internalSHA256, ZIP hashes and actual clean-extraction
receipts. Exclude environments, caches, credentials, sealed test and unlicensed
raw/record-level data. WDC stays aggregate-only. Clearly list external archival
dependencies; finite checks do not reproduce every historical experiment.
No deployment, submission or acceptance claim. Preserve REFRAME when evidence
does not establish a publication-level contribution.
