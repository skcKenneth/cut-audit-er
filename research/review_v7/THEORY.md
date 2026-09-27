# V7: distinguish hindsight advantage from a known-law scoring error

Status: mathematical derivation. Execution and independent implementation checks
are recorded separately in the versioned results and validation receipts.
This file changes no selector. The V5 numerical implementation and V6 natural
state audit remain immutable. All new probability laws are constructed controls,
not learned or estimated natural-data distributions.

## 1. Fixed-pool value of information identity

Condition on the complete visible state h. Let P be a fixed finite set containing
the actual action a and a zero-valued no-action alternative. Define v_y(Q) as
single-batch FP+FN reduction divided by the entire batch query count, with v_y(0)=0.
The chosen a cannot use the current unknown reference y. Write mu(Q)=E[v_Y(Q)|h].
Then, by adding and subtracting max_Q mu(Q),

    E[max_Q v_Y(Q)-v_Y(a)|h]
      = (E[max_Q v_Y(Q)|h]-max_Q mu(Q))
        + (max_Q mu(Q)-mu(a)).

Both terms are nonnegative: expectation dominates each expected action value,
and the maximum dominates the selected expected value. The first is perfect
information value for this fixed pool and one-batch criterion; the second is its
expected decision gap. This is standard decision-theoretic algebra, not a novel
regret theorem. If the action is randomized, condition also on its independent
random seed, or average the corresponding selected value afterwards.

If a_s is the deterministic maximum of the implemented proxy using the same tie
rule, the second term can be written

    [max_Q mu(Q)-mu(a_s)] + [mu(a_s)-mu(a)].

The last term need not be nonnegative. A valid fixed-pool choice certificate makes
a=a_s and sets this term to zero; it does not identify the first bracket. Fallback
queries are not silently promoted to positive-plan proxy winners. A single
reference partition at each natural state does not identify the conditional law
or either expectation above. In particular 211/241 is not an error-rate estimate.

## 2. Exact fixed-bond value under an explicitly known partition law

At one fixed state H, let Q be a legal bond: removing all its edges splits one
component into connected sides U,W, while removing any proper subset leaves that
component connected. Let w=|Q|, C=|U||W| and A={all queried Q edges are negative}.
All w answers are paid even after a positive answer. Let pi=P(A|h)>0 and
m_A=sum_{u in U,v in W} P(Y(u)=Y(v)|A,h). For lambda=1,

    mu(Q)=pi(C-2m_A)/w.

Proof: outside A, only a proper subset of the bond is removed and the predicted
partition is unchanged, so gain is zero. On A the C cross pairs are disconnected;
each true-negative pair removes one FP and each true-positive pair adds one FN.
Taking conditional expectation gives C-2m_A, then multiplying by pi and dividing
by the fully paid w gives the expression. If pi=0, mu(Q)=0 directly and m_A is
undefined, not imputed as an observed conditional quantity.

Let q be the product approximation and m_tilde the endpoint-adjusted marginal
sum in the ideal-real existing proxy s=q(C-2m_tilde)/w. Exact algebra gives

    mu-s = [(pi-q)(C-2m_tilde)-2pi(m_A-m_tilde)]/w.

These are signed, order-dependent substitution effects with interaction; they are
not a unique causal allocation. Natural graphs have no identified pi or m_A, so
this decomposition is confined to the known-law controls. Binary64 s_float is
reported separately from rational s; the numerical certificate bounds s_float,
not mu or the ideal-real formula.

## 3. Initial-state tree proposition and exact-marginal counterexample

Fix a tree T. Independently delete each tree edge e with probability theta_e and
define the reference entities as the connected components after these deletions.
All generated references are equivalence relations. For u,v, their exact same-
entity marginal is the product of (1-theta_e) on their unique tree path. At the
initial visible graph T with no paid observations, querying e has expected gain

    mu({e})=theta_e |U_e||W_e|.

Proof: the answer is negative exactly when e was deleted in the sampled world.
On that event no same-entity pair can cross its tree cut, so all C cross pairs
are FP and the query removes exactly C FP with zero new FN. On a positive answer
the graph remains unchanged. This proposition is initial-state and model-specific;
it is not advice to omit FN protection in general ER.

