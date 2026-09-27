"""Reference-only finite probability-law evaluation after visible outputs freeze.

Never imports or invokes a selector. Exact rational expectations and pair-count
recomputation are distinct from acquisition and from conditional natural-data
estimation. Unknown event conditionals remain undefined, not invented zeros.
"""
from __future__ import annotations
from fractions import Fraction
from itertools import combinations, product
import math

from .common import fingerprint, require, validate_spec


def labels(nodes, edges):
    """Independent union-find partition; does not use the engine's metrics."""
    parent = {u: u for u in nodes}
    def find(u):
        while parent[u] != u:
            u = parent[u]
        return u
    for u, v in edges:
        a, b = find(u), find(v)
        parent[max(a, b)] = min(a, b)
    return {u: find(u) for u in nodes}


def reference_worlds(spec, visible):
    probabilities = validate_spec(spec)
    require(visible['spec_sha256'] == fingerprint(spec), 'Spec/visible hash mismatch')
    require(spec['kind'] != 'matching', '100-edge law is analytic; do not enumerate 2^100 worlds')
    worlds = []
    if spec['kind'] == 'path':
        switches = len(probabilities)
    else:
        switches = 2
    for index, flags in enumerate(product((False, True), repeat=switches)):
        weight = math.prod(p if flag else 1-p for p, flag in zip(probabilities, flags))
        if weight == 0:
            continue
        if spec['kind'] == 'path':
            kept = [e for e, cut in zip(visible['edges'], flags) if not cut]
        else:
            kept = [e for e in visible['edges'] if not
                    ({e[0][0], e[1][0]} == {'A', 'B'} and flags[0]) and not
                    (e[0][0] == e[1][0] == 'R' and flags[1])]
        worlds.append({'id': f'w{index:02}', 'weight': str(weight),
                       'reference': labels(visible['nodes'], kept)})
    validate_worlds(visible, worlds)
    return worlds


def validate_worlds(visible, worlds):
    require(worlds and len({w['id'] for w in worlds}) == len(worlds), 'Missing/duplicate worlds')
    require(all(Fraction(w['weight']) > 0 for w in worlds), 'World weights must be positive')
    require(sum(Fraction(w['weight']) for w in worlds) == 1, 'World weights do not sum to one')
    require(all(set(w['reference']) == set(visible['nodes']) for w in worlds), 'Reference membership mismatch')
    for i, u in enumerate(visible['nodes']):
        for j, v in enumerate(visible['nodes']):
            p = sum(Fraction(w['weight']) for w in worlds if w['reference'][u] == w['reference'][v])
            require(p == Fraction(visible['exact_marginals'][i][j]), 'World law does not reproduce exact marginals')


def counts(nodes, predicted, reference):
    fp = fn = 0
    for u, v in combinations(nodes, 2):
        same_p, same_y = predicted[u] == predicted[v], reference[u] == reference[v]
        fp += int(same_p and not same_y)
        fn += int(same_y and not same_p)
    return {'fp': fp, 'fn': fn, 'loss': fp+fn}


def realized_batch(visible, reference, action):
    nodes, edges = visible['nodes'], [tuple(e) for e in visible['edges']]
    require(set(reference) == set(nodes), 'Reference membership mismatch')
    q = [tuple(e) for e in action]
    require(len(q) == len(set(q)) and all(e in edges for e in q), 'Invalid batch edges')
    require(len(q) <= visible['budget'], 'Batch exceeds requested budget')
    initial = labels(nodes, edges)
    before = counts(nodes, initial, reference)
    current, events = list(edges), []
    for number, (u, v) in enumerate(q, 1):
        positive = reference[u] == reference[v]
        if not positive:
            current.remove((u, v))
        state = labels(nodes, current)
        events.append({'position': number, 'answer': positive, 'partition': state,
                       **counts(nodes, state, reference)})
    after = counts(nodes, labels(nodes, current), reference)
    fp_removed, fn_added = before['fp']-after['fp'], after['fn']-before['fn']
    require(fp_removed >= 0 and fn_added >= 0, 'Deletion FP/FN monotonicity failed')
    gain = fp_removed-fn_added
    require(gain == before['loss']-after['loss'], 'Gain conservation failed')
    return {'before': before, 'after': after, 'fp_removed': fp_removed, 'fn_added': fn_added,
            'gain': gain, 'cost': len(q), 'value': str(Fraction(gain, len(q)) if q else Fraction(0)),
            'events': events, 'no_op': not q}


