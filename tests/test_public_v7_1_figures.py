"""Editorial verification only; unchanged V7 research evidence is read, not rerun."""
import importlib.util
import json
from pathlib import Path
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]

def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value

f=module('make_figures_v7_1')


def test_cost_editorial_labels_preserve_projection_and_canvas(tmp_path):
    f.v6.style()
    acquisitions=f.table(ROOT/'historical/v5/evidence','acquisitions')
    batches=f.table(ROOT/'historical/v5/evidence','batches')
    same=json.loads((ROOT/'evidence/same_pool_summary.json').read_text())
    old,expected=f._retained_cost(acquisitions,batches,same)
    plt.close(old)
    fig,actual=f.cost(acquisitions,batches,same)
    assert actual==expected
    assert fig.axes[1].get_xlabel().replace('\n',' ')=='Retained natural-run time total (seconds)'
    assert fig.axes[1].get_title(loc='left').replace('\n',' ')=='(b) Retained natural-run costs'
    fig.canvas.draw()
    renderer=fig.canvas.get_renderer()
    label=fig.axes[1].xaxis.label.get_window_extent(renderer)
    legend=fig.texts[0].get_window_extent(renderer)
    assert label.y0>legend.y1
    (tmp_path/'data').mkdir()
    record=f.v6.save(fig,tmp_path,'cost_labels',actual)
    assert record['minimum_font_pt']>=8 and record['text_bounds_within_canvas']


def test_earlier_figures_use_retained_functions():
    assert f.PLOT_NAMES==f.v7.PLOT_NAMES
    assert f.v7.cost is f._retained_cost
    assert not any(name in f.__dict__ for name in ('contract','structure','natural','realized_gap','known_law'))


def test_site_marks_editorial_scope_and_private_paper_exclusion():
    s=module('build_site_v7_1')
    assert tuple(r[0] for r in s.FIGURES)==f.PLOT_NAMES
    source=(ROOT/'scripts/build_site_v7_1.py').read_text(encoding='utf-8')
    assert 'V7.1' in source and 'editorial' in source.lower()
    assert 'manuscript_included' in source and 'False' in source
    assert 'make_figures_v7_1.py' in source and 'build_site_v7_1.py' in source
