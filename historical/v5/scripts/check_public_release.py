"""Validate the explicit V5 public payload without acquiring research answers."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import importlib.util
import json
import re
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '.venv', '__pycache__', '.pytest_cache', '.cache', 'node_modules', '_site', 'build'}
ROOT_FILES = {'README.md', 'README.zh-Hant.md', 'REPRODUCTION_SCOPE.md', 'LICENSE',
              'THIRD_PARTY_NOTICES.md', 'SOURCE_PROVENANCE.json', 'MANIFEST_SHA256.json',
              'pyproject.toml', 'requirements-public.txt', '.gitignore'}

def require(condition, message):
    if not condition: raise ValueError(message)

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))

def allowed_name(name):
    p = PurePosixPath(name)
    require(name and not p.is_absolute() and '\\' not in name and ':' not in name and
            not any(x in ('', '.', '..') for x in name.split('/')), 'Unsafe public member')
    parts = p.parts
    require(not any(x in EXCLUDED or re.match(r'(?i)(?:\.env|credentials?|tokens?|secrets?|human_approval)', x)
                    for x in parts), 'Excluded public member')
    if len(parts) == 1: valid = name in ROOT_FILES
    elif parts[:2] == ('historical', 'v4'): valid = True  # pinned complete historical manifest checked below
    elif parts[0] == '.github': valid = len(parts) == 3 and parts[1] == 'workflows' and p.suffix == '.yml'
    elif parts[0] == 'src': valid = len(parts) == 3 and parts[1] == 'cut_audit_er' and p.suffix == '.py'
    elif parts[0] in ('scripts', 'tests'): valid = p.suffix == '.py'
    elif parts[0] == 'evidence': valid = len(parts) == 2 and p.suffix in ('.json', '.csv')
    elif parts[0] == 'figures': valid = p.suffix in ('.json', '.pdf', '.svg', '.png')
    elif parts[0] == 'replay': valid = len(parts) > 2 and parts[1] in ('dblp_exposed', 'dblp_unused', 'synthetic') and p.suffix in ('.json', '.jsonl', '.npy', '.csv')
    elif parts[0] == 'site':
        valid = (len(parts) == 2 and p.name in ('index.html', 'style.css', 'app.js', '.nojekyll',
                 'README.md', 'README.zh-Hant.md', 'REPRODUCTION_SCOPE.md', 'THIRD_PARTY_NOTICES.md')) or (
                 len(parts) > 2 and parts[1] in ('figures', 'evidence') and p.suffix in ('.csv', '.json', '.pdf', '.svg', '.png'))
    else: valid = name in ('configs/review_v4_synthetic.json', 'research/review_v4/SYNTHETIC_PROTOCOL.md',
                          'research/review_v5/PROTOCOL.md', 'research/review_v5/THEORY.md', 'research/review_v5/NUMERIC_BOUND.md')
    require(valid, 'Not in V5 public allowlist: ' + name)
    return name

def payload(root=ROOT):
    root = Path(root).resolve()
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if any(p in EXCLUDED for p in rel.parts): continue
        require(not path.is_symlink(), 'Public symlink')
        if path.is_file(): yield allowed_name(rel.as_posix()), path

def site_links(site):
    site = Path(site).resolve(); checked = 0
    for path in site.rglob('*.html'):
        for url in re.findall(r'(?:href|src)=["\']([^"\']+)', path.read_text(encoding='utf-8')):
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc or url.startswith('#'): continue
            target = (path.parent / unquote(parsed.path)).resolve()
            require(target.is_relative_to(site) and target.exists(), 'Broken or escaping site link: ' + url)
            checked += 1
    return {'status': 'PASS', 'local_links_checked': checked}

def check(root=ROOT):
    root = Path(root).resolve(); files = dict(payload(root)); names = set(files)
    require(len(names) == len({n.casefold() for n in names}), 'Case-colliding public paths')
    historical = root / 'historical/v4'
    require(sha(historical / 'MANIFEST_SHA256.json') == 'd83292bb4932a0e7e715311081d1f55688092cf72bc586acd88ad2f80dbca84e', 'Untrusted historical V4 manifest')
    manifest = read(historical / 'MANIFEST_SHA256.json')
    expected = set(manifest['files']) | {'MANIFEST_SHA256.json'}
    historical_count = len(manifest['files'])
    actual = {n.removeprefix('historical/v4/') for n in names if n.startswith('historical/v4/')}
    require(actual == expected, 'Historical V4 inventory changed')
    for name, pin in manifest['files'].items():
        p = historical / name
        require(sha(p) == pin['sha256'] and p.stat().st_size == pin['bytes'], 'Historical V4 member changed')
    for name, path in files.items():
        if path.suffix in ('.json', '.jsonl', '.csv', '.md', '.html'):
            require(not re.search(rb'[A-Za-z]:[\\/](?:Users|Projects|GitHub)', path.read_bytes()), 'Absolute local path: ' + name)
    provenance = read(root / 'SOURCE_PROVENANCE.json')
    require(provenance['predecessor_public_zip_sha256'] == '2c36f49402f2731cd23cc71add250cf26c3fe43621b13caadb78e2d9ac4c1b08', 'Historical source archive differs')
    require(bool(provenance.get('first_party_files_sha256')), 'Missing named source provenance')
    for name, digest in provenance['first_party_files_sha256'].items():
        require(name in files and sha(files[name]) == digest, 'Public first-party source differs: ' + name)
    for folder in ('dblp_exposed', 'dblp_unused', 'synthetic'):
        base = root / 'replay' / folder; pin = read(base / 'manifest.json')
        expected = set(pin['files_sha256']) | {'manifest.json'}
        actual = {p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()}
        require(expected == actual, 'Replay inventory changed: ' + folder)
        for name, digest in pin['files_sha256'].items():
            path = (base / name).resolve()
            require(path.is_relative_to(base.resolve()) and sha(path) == digest, 'Replay checksum changed')
    spec = importlib.util.spec_from_file_location('v5_public_evidence_validation', root / 'scripts/validate_evidence.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    evidence = module.validate(root / 'evidence')
    figures = read(root / 'figures/figure_provenance.json')
    require(figures['input_manifest_sha256'] == sha(root / 'evidence/manifest.json'), 'Figures use different evidence')
    require(figures['renderer_sha256'] == sha(root / 'scripts/make_figures.py'), 'Figure renderer source changed')
    # Renderer receipt pins its own output paths and source table manifest.
    pins = figures.get('files_sha256', figures.get('outputs_sha256', {}))
    stems = ('fig01_contract', 'fig02_structure', 'fig03_natural', 'fig04_synthetic', 'fig05_mechanism', 'fig06_cost')
    expected_figures = {stem + '.' + ext for stem in stems for ext in ('pdf', 'svg', 'png')} | {'data/' + stem + '.json' for stem in stems}
    require(set(pins) == expected_figures, 'Figure checksum inventory differs')
    actual_figures = {n.removeprefix('figures/') for n in names if n.startswith('figures/')}
    require(actual_figures == expected_figures | {'figure_provenance.json'}, 'Unlisted public figure file')
    for name, digest in pins.items():
        p = (root / 'figures' / name).resolve()
        require(p.is_relative_to((root / 'figures').resolve()) and sha(p) == digest, 'Figure checksum changed')
    if (root / 'site').exists():
        site_links(root / 'site')
        for name, path in files.items():
            if name.startswith(('site/figures/', 'site/evidence/')):
                source = root / name.removeprefix('site/')
                require(source.is_file() and source.read_bytes() == path.read_bytes(), 'Site data differs from public source')
    return {'status': 'PASS', 'allowlisted_files': len(files), 'historical_files_unchanged': historical_count,
            'evidence': evidence, 'scope': 'Allowlist, hash and scalar arithmetic only. Full paid-answer replay is separately logged.'}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--site', type=Path); args = parser.parse_args()
    print(json.dumps(site_links(args.site) if args.site else check(), indent=2))