def rational_proxy(visible, candidate):
    q = [tuple(e) for e in candidate['action']]
    nodes = visible['nodes']
    p = lambda u, v: Fraction(visible['exact_marginals'][nodes.index(u)][nodes.index(v)])
    left, right = candidate['partition']
    cross = len(left)*len(right)
    require(q and cross, 'Zero-width or empty-side candidate')
    negative_product = math.prod(1-p(*e) for e in q)
    adjusted = sum(p(u, v) for u in left for v in right) - sum(p(*e) for e in q)
    return negative_product * (cross-2*adjusted)/len(q), negative_product, adjusted


def packed_fraction(row, name, value):
    row[name] = None if value is None else str(value)
    row[name+'_float'] = None if value is None else float(value)


def evaluate_case(spec, decision):
    visible = decision['visible']
    require(decision['visible_sha256'] == fingerprint(visible), 'Visible decision hash mismatch')
    require(visible['spec_sha256'] == fingerprint(spec), 'Source specification hash mismatch')
    require(decision['pool_count'] == len(decision['candidates']), 'Missing candidates')
    validate_spec(spec)
    if spec['kind'] == 'matching':
        return analytic_matching(spec, decision)
    worlds = reference_worlds(spec, visible)
    selected = tuple(sorted(tuple(e) for e in decision['selected_action']))
    rows, world_rows, values_by_world = [], [], {w['id']: [Fraction(0)] for w in worlds}
    selected_world = {}
    for index, candidate in enumerate(decision['candidates']):
        action = candidate['action']
        q = tuple(sorted(tuple(e) for e in action))
        row = {'case': spec['id'], 'action_id': f'q{index:03}', 'action': action, 'depth': len(q),
               'selected': q == selected, 'proxy_float': candidate['proxy_float'],
               'was_scored': candidate['was_scored']}
        exact_proxy, neg_product, adjusted = rational_proxy(visible, candidate)
        pi = marginal_mass = expected = fp = fn = Fraction(0)
        left, right = candidate['partition']
        for w in worlds:
            reference, weight = w['reference'], Fraction(w['weight'])
            result = realized_batch(visible, reference, action)
            val = Fraction(result['value'])
            expected += weight*val
            fp += weight*result['fp_removed']
            fn += weight*result['fn_added']
            values_by_world[w['id']].append(val)
            if q == selected:
                selected_world[w['id']] = val
            all_negative = all(reference[u] != reference[v] for u, v in q)
            if all_negative:
                pi += weight
                marginal_mass += weight * sum(reference[u] == reference[v] for u in left for v in right)
            world_rows.append({'case': spec['id'], 'world_id': w['id'], 'weight': w['weight'],
                               'action_id': row['action_id'], 'selected': row['selected'], **result})
        conditional = marginal_mass/pi if pi else None
        c, width = len(left)*len(right), len(q)
        both = (pi*c-2*marginal_mass)/width
        require(expected == both, 'Independent partition expectation disagrees with bond identity')
        probability_only = pi*(c-2*adjusted)/width
        conditional_only = neg_product*(c-2*conditional)/width if conditional is not None else None
        probability_term = (pi-neg_product)*(c-2*adjusted)/width
        conditional_term = -2*(marginal_mass-pi*adjusted)/width
        require(expected-exact_proxy == probability_term+conditional_term, 'Proxy decomposition failed')
        values = {'proxy_exact': exact_proxy, 'expected_value': expected,
                  'exact_all_negative': pi, 'product_all_negative': neg_product,
                  'conditional_same_sum': conditional, 'endpoint_adjusted_same_sum': adjusted,
                  'probability_only': probability_only, 'conditional_only': conditional_only,
                  'both_exact': both, 'expected_fp_removed': fp, 'expected_fn_added': fn,
                  'probability_approximation_term': probability_term,
                  'conditional_approximation_term': conditional_term,
                  'binary64_score_minus_exact': Fraction.from_float(candidate['proxy_float'])-exact_proxy}
        for name, value in values.items():
            packed_fraction(row, name, value)
        rows.append(row)
    # Fixed controls have positive certified selections; fallback is never silently
    # treated as a pool winner. It would require a separate reference row.
    require(len(selected_world) == len(worlds), 'Actual action absent from evaluated pool')
    best = max([Fraction(0)] + [Fraction(r['expected_value']) for r in rows])
    selected_mu = sum(Fraction(w['weight'])*selected_world[w['id']] for w in worlds)
    perfect = sum(Fraction(w['weight'])*max(values_by_world[w['id']]) for w in worlds)
    p_gap = sum(Fraction(w['weight']) for w in worlds if max(values_by_world[w['id']]) > selected_world[w['id']])
    summary = base_summary(spec, decision, len(worlds))
    for name, value in {'selected_expected_value': selected_mu, 'optimal_expected_value': best,
                        'expected_decision_gap': best-selected_mu, 'evpi': perfect-best,
                        'expected_hindsight_gap': perfect-selected_mu,
                        'positive_hindsight_probability': p_gap}.items():
        packed_fraction(summary, name, value)
    require(Fraction(summary['expected_hindsight_gap']) == Fraction(summary['evpi'])+Fraction(summary['expected_decision_gap']), 'EVPI identity failed')
    return {'summary': summary, 'actions': rows, 'worlds': worlds, 'world_actions': world_rows}


