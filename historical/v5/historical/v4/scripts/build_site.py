"""Build a local bilingual reading site from the canonical V4 evidence manifest.

No data acquisition, model fitting, selector execution or remote publication.
"""
from __future__ import annotations

import argparse
import hashlib
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import shutil
from urllib.parse import unquote, urlsplit

try:
    from .validate_evidence import table, validate
except ImportError:
    from validate_evidence import table, validate

FIGURES = ('fig01_contract', 'fig02_structure', 'fig03_outcomes', 'fig04_events',
           'fig05_controlled', 'fig06_use')
METHODS = {'edge_betweenness': 'Weighted BC', 'cut_plan_fixed': 'Raw fixed',
           'cut_plan_fixed_singleton': 'Singleton'}
DATASETS = {'wdc': 'WDC · exposed', 'dblp_acm': 'DBLP–ACM · exposed',
            'dblp_unused': 'DBLP–ACM · unused cohort'}
COPY_DOCS = ('README.md', 'README.zh-Hant.md', 'README_zh-Hant.md',
             'REPRODUCTION_SCOPE.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe(root, name):
    pure = PurePosixPath(name)
    if not name or '\\' in name or ':' in name or str(pure) != name or pure.is_absolute() or '..' in pure.parts:
        raise ValueError('Unsafe site asset path: ' + name)
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError('Escaping site asset: ' + name)
    return path


def label(value):
    if value is None:
        return '—'
    if isinstance(value, float):
        return f'{value:.3f}'
    return str(value)


def cells(values):
    return '<tr>' + ''.join('<td>' + escape(label(value)) + '</td>' for value in values) + '</tr>'


def status_text(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def projection(manifest, natural, synthetic):
    """Read completion from statuses, cross-check planned counts; never impute."""
    counts = manifest['counts']
    natural_done = sum(row['status'] == 'completed' for row in natural)
    synthetic_done = sum(row['status'] == 'completed' for row in synthetic)
    expected = {'natural_slots': len(natural), 'natural_completed': natural_done,
                'synthetic_reference_evaluations': len(synthetic),
                'synthetic_reference_evaluations_completed': synthetic_done}
    if any(counts.get(key) != value for key, value in expected.items()):
        raise ValueError('Site counts differ from canonical tables')
    if counts['synthetic_acquisitions'] != 90 or len(synthetic) != 180:
        raise ValueError('Unexpected preregistered synthetic grid')
    if counts['synthetic_acquisitions_completed'] * 2 != synthetic_done:
        raise ValueError('Dependent reference count is not twice completed acquisitions')
    cohort = [r for r in natural if r['dataset'] == 'dblp_unused']
    if len(cohort) != 9:
        raise ValueError('Cohort inventory must retain all nine planned slots')
    low, high = counts['synthetic_paid_lower_bound'], counts['synthetic_paid_upper_bound']
    if low is None or high is None:
        paid = 'unknown / 未知'
    elif not 0 <= low <= high <= 288:
        raise ValueError('Synthetic physical paid bounds invalid')
    else:
        paid = str(low) if low == high else f'{low}–{high}'
    return {'{{NATURAL_COMPLETED}}': str(natural_done), '{{NATURAL_PLANNED}}': str(len(natural)),
            '{{SYNTH_COMPLETED}}': str(counts['synthetic_acquisitions_completed']),
            '{{SYNTH_PLANNED}}': str(counts['synthetic_acquisitions']),
            '{{REFERENCE_COMPLETED}}': str(synthetic_done), '{{REFERENCE_PLANNED}}': str(len(synthetic)),
            '{{SYNTH_PAID}}': paid, '{{COHORT_COMPLETED}}': str(sum(r['status'] == 'completed' for r in cohort)),
            '{{SYNTH_STATUS}}': escape(status_text(manifest['study_status']['synthetic'])),
            '{{COHORT_STATUS}}': escape(status_text(manifest['study_status']['cohort']))}


def figure_cards():
    descriptions = (
        ('From answers to partitions', '從回答到分群變化',
         'An illustrative contract: paid answers, delayed splits, and filtering only after the common candidate cap.',
         '示意圖：付費回答、延後分裂，以及共同候選截斷後才作單邊過濾。'),
        ('Which structure is actually covered?', '實際覆蓋哪些結構？',
         'Component coverage and initial FP mass use different denominators. FN headroom is an offline diagnostic.',
         'Component 覆蓋與初始 FP 量使用不同分母；FN headroom 只作離線診斷。'),
        ('Every requested-budget endpoint', '全部 requested-budget 終點',
         'Separately executed budgets retain missing cells, ties, BC wins, and both FP and FN in the linked tables.',
         '預算各自執行；保留缺失、平手及 BC 較佳案例，連結表格另列 FP 與 FN。'),
        ('A query can precede its repair', '查詢收益可以延後出現',
         'Saved WDC events distinguish positive answers, negative answers without a split and completed splits. WDC pair identities remain private.',
         '已保存 WDC 事件區分正回答、不分裂負回答及完成分裂；WDC pair 身分維持私人。'),
        ('Controlled opportunity and reference', '受控機會與參考條件',
         'Constructed graphs cross boundary width and fixed score profiles. Two offline references reuse each paid trajectory; unavailable cells remain NA.',
         '合成圖交叉邊界寬度與固定分數配方；兩份離線參考共用付費軌跡，缺失格維持 NA。'),
        ('Available candidates versus used actions', '可用候選與實際動作',
         'Capped candidate occurrences and committed batches have separate denominators. Generating a multiedge plan is not evidence of executing one.',
         '截斷後候選次數與承諾批次各有分母；生成多邊計畫並不等於實際執行。'),
    )
    cards = []
    for index, (name, text) in enumerate(zip(FIGURES, descriptions), 1):
        title_en, title_zh, en, zh = text
        cards.append(f'''<article class="figure-card"><div class="figure-copy"><span class="number">FIGURE {index:02d}</span>
<h3><span lang="en">{escape(title_en)}</span><span lang="zh-Hant">{escape(title_zh)}</span></h3>
<p><span lang="en">{escape(en)}</span><span lang="zh-Hant">{escape(zh)}</span></p>
<a href="figures/{name}.pdf">PDF</a> · <a href="figures/{name}.svg">SVG</a></div>
<a class="figure-image" href="figures/{name}.svg"><img loading="lazy" src="figures/{name}.svg"
alt="{escape(title_en + ' / ' + title_zh, quote=True)}" width="960" height="680"></a></article>''')
    return '\n'.join(cards)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []

    def handle_starttag(self, tag, attrs):
        self.targets += [value for key, value in attrs if key in ('href', 'src') and value]


def check_links(output):
    parser = Links()
    parser.feed((output / 'index.html').read_text(encoding='utf-8'))
    count = 0
    for link in parser.targets:
        url = urlsplit(link)
        if url.scheme or url.netloc or not url.path:
            continue
        target = (output / unquote(url.path)).resolve()
        if not target.is_relative_to(output.resolve()) or not target.is_file():
            raise ValueError('Broken local site link: ' + link)
        count += 1
    return count


def build(root, output, figures=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    figures = Path(figures).resolve() if figures else root / 'figures'
    if output == root or root.is_relative_to(output):
        raise ValueError('Site output must not contain the package root')
    if output.exists():
        raise FileExistsError('Use a fresh site output directory')
    validation = validate(root / 'evidence')
    manifest = json.loads((root / 'evidence/manifest.json').read_text(encoding='utf-8'))
    natural = table(root / 'evidence', 'natural_endpoints')
    synthetic = table(root / 'evidence', 'synthetic_endpoints')
    replacements = projection(manifest, natural, synthetic)
    provenance = json.loads((figures / 'figure_provenance.json').read_text(encoding='utf-8'))
    if provenance['input_manifest_sha256'] != sha(root / 'evidence/manifest.json'):
        raise ValueError('Figure provenance uses another evidence manifest')
    pins = {}
    for record in provenance['figures']:
        pins.update(record['files_sha256'])
    for name in FIGURES:
        for suffix in ('pdf', 'svg', 'png'):
            relative = name + '.' + suffix
            if relative not in pins or sha(figures / relative) != pins[relative]:
                raise ValueError('Missing or changed figure: ' + relative)
    output.mkdir(parents=True)
    for name in ('styles.css', 'app.js'):
        shutil.copyfile(root / 'site' / name, output / name)
    for name in COPY_DOCS:
        shutil.copyfile(root / name, output / name)
    downloads = []
    for name in sorted(set(manifest['files_sha256']) | {'manifest.json'}):
        source = safe(root / 'evidence', name)
        if source.suffix not in ('.csv', '.json'):
            raise ValueError('Unexpected evidence type for static presentation')
        target = output / 'evidence' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if source.suffix == '.csv':
            downloads.append(f'<li><a href="evidence/{escape(name, quote=True)}">{escape(name)}</a></li>')
    (output / 'figures').mkdir()
    for name in FIGURES:
        for suffix in ('pdf', 'svg', 'png'):
            shutil.copyfile(figures / (name + '.' + suffix), output / 'figures' / (name + '.' + suffix))
    shutil.copyfile(figures / 'figure_provenance.json', output / 'figures/figure_provenance.json')
    replay_links = []
    for relative in ('replay/dblp_exposed/manifest.json', 'replay/dblp_unused/manifest.json',
                     'replay/synthetic/analysis/manifest.json'):
        source = root / relative
        if source.is_file():
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            replay_links.append(f'<li><a href="{relative}">{escape(relative)}</a></li>')
    replacements.update({'{{FIGURE_CARDS}}': figure_cards(), '{{DOWNLOADS}}': '\n'.join(downloads),
                         '{{REPLAY_LINKS}}': '\n'.join(replay_links) or '<li>Unavailable / 尚未提供</li>',
                         '{{NATURAL_ROWS}}': '\n'.join(cells([DATASETS.get(r['dataset'], r['dataset']),
                          METHODS.get(r['method'], r['method']), r['budget'], r['status'], r['fp'], r['fn'], r['loss'],
                          r['paid'], r.get('selector_seconds'), r.get('worker_wall_seconds')]) for r in natural),
                         '{{SYNTHETIC_ROWS}}': '\n'.join(cells([r['k'], r.get('profile', r.get('score_profile')),
                          r['reference'], METHODS.get(r['method'], r['method']), r['budget'], r['status'],
                          r['fp'], r['fn'], r['loss']]) for r in synthetic)})
    page = (root / 'site/index.html').read_text(encoding='utf-8')
    for old, new in replacements.items():
        page = page.replace(old, new)
    if '{{' in page or '}}' in page:
        raise ValueError('Unresolved site template')
    (output / 'index.html').write_text(page, encoding='utf-8')
    (output / '.nojekyll').write_text('', encoding='utf-8')
    receipt = {'schema': 'cut-audit-site-v4', 'status': 'PASS',
               'evidence_manifest_sha256': sha(root / 'evidence/manifest.json'),
               'figure_provenance_sha256': sha(figures / 'figure_provenance.json'),
               'validation': validation, 'local_links_checked': check_links(output),
               'remote_deployment_performed': False, 'new_oracle_answers': 0,
               'site_scope': 'Local bilingual reading view; replay manifests only, full assets in the package'}
    (output / 'site_build.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('_site'))
    parser.add_argument('--figures', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(Path(__file__).resolve().parents[1], args.out, args.figures), indent=2))
