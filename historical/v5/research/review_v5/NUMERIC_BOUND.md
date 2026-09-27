# V5 numerical bound and certificate scope

The certificate ranks the **unchanged computed binary64 completion score** over
the legal, budget-feasible pool searched at one decision. It is not a bound on
true repair loss, an exact-real proxy certificate, a calibration assertion, or
an adaptive-policy guarantee. Large components retain an incomplete legacy
generator; a certificate does not extend to their omitted bonds. There is no
novelty claim for this elementary numerical envelope or screening rule.

## Inputs and arithmetic assumptions

`PairScores` supplies immutable finite binary64 entries in [0,1]. Its existing
approximate-symmetry check is retained; exact symmetry is not silently assumed.
Paid observations are canonical distinct pairs with Boolean answers and must
belong to the verified set. Candidate edges are unverified. Lambda is finite
and nonnegative. The score implementation and its order of endpoint corrections
are unchanged. We assume IEEE-754 round-to-nearest binary64, gradual underflow,
and a NumPy sum implemented by binary64 additions (sequential or pairwise),
without fast-math reassociation into lower precision or flush-to-zero.

For a cut with C=|L||R| cross pairs, let r be the number of paid observations
plus the candidate width d. This conservatively bounds the number of crossing
endpoint replacements, including any irrelevant observations. Set K=C+2r and
u=2^-53. The implementation rejects K>=2^53, invalid inputs, and nonfinite fully
computed scores; it does not convert such failures into certified decisions.

## Summation, endpoint cancellation, and asymmetry

Before rounding, the cross sum followed by endpoint corrections is a linear
form with at most C+2r signed inputs, total absolute input sum at most C+2r,
and at most K rounded addition/subtraction operations along any dependency
path. Thus its absolute rounding error is bounded by

    gamma_K K = K^2 / (2^53-K).

The rational expression is evaluated with `Fraction`, then converted upward
to binary64 by comparing the rounded float to the exact rational. It is not an
arbitrary epsilon. Addition/subtraction whose exact result is subnormal is
exact under gradual underflow: binary64 operands are integer multiples of the
least subnormal. Consequently the addition/subtraction relative-error model
used here does not lose a separate underflow term near cancellation.

The initial dense sum may read M[v,u], while the canonical endpoint correction
reads M[u,v]. At the first UB decision of each run we scan the entire visible
matrix to obtain an outward bound delta on max |M-M.T|. In real arithmetic the
endpoint-adjusted sum is at least -r delta, even with approximate symmetry.
Its computed value therefore is at least -E, where E is an outward evaluation
of gamma_K K + r delta. A positive endpoint replacement contributes 1, a
negative one contributes 0, up to that orientation error.

The scan inspects two N-by-N operands. It charges **2N^2 score-entry accesses**
to `scores.calls` and separately reports `numeric_scan_score_entry_reads` and
`numeric_preprocessing_seconds`. The result is cached only in run-private state
for that same immutable matrix object. New runs or a different matrix scan
again. This is additional preprocessing cost, not free probability access.

## Final operations and screening

Let c_hat=fl(1+lambda), and let q_hat be the identical ordered floating product
of (1-p_e) used by `completion_score`. The implementation computes outward:

    Ubar = up(C + up(c_hat E))
    Sbar = up(up(q_hat Ubar) / d).

Every positive multiply/add/divide uses `nextafter` toward +infinity, including
a positive multiplication/division rounded to zero. Exact zero operands are
handled separately. If q_hat=0, a finite old score is signed zero and the bound
is zero. Infinite conservative bounds are retained as unprunable (JSON stores
null together with `upper_bound_finite=false`); NaN full scores fail closed.
Monotonicity of the rounded operations gives S_float<=Sbar. The incumbent is
the actual computed score, so its own exact-real lower bound is not required.

Candidates are ordered by descending Sbar, then old width/lexicographic tie
rules. At most 64 full completion scores are evaluated. A positive incumbent
is certified early only when its actual score **strictly exceeds** the next
unscored upper bound. Equality cannot certify; when all searched candidates
were scored, the old exact floating-score/width/lexicographic argmax suffices.
At the score limit without separation, a positive incumbent is still selected
with `score_limit_uncertified`. BC fallback occurs only without a positive
evaluated incumbent. The cap-control arm uses the original mean-BC cap and
reports `bc_cap_uncertified` if legal union candidates remain unscored.

An all-scored pool can have a certified **nonpositive** incumbent and therefore
still fall back to BC. In that case the certificate does not certify the
returned BC query as the pool argmax. Reports must distinguish positive-plan
certificates from fallback cases (`fallback` is present and
`candidate_trace.selected_plan` is empty).

`candidate_trace.capped_order` records a true candidate-cap stage: BC-truncated
for the cap control, identity on the raw union for UB arms. The separate
`evaluation_prefix_order` records the at-most-64 score allocation. Actual
`scored_order` may be shorter after a strict certificate. These stages must not
be conflated when diagnosing omitted opportunities.

## Validation boundary

The V5 tests compare enumeration with independent vertex bipartitions, stress
the bound against the unchanged implementation under endpoint cancellation,
approximate asymmetry and extreme representable values, check strict ties and
uncertified positive incumbents, and compare old semantic traces/access counts
with the preserved V4 source in separate interpreters. Tests are software
validation, not scientific evidence of repair improvement. Formal results and
missing cases are recorded separately under the frozen V5 protocol.
