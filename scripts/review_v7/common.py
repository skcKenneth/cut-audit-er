"""Dependency-light validation shared by isolated visible/reference processes."""
from fractions import Fraction
import hashlib
import json


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_spec(spec):
    common = {'id', 'kind', 'budget', 'error_probabilities'}
    require(isinstance(spec, dict) and spec.get('kind') in {'matching', 'path', 'cliques'}, 'Unknown case')
    expected = common | ({'pair_count'} if spec['kind'] == 'matching' else set())
    require(set(spec) == expected, 'Unexpected field: visible specifications cannot accept realized gold')
    require(isinstance(spec['id'], str) and spec['id'].replace('_', '').isalnum(), 'Unsafe case id')
    require(type(spec['budget']) is int and spec['budget'] in (1, 2), 'Unsupported initial budget')
    require(all(isinstance(p, str) for p in spec['error_probabilities']), 'Exact rational probability strings required')
    probabilities = tuple(Fraction(p) for p in spec['error_probabilities'])
    require(len(probabilities) == (3 if spec['kind'] == 'path' else 2), 'Probability count differs')
    require(all(0 <= p <= 1 for p in probabilities), 'Probability outside unit interval')
    if spec['kind'] == 'matching':
        require(type(spec['pair_count']) is int and 2 <= spec['pair_count'] <= 100, 'Matching size outside scope')
        require(spec['budget'] == 1, 'Analytic matching control requires B1')
    return probabilities
