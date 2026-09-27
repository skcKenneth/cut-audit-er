"""V7.1 editorial labels over the unchanged, hash-checked V7 scientific figures."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cut_audit_v7_retained_render', Path(__file__).with_name('make_figures_v7.py'))
v7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v7)
v6, sha, encoded, table = v7.v6, v7.sha, v7.encoded, v7.table
PLOT_NAMES = v7.PLOT_NAMES
_retained_cost = v7.cost


def cost(acquisitions, batches, same_pool):
    fig, projection = _retained_cost(acquisitions, batches, same_pool)
    # Make space for the prescribed two-line wording without shrinking text.
    fig.subplots_adjust(bottom=.38)
    fig.axes[1].set_xlabel('Retained natural-run\ntime total (seconds)', labelpad=0)
    fig.axes[1].set_title('(b) Retained natural-run\ncosts', loc='left', fontsize=8)
    return fig, projection


def main(evidence, out, legacy=None):
    # Invoke the retained generator, changing only the final panel's two labels.
    # Restoring the callable makes repeated use in finite tests safe.
    prior = v7.cost
    try:
        v7.cost = cost
        result = v7.main(evidence, out, legacy)
    finally:
        v7.cost = prior
    result['schema'] = 'cut-audit-public-figures-v7-1'
    result['retained_renderer_sha256'] = sha(Path(__file__).with_name('make_figures_v7.py'))
    result['renderer_sha256'] = sha(Path(__file__))
    result['editorial_change'] = 'Figure 6 panel b title and time-axis label only; scientific data projections unchanged.'
    result['new_scientific_computations'] = 0
    (Path(out)/'figure_provenance.json').write_bytes(encoded(result))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, default=ROOT/'evidence')
    parser.add_argument('--legacy', type=Path, default=ROOT/'historical/v5/evidence')
    parser.add_argument('--out', type=Path, default=ROOT/'figures')
    args = parser.parse_args()
    print(json.dumps({'status':'PASS','figures':len(main(args.evidence,args.out,args.legacy)['figures'])}))
