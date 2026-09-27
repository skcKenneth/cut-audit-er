"""Strict Cora citation-ER inspection and conversion; no R code is executed.

The provider's original positive-pair gold and updated entity mapping must
agree. Missing labels are never inferred to be nonmatches. The inspected 0.1.0
release fails this requirement and is deliberately not normalized for a pilot.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import math
from numbers import Integral, Real
from pathlib import Path
import re
import unicodedata
import warnings

import pandas as pd

TEXT_FIELDS = ('title', 'authors', 'book_title', 'journal', 'year')
RECORD_FIELDS = ('id', 'title', 'book_title', 'authors', 'address', 'date', 'year',
                 'editor', 'journal', 'volume', 'pages', 'publisher', 'institution',
                 'type', 'tech', 'note')
PINNED_FILES = {
    'cran_cora.RData': ('cora', 'dfecf0cac44501e4f6ffdbfa79234980d9379bae033c946f13d1ecf9099332c1'),
    'cran_cora_gold_update.RData': ('cora_gold_update', '52c80612e53b576f91be74901e930db48dc2714a601ad7bbd587c2659030ea2f'),
    'cran_cora_gold.RData': ('cora_gold', 'b5f48a1743805346be975f8a55e6ea8bc233911d49d2e05fa8961719a8c3df03'),
}


class CoraGoldConflict(ValueError):
    def __init__(self, message, details):
        super().__init__(message)
        self.details = details


def _integer_id(value, field):
    if isinstance(value, bool) or pd.isna(value):
        raise ValueError('Missing or invalid ' + field)
    if isinstance(value, Integral):
        result = int(value)
    elif isinstance(value, Real):
        if not math.isfinite(value) or not float(value).is_integer() or abs(value) > 2**53:
            raise ValueError('Nonintegral or unsafe ' + field)
        result = int(value)
    elif isinstance(value, str) and re.fullmatch(r'[1-9][0-9]*', value):
        result = int(value)
    else:
        raise ValueError('Invalid ' + field)
    if result <= 0:
        raise ValueError('Nonpositive ' + field)
    return result


def _field_text(value):
    if pd.isna(value):
        return ''
    if not isinstance(value, str):
        raise ValueError('Observed citation fields must be strings or missing')
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value)).strip()


def _prepare(records, updated_gold, positive_pairs):
    if list(records.columns) != list(RECORD_FIELDS):
        raise ValueError('Cora record schema must match the inspected 16 columns')
    if list(updated_gold.columns) != ['cora_id', 'unique_id']:
        raise ValueError('Updated gold schema must be cora_id, unique_id')
    if list(positive_pairs.columns) != ['id1', 'id2']:
        raise ValueError('Original gold schema must be id1, id2')
    texts = {}
    for row in records.to_dict('records'):
        identifier = _integer_id(row['id'], 'record ID')
        if identifier in texts:
            raise ValueError('Duplicate Cora record ID')
        text = ' '.join(part for part in (_field_text(row[f]) for f in TEXT_FIELDS) if part)
        if not text:
            raise ValueError('Record has no nonblank selected text; no record is silently removed')
        texts[identifier] = text
    if not texts:
        raise ValueError('Cora records are empty')
    labels = {}
    for record, entity in updated_gold.itertuples(index=False, name=None):
        record = _integer_id(record, 'mapping record ID')
        entity = _integer_id(entity, 'entity ID')
        if record in labels:
            raise ValueError('Duplicate or conflicting record in updated gold')
        labels[record] = entity
    if set(texts) != set(labels):
        raise ValueError('Updated gold must cover every record exactly once; no singleton inference')
    pairs = set()
    for first, second in positive_pairs.itertuples(index=False, name=None):
        edge = tuple(sorted((_integer_id(first, 'pair ID'), _integer_id(second, 'pair ID'))))
        if edge[0] == edge[1] or any(node not in texts for node in edge):
            raise ValueError('Original positive pair has a self-pair or unknown ID')
        if edge in pairs:
            raise ValueError('Duplicate unordered original positive pair')
        pairs.add(edge)
    return texts, labels, pairs


def inspect_cora_tables(records, updated_gold, positive_pairs):
    """Return data-quality counts only; never produce splits or graph outcomes."""
    texts, labels, pairs = _prepare(records, updated_gold, positive_pairs)
    groups = defaultdict(list)
    for record, entity in sorted(labels.items()):
        groups[entity].append(record)
    mapping_pairs = {(first, second) for group in groups.values()
                     for i, first in enumerate(group) for second in group[i + 1:]}
    disagreements = sorted(pairs - mapping_pairs)
    additions = sorted(mapping_pairs - pairs)
    parent = {record: record for record in texts}

    def find(node):
        while node != parent[node]:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    covered = set()
    for a, b in sorted(pairs):
        covered.update((a, b))
        a, b = sorted((find(a), find(b)))
        parent[b] = a
    component_sizes = Counter(find(node) for node in texts)
    entity_sizes = Counter(labels.values())
    unlinked = sorted(set(texts) - covered)
    text_entities = defaultdict(set)
    for record, text in texts.items():
        text_entities[text].add(labels[record])
    return {
        'dataset': 'cora_citation_entity_resolution', 'provider_version': '0.1.0',
        'status': 'GOLD_SOURCES_AGREE' if not disagreements and not additions else 'REJECTED_CROSS_SOURCE_GOLD_CONFLICT',
        'records': len(texts), 'record_columns': list(RECORD_FIELDS),
        'updated_mapping_rows': len(updated_gold), 'updated_mapping_entities': len(groups),
        'updated_mapping_singleton_entities': sum(size == 1 for size in entity_sizes.values()),
        'updated_mapping_largest_entity': max(entity_sizes.values()),
        'updated_entity_size_histogram': dict(sorted(Counter(entity_sizes.values()).items())),
        'record_id_duplicates': 0, 'mapping_id_duplicates': 0,
        'missing_mapping_ids': 0, 'unknown_mapping_ids': 0, 'unknown_pair_ids': 0,
        'original_unique_positive_pairs': len(pairs),
        'updated_mapping_implied_positive_pairs': len(mapping_pairs),
        'original_pairs_conflicting_with_updated_mapping': len(disagreements),
        'updated_positive_pairs_absent_from_original_gold': len(additions),
        'conflicting_pair_examples': [list(edge) for edge in disagreements[:10]],
        'added_pair_examples': [list(edge) for edge in additions[:10]],
        'original_pair_components_including_unlinked': len(component_sizes),
        'original_pair_largest_component': max(component_sizes.values()),
        'original_component_size_histogram': dict(sorted(Counter(component_sizes.values()).items())),
        'original_pair_component_closure_pairs': sum(n * (n - 1) // 2 for n in component_sizes.values()),
        'original_components_are_complete_cliques': len(pairs) == sum(n * (n - 1) // 2 for n in component_sizes.values()),
        'records_unlinked_in_original_pair_gold': len(unlinked),
        'unlinked_records_marked_singleton_by_updated_gold': sum(entity_sizes[labels[n]] == 1 for n in unlinked),
        'unlinked_records_marked_nonsingleton_by_updated_gold': [n for n in unlinked if entity_sizes[labels[n]] != 1],
        'missing_by_observed_field': {field: int(records[field].isna().sum()) for field in RECORD_FIELDS if field != 'id'},
        'observed_text_fields': list(TEXT_FIELDS),
        'text_normalization': 'NFKC; collapse whitespace; concatenate nonmissing fields in fixed order',
        'nonempty_selected_text_records': len(texts), 'distinct_selected_texts': len(set(texts.values())),
        'repeated_selected_text_rows': len(texts) - len(set(texts.values())),
        'identical_text_groups_with_different_updated_labels': sum(len(v) > 1 for v in text_entities.values()),
        'excluded_from_text': ['id', 'cora_id', 'unique_id', 'all gold pair labels'],
        'records_removed': 0, 'missing_labels_inferred_as_nonmatches': False,
        'gold_repaired_or_replaced': False, 'splits_generated': False,
        'matcher_or_policy_executed': False, 'test_evaluated': False,
    }


def cora_records(records, updated_gold, positive_pairs):
    """Convert only if both authoritative gold representations fully agree."""
    report = inspect_cora_tables(records, updated_gold, positive_pairs)
    if report['status'] != 'GOLD_SOURCES_AGREE':
        raise CoraGoldConflict('Original Cora pair gold and updated entity mapping disagree; conversion refused', report)
    texts, labels, _ = _prepare(records, updated_gold, positive_pairs)

    def opaque(kind, value):
        return hashlib.sha256(('cora_citation_er_' + kind + '\0' + str(value)).encode()).hexdigest()

    frame = pd.DataFrame([
        {'record_id': 'r_' + opaque('record', record), 'entity_id': 'e_' + opaque('entity', labels[record]),
         'text': text, 'source': 'cora_citation_er_0_1_0'} for record, text in texts.items()
    ]).sort_values('record_id', kind='stable').reset_index(drop=True)
    return frame, report


def read_cora_sources(raw_directory):
    """Read pinned small RData objects with a Python parser, not an R runtime."""
    import importlib.metadata
    try:
        import rdata
    except ImportError as error:
        raise RuntimeError('Inspection requires optional rdata==1.1.0 and xarray==2025.12.0') from error
    base = Path(raw_directory)
    objects, file_records, reader_warnings = {}, [], []
    for filename, (name, expected) in PINNED_FILES.items():
        path = base / filename
        content = path.read_bytes()
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            raise ValueError('Pinned Cora source hash differs: ' + filename)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            loaded = rdata.read_rda(path)
        if set(loaded) != {name} or not isinstance(loaded[name], pd.DataFrame):
            raise ValueError('Unexpected RData object schema: ' + filename)
        objects[name] = loaded[name]
        reader_warnings.extend(str(w.message) for w in caught)
        file_records.append({'filename': filename, 'bytes': len(content), 'sha256': actual, 'object': name})
    metadata = {'pinned_inputs': file_records, 'reader': 'rdata.read_rda; no R execution',
                'reader_versions': {name: importlib.metadata.version(name) for name in ('rdata', 'xarray', 'pandas', 'numpy')},
                'reader_warnings': sorted(set(reader_warnings)), 'downloaded_code_executed': False}
    return objects['cora'], objects['cora_gold_update'], objects['cora_gold'], metadata
