# V6 mathematical scope and independent validation obligations

The exact implementation and full numerical derivation remain frozen in
`research/review_v5/NUMERIC_BOUND.md` and `THEORY.md`. This text does not change
the method. Neither a proof nor a finite test is a measured repair result.

## Searched-pool certification

At a saved state let P be the legal, budget-feasible searched pool, s_float its
unchanged binary64 score, and b(Q) a conservative bound on that computed score.
If the incumbent Q* has s_float(Q*) > max b(Q) over all unscored members,
then none can tie or exceed it. Evaluated ties are resolved by the same width
and lexicographic rule as exhaustive evaluation. Q* therefore equals the
deterministic winner from complete scoring of P. Exhaustive scoring provides
the independent check; increasing only the number of scores cannot change Q*.

An equality does not permit strict certification. An uncertified score-limit
termination does not satisfy the premise. A nonpositive-pool certificate does
not certify the subsequent BC fallback. Candidate completeness within small
components is a separate statement; large-component omissions remain possible.
This is a standard finite branch-and-bound argument, not a new theorem about
globally optimal querying or actual expected utility.

## Numerical envelope to include in the main manuscript

Assume immutable finite scores in[0,1], round-to-nearest IEEE754 binary64 with
gradual underflow, binary64 additions in NumPy sums and the frozen endpoint
correction/product order. For C cross pairs and at most r endpoint replacements,
K=C+2r<2^53 bounds both absolute operand mass and addition-path length. An
outward rational evaluation of K^2/(2^53-K) bounds additive rounding error.
Let delta be the outward measured matrix-asymmetry bound; add r*delta before
outward evaluation to obtain E. With the same computed q_hat and
c_hat=fl(1+lambda), compute

    Ubar=up(C+up(c_hat*E));  Sbar=up(up(q_hat*Ubar)/|Q|).

This bounds the implemented score, including signed endpoint cancellation;
it is not an exact-real proxy, probabilistic calibration or real-gain bound.
Infinite bounds are unprunable; invalid/nonfinite full scores fail closed.
The implementation's exact-zero and positive-underflow handling are retained.
Every step and assumption, not a single arbitrary epsilon, is needed.

## Realized fixed-batch diagnostic

Given a complete evaluator reference y, only the negative queried edges Q-_y
are removed. Directly recompute the partition after that entire fixed batch.
All |Q| labels cost one each, including positive and ineffective answers.
Let g_y(Q)=L_y(H)-L_y(H\Q-_y), v_y(Q)=g_y(Q)/|Q|. Decompose signed gain as
FP removed minus FN added; both counts are nonnegative under edge deletion.
Include the selected action and a zero-gain no-action reference in comparisons.

If only a subset is evaluated, its best observed value is a lower bound on
the full comparison-pool maximum. Do not report an exact oracle gap for a
partial state. A beneficial unselected Q need not beat the selected batch.
Even a positive exact realized gap is a hindsight, one-batch comparison. It
does not isolate miscalibration, estimate conditional expectation, imply a
deployable gold-aware alternative, or causally allocate terminal loss.

## Observability

The existing H0/H9 original-edge answer equivalence couples every permitted
adaptive transcript, while the two references can have distinct FN headroom.
It assumes no query of nonedges, no known true cluster count and no extra
visible distinguishing information. It does not rule out statistical inference
under additional assumptions. Re-evaluating the same trace under two references
neither purchases another trajectory nor creates independent observations.

## Required falsification checks

Independent candidate enumeration/full-score checks must reject a bad bound,
wrong candidate/tie winner or replay divergence. Direct pair/partition counts
must agree with the reported gain accounting. Changing evaluator gold while
holding paid answers fixed must leave every selector/visible audit field
unchanged. A counterexample blocks external acquisition and is recorded as
an implementation failure, never used to decorate the research narrative.