def base_summary(spec, decision, world_count):
    return {'case': spec['id'], 'kind': spec['kind'], 'status': 'passed',
            'world_count': world_count, 'budget': spec['budget'],
            'selected_action': decision['selected_action'],
            'selected_proxy_float': decision['selection_info'].get('selected_proxy_score'),
            'pool_count': decision['pool_count'], 'scored_count': decision['scored_count'],
            'certificate_status': decision['certificate_status'],
            'positive_pool_certificate': decision['positive_pool_certificate'],
            'new_oracle_answers': 0, 'scope': 'known-law initial single-batch per-paid-query diagnostic'}


def analytic_matching(spec, decision):
    visible = decision['visible']
    require(spec['kind'] == 'matching' and spec['budget'] == 1, 'Analytic matching scope')
    probabilities = validate_spec(spec)
    error = [probabilities[0]]+[probabilities[1]]*(spec['pair_count']-1)
    selected = decision['selected_action']
    require(len(selected) == 1 and selected[0] in visible['edges'], 'Invalid analytic selected action')
    selected_index = visible['edges'].index(selected[0])
    expected = error[selected_index]
    perfect = 1-math.prod(1-p for p in error)
    p_gap = (1-expected)*(1-math.prod(1-p for i, p in enumerate(error) if i != selected_index))
    rows = []
    for index, candidate in enumerate(decision['candidates']):
        exact, neg_product, adjusted = rational_proxy(visible, candidate)
        value = error[visible['edges'].index(candidate['action'][0])]
        require(exact == value and adjusted == 0, 'Matching proxy must equal true expectation')
        row = {'case': spec['id'], 'action_id': f'q{index:03}', 'action': candidate['action'],
               'depth': 1, 'selected': candidate['action'] == selected,
               'proxy_float': candidate['proxy_float'], 'was_scored': candidate['was_scored']}
        for name, val in {'proxy_exact': exact, 'expected_value': value, 'exact_all_negative': value,
                          'product_all_negative': neg_product, 'conditional_same_sum': Fraction(0) if value else None,
                          'endpoint_adjusted_same_sum': adjusted, 'probability_only': value,
                          'conditional_only': value if value else None, 'both_exact': value,
                          'expected_fp_removed': value, 'expected_fn_added': Fraction(0),
                          'probability_approximation_term': Fraction(0), 'conditional_approximation_term': Fraction(0),
                          'binary64_score_minus_exact': Fraction.from_float(candidate['proxy_float'])-exact}.items():
            packed_fraction(row, name, val)
        rows.append(row)
    summary = base_summary(spec, decision, None)
    summary.update(analytic_world_count=str(2**spec['pair_count']), materialized_worlds=0,
                   independent_pair_error_law=True)
    for name, val in {'selected_expected_value': expected, 'optimal_expected_value': max(error),
                      'expected_decision_gap': max(error)-expected, 'evpi': perfect-max(error),
                      'expected_hindsight_gap': perfect-expected,
                      'positive_hindsight_probability': p_gap}.items():
        packed_fraction(summary, name, val)
    require(Fraction(summary['expected_hindsight_gap']) == Fraction(summary['evpi'])+Fraction(summary['expected_decision_gap']), 'Analytic EVPI identity')
    return {'summary': summary, 'actions': rows, 'worlds': [], 'world_actions': []}