For the path 1--2--3--4 with theta=(7/20,3/10,7/20), exact adjacent marginals are
(13/20,7/10,13/20), distance-two marginals 91/200, and p14=1183/4000. The ideal-real
proxy is 20979/40000=.524475 at each outer edge and 9531/20000=.476550 in the middle.
Expected gains are 21/20=1.05 and 6/5=1.2, respectively. Thus the proxy's outer-edge
maximum has expected gap 3/20=.15 despite exact marginals. All actions are
singletons, all three bridges are in the full pool, and q=pi for each singleton:
the mechanism is failure to update the other cross-cut probabilities conditional
on the negative answer, without a batch-product or candidate-cap confound.

The equal-cut control theta=(3/10,3/10,3/10) has ideal-real outer/middle scores
2001/5000=.4002 and 2031/5000=.4062. The middle action also maximizes true expected
gain (6/5 versus 9/10), so its expected gap is zero. Both laws have eight worlds.
Their exact scores preserve just the path edges at threshold .6, but no record
texts or matcher are generated, so neither verifies the full text-to-graph pipe.

## 4. Two other fixed controls

**Bayes-optimal hindsight negative control.** There are 100 disjoint two-node
components with independent negative probabilities (.10,.09,...,.09), no shared
entities across components, and budget one. The first edge is optimal in
expectation, with expected gap zero. Nevertheless positive hindsight gap has
probability .9(1-.91^99), approximately .8999206877. It is an analytic calculation,
not a 2^100-world enumeration, natural null distribution, p-value or new dataset.

**Correlated two-edge bond.** Two triangles A,B have two connector edges, and an
independent two-node component R has one edge. A and B are one entity with
probability 3/4, otherwise distinct; R's two records match independently with
probability 3/4. Cross-component records never match. All four worlds are valid
partitions, with probabilities 9/16,3/16,3/16,1/16. The two-edge bond has pi=1/4,
q=1/16, C=9, m_tilde=21/4, m_A=0. Its original score is -3/64; exact expected gain
per paid answer is 9/8. The R singleton is 1/4 under both criteria.

The four offline substitutions for Q are original -3/64, pi-only -3/16,
m_A-only 9/32, and both 9/8. The joint-probability substitution alone makes its
negative score more negative. These are explanatory oracle calculations, not
four new policies. The graph is exogenous: top-10/.6 on all .75 cross-block
marginals would also add the other cross-block edges, so graph provenance must
not be described as the natural matcher pipeline. Full batch commitment retains
both charges even when its first answer is positive.

## 5. Numerical order and Higham scope

Keep the exact frozen order in `completion_score`: `cross_sum` first; create a
dict from paid observations and update it with candidate negatives; for each
crossing correction form `fl(int(answer)-p_uv)` then add it to the current sum;
form `c=fl(1+lambda)`, `u=fl(C-fl(c*m_hat))`; form q_hat as the ordered product of
`fl(1-p_e)` using `math.prod`; return `fl(fl(q_hat*u)/w)`. NumPy reductions use
binary64 addition trees. Node/adjacency and observation insertion orders are
preserved. Supported runtime and source hashes are recorded, not assumed portable
under arbitrary reassociation, precision reduction, or flush-to-zero.

Higham (1993), sections 2--3, supplies summation-error analysis under its stated
rounding model; page 784 explicitly excludes underflow. It is not a citation for
the project's whole certificate. The project's gamma_K K bound separately
accounts for signed endpoint corrections and approximate matrix symmetry.
Its gradual-underflow addition argument uses the fact that binary64 operands
are multiples of the least subnormal, so a subnormal exact sum/difference is
representable. Products/divisions use the identical computed q_hat and outward
positive operations, including positive operations rounded to zero. Exact zeros,
infinite unprunable bounds, and nonfinite score rejection retain their existing
semantics. Source: https://nhigham.com/wp-content/uploads/2023/10/high93s.pdf

## 6. Proof-versus-validation boundary

Root execution must independently verify all 20 finite worlds, exact marginals,
unchanged `completion_score`, full-pool tie-selected actions, direct partition
gain/FP/FN/cost, the analytic Bayes control, and evaluator isolation before these
derived numbers are reported as executed controls. No new natural acquisition,
fit, method, or external source is authorized. Positive expected gap in the path
does not assign that mechanism to any of the 211 natural hindsight-gap states.
