"""Static presentation checks with constructed rows, never acquisition."""
from pathlib import Path

import pytest

from scripts import build_site as site


def inputs():
    natural = [{'dataset': dataset, 'status': 'completed'} for dataset in ('wdc', 'dblp_acm', 'dblp_unused')
               for _ in range(9)]
    synthetic = [{'status': 'completed'} for _ in range(178)] + [{'status': 'interrupted'} for _ in range(2)]
    manifest = {'counts': {'natural_slots': 27, 'natural_completed': 27,
                          'synthetic_acquisitions': 90, 'synthetic_acquisitions_completed': 89,
                          'synthetic_reference_evaluations': 180, 'synthetic_reference_evaluations_completed': 178,
                          'synthetic_paid_lower_bound': 287, 'synthetic_paid_upper_bound': 288},
                'study_status': {'synthetic': 'completed_with_missing', 'cohort': 'qualified_complete'}}
    return manifest, natural, synthetic


def test_counts_keep_reference_dependence_and_interrupted_cost_uncertainty():
    values = site.projection(*inputs())
    assert values['{{SYNTH_COMPLETED}}'] == '89' and values['{{SYNTH_PLANNED}}'] == '90'
    assert values['{{REFERENCE_COMPLETED}}'] == '178' and values['{{REFERENCE_PLANNED}}'] == '180'
    assert values['{{SYNTH_PAID}}'] == '287–288'
    assert values['{{COHORT_COMPLETED}}'] == '9'


def test_pending_cohort_is_not_reported_as_success():
    manifest, natural, synthetic = inputs()
    for row in natural:
        if row['dataset'] == 'dblp_unused':
            row['status'] = 'ineligible'
    manifest['counts']['natural_completed'] = 18
    manifest['study_status']['cohort'] = 'ineligible'
    projected = site.projection(manifest, natural, synthetic)
    assert projected['{{COHORT_COMPLETED}}'] == '0'
    assert projected['{{COHORT_STATUS}}'] == 'ineligible'


@pytest.mark.parametrize('key,value', [('natural_completed', 28), ('synthetic_acquisitions_completed', 90),
    ('synthetic_reference_evaluations', 178), ('synthetic_paid_upper_bound', 289)])
def test_count_or_paid_bound_contradiction_fails(key, value):
    manifest, natural, synthetic = inputs()
    manifest['counts'][key] = value
    with pytest.raises(ValueError):
        site.projection(manifest, natural, synthetic)


def test_missing_numeric_endpoint_and_html_fields_are_not_imputed():
    row = site.cells(['<script>', None, 0])
    assert '&lt;script&gt;' in row and '<script>' not in row
    assert '<td>—</td>' in row and '<td>0</td>' in row


def test_six_current_figures_and_no_stale_depth_or_cost_names():
    cards = site.figure_cards()
    assert cards.count('<article class="figure-card">') == 6
    assert 'fig05_controlled.svg' in cards and 'fig06_use.svg' in cards
    assert 'fig05_depth' not in cards and 'fig06_cost' not in cards


def test_local_link_checker_rejects_missing_and_escaping_links(tmp_path):
    index = tmp_path / 'index.html'
    index.write_text('<a href="missing.csv">bad</a>', encoding='utf-8')
    with pytest.raises(ValueError, match='Broken local'):
        site.check_links(tmp_path)
    index.write_text('<a href="../outside.csv">bad</a>', encoding='utf-8')
    with pytest.raises(ValueError, match='Broken local'):
        site.check_links(tmp_path)
    (tmp_path / 'ok.csv').write_text('a\n', encoding='utf-8')
    index.write_text('<a href="ok.csv">ok</a><a href="#evidence">jump</a>', encoding='utf-8')
    assert site.check_links(tmp_path) == 1


def test_workflow_never_deploys_from_push_or_pull_request():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / '.github/workflows/pages.yml').read_text(encoding='utf-8')
    assert 'default: false' in workflow
    assert workflow.count("if: github.event_name == 'workflow_dispatch' && inputs.deploy_pages") == 3
    assert "python-version: '3.12'" in workflow
    assert 'check_bundled_replays.py' in workflow
    assert 'synthetic.py run' not in workflow and 'run_audit' not in workflow
