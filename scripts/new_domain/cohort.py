"""Outcome-blind whole-entity cohort and roles from the frozen V2 protocol.

The caller hashes the complete normalized input before invoking this function.
This module neither reads external data nor fits, scores or queries anything.
Reference entity IDs are used solely for whole-entity grouping and separation.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
import hashlib
import json
import re


ROLE_NAMES = ('train', 'calibration', 'completion_fit', 'evaluation')
GRAPH_ROLES = frozenset(('completion_fit', 'evaluation'))


def _json_bytes(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def _string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a nonempty normalized string')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError(f'{field} must contain valid UTF-8 text') from exc
    return value


def ordered_ids_sha256(ids):
    """Unambiguous order-sensitive identity; JSON array, not newline joining."""
    return hashlib.sha256(_json_bytes(list(ids))).hexdigest()


def entity_sort_key(entity_id, normalized_data_sha256, seed=20260919):
    """Protocol-exact SHA256 key, with an explicit UTF-8 byte tie-breaker."""
    return (hashlib.sha256(_json_bytes([seed, normalized_data_sha256, entity_id])).hexdigest(),
            entity_id.encode('utf-8'))


def split_cohort(records: Iterable[Mapping], normalized_data_sha256: str, *,
                 seed: int = 20260919, record_cap: int = 4000,
                 graph_cap: int = 1500) -> tuple[dict[str, list[dict]], dict]:
    """Return role records and an auditable deterministic membership manifest.

    Defaults are the frozen scientific rule. Explicit parameters support small
    constructed tests; the study runner must bind their values in its config.
    ``normalized_data_sha256`` must identify the complete, pre-sampling input;
    its correspondence to a file is the caller's provenance responsibility.
    Input order never affects selection or output ordering. IDs are preserved
    exactly: no trimming, coercion, Unicode normalization or entity relabeling.
    """
    if not isinstance(normalized_data_sha256, str) or not re.fullmatch('[0-9a-f]{64}', normalized_data_sha256):
        raise ValueError('normalized_data_sha256 must be a lowercase 64-hex SHA256')
    if type(seed) is not int or seed < 0:
        raise ValueError('seed must be a nonnegative integer')
    for name, value in (('record_cap', record_cap), ('graph_cap', graph_cap)):
        if type(value) is not int or value < 1:
            raise ValueError(f'{name} must be a positive integer')

    groups = defaultdict(list)
    record_ids = set()
    for supplied in records:
        if not isinstance(supplied, Mapping):
            raise ValueError('Each normalized record must be a mapping')
        row = dict(supplied)
        for field in ('record_id', 'entity_id', 'text'):
            if field not in row:
                raise ValueError(f'Normalized record lacks {field}')
            _string(row[field], field)
        if row['record_id'] in record_ids:
            raise ValueError(f'Duplicate normalized record_id: {row["record_id"]!r}')
        record_ids.add(row['record_id'])
        groups[row['entity_id']].append(row)

    ordered_entities = sorted(groups, key=lambda entity: entity_sort_key(entity, normalized_data_sha256, seed))
    retained = []
    selected = []
    omitted = []
    used = 0
    for entity in ordered_entities:
        count = len(groups[entity])
        key = entity_sort_key(entity, normalized_data_sha256, seed)[0]
        entry = {'entity_id': entity, 'records': count, 'ordering_sha256': key}
        if count > record_cap:
            omitted.append({**entry, 'reason': 'entity_exceeds_record_cap',
                            'remaining_record_capacity': record_cap-used})
        elif count > record_cap-used:
            omitted.append({**entry, 'reason': 'insufficient_remaining_record_capacity',
                            'remaining_record_capacity': record_cap-used})
        else:
            retained.append(entity)
            selected.append(entry)
            used += count

    n = len(retained)
    counts = [45*n//100, 15*n//100, 20*n//100]
    counts.append(n-sum(counts))
    roles = {}
    role_manifest = {}
    offset = 0
    for role, count in zip(ROLE_NAMES, counts):
        entities = retained[offset:offset+count]
        offset += count
        rows = sorted((dict(row) for entity in entities for row in groups[entity]),
                      key=lambda row: row['record_id'].encode('utf-8'))
        ids = [row['record_id'] for row in rows]
        roles[role] = rows
        status = ('empty_role' if not rows else 'resource_ineligible'
                  if role in GRAPH_ROLES and len(rows) > graph_cap else 'eligible')
        role_manifest[role] = {
            'records': len(rows), 'entities': len(entities), 'entity_ids': entities,
            'record_ids': ids, 'entity_ids_sha256': ordered_ids_sha256(entities),
            'record_ids_sha256': ordered_ids_sha256(ids), 'status': status,
            'graph_record_cap': graph_cap if role in GRAPH_ROLES else None,
            'reason': ('no_entities_assigned_by_fixed_integer_rule' if not rows else
                       'intact_graph_exceeds_predeclared_record_cap' if status == 'resource_ineligible' else None),
        }

    entity_sets = [set(role_manifest[role]['entity_ids']) for role in ROLE_NAMES]
    record_sets = [set(role_manifest[role]['record_ids']) for role in ROLE_NAMES]
    entity_overlap = sum(len(entity_sets[i] & entity_sets[j]) for i in range(4) for j in range(i))
    record_overlap = sum(len(record_sets[i] & record_sets[j]) for i in range(4) for j in range(i))
    if entity_overlap or record_overlap or sum(len(rows) for rows in roles.values()) != used:
        raise AssertionError('Whole-entity assignment invariant failed')
    manifest = {
        'schema': 'cut-audit-whole-entity-cohort-v1',
        'normalized_data_sha256': normalized_data_sha256,
        'input_hash_scope': 'complete normalized input before deterministic sampling; supplied by caller',
        'seed': seed, 'record_cap': record_cap, 'graph_cap': graph_cap,
        'entity_order_rule': 'SHA256(UTF8 compact JSON [seed, normalized_data_sha256, exact entity_id]); UTF8 entity-ID bytes break ties',
        'role_rule': 'floor(45*n/100), floor(15*n/100), floor(20*n/100), all remaining; no second shuffle',
        'record_order_rule': 'ascending exact record-ID UTF8 bytes within each role',
        'membership_hash_rule': 'SHA256(UTF8 compact JSON ordered ID array), ensure_ascii=False, no BOM/newline',
        'input_records': len(record_ids), 'input_entities': len(groups),
        'selected_records': used, 'selected_entities': n,
        'omitted_records': len(record_ids)-used, 'omitted_entities': len(omitted),
        'remaining_record_capacity': record_cap-used,
        'selected': selected, 'omitted': omitted, 'roles': role_manifest,
        'record_overlap': record_overlap, 'entity_overlap': entity_overlap,
        'selection_uses_outcomes': False, 'evaluation_graph_count_if_eligible': 1,
        'eligibility_scope': 'Resource/empty-role checks only; vocabulary and sampled pair classes are checked during matcher fitting without rescue',
    }
    return roles, manifest
