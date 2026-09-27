"""Finite public release checks; no data download, fitting or acquisition."""
import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

IGNORED = {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist', '_site', 'outputs'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def require(value, message):
    if not value:
        raise ValueError(message)


def member(root, name):
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and '..' not in relative.parts and '\\' not in name,
            f'Unsafe member path: {name}')
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), f'Escaping member: {name}')
    return path


def payload(root):
    return {p.relative_to(root).as_posix(): p for p in root.rglob('*')
            if p.is_file() and not any(x in IGNORED or x.endswith('.egg-info')
                                      for x in p.relative_to(root).parts)
            and p.suffix not in {'.pyc', '.pyo'}}


def verify_manifest(root):
    manifest = read(root / 'MANIFEST_SHA256.json')
    require(manifest['schema'] == 'cut-audit-public-release-manifest-v1', 'Wrong current manifest')
    actual = payload(root)
    actual.pop('MANIFEST_SHA256.json', None)
    require(set(actual) == set(manifest['files']), 'Current inventory differs')
    for name, item in manifest['files'].items():
        path = member(root, name)
        require(sha(path) == item['sha256'] and path.stat().st_size == item['bytes'],
                f'Release hash mismatch: {name}')
    protected = read(root / 'provenance/RETAINED_PAYLOAD_SHA256.json')['files_sha256']
    for name, digest in protected.items():
        require(sha(member(root, name)) == digest, f'Retained science/source changed: {name}')
    require(not any(Path(n).suffix in {'.tex', '.bib', '.zip'} for n in actual),
            'Manuscript/archive is outside the public allowlist')
    require(not any(x.lower() in {'.env', '.env.local', '.credentials', 'id_rsa', 'id_ed25519'}
                    for n in actual for x in PurePosixPath(n).parts), 'Credential file in payload')
    return len(actual), len(protected)


def verify_figures(root, rebuilt):
    retained = root / 'figures'
    names = {p.name for p in (retained / 'data').glob('*.json')}
    require(len(names) == 6 and names == {p.name for p in (rebuilt / 'data').glob('*.json')},
            'Expected six figure projections')
    for name in names:
        require(read(retained / 'data' / name) == read(rebuilt / 'data' / name),
                f'Figure numeric projection mismatch: {name}')
    for directory in (retained, rebuilt):
        provenance = read(directory / 'figure_provenance.json')
        require(len(provenance['figures']) == 6, 'Expected six provenance entries')
        for row in provenance['figures']:
            require(row['minimum_font_pt'] >= 8 and row['text_bounds_within_canvas'], 'Figure layout check failed')
            require(sha(directory / 'data' / (row['name']+'.json')) == row['projection_sha256'], 'Projection hash mismatch')
            for name, digest in row['files_sha256'].items():
                require(sha(member(directory, name)) == digest, f'Figure hash mismatch: {name}')
    return len(names)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets, self.ids, self.cards, self.downloads = [], set(), 0, 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        self.cards += 'figure-card' in attrs.get('class', '').split()
        self.downloads += tag == 'a' and 'download' in attrs
        for key in ('src', 'href'):
            if key in attrs:
                self.assets.append(attrs[key])


def verify_site(root, site):
    record = read(site / 'site_manifest.json')
    require(record['figures'] == 6 and record['manuscript_included'] is False, 'Incorrect site scope')
    require(record['input_manifest_sha256'] == sha(root / 'evidence/manifest.json'), 'Site evidence differs')
    require(record['v7_input_manifest_sha256'] == sha(root / 'evidence/v7_manifest.json'), 'V7 site evidence differs')
    for name, digest in record['files_sha256'].items():
        require(sha(member(site, name)) == digest, f'Site asset hash mismatch: {name}')
    actual = {p.relative_to(site).as_posix() for p in site.rglob('*') if p.is_file()}
    require(actual == set(record['files_sha256']) | {'site_manifest.json'}, 'Unexpected site file')
    page = (site / 'index.html').read_text(encoding='utf-8')
    parser = Links(); parser.feed(page)
    require(parser.cards == 6 and 'language' in parser.ids, 'Missing figures/language control')
    require('data-en=' in page and 'data-zh=' in page and parser.downloads > 0, 'Missing bilingual/download content')
    for url in parser.assets:
        split = urlsplit(url)
        if split.scheme or split.netloc:
            continue
        if split.path:
            require(member(site, unquote(split.path)).is_file(), f'Broken local asset: {url}')
        elif split.fragment:
            require(split.fragment in parser.ids, f'Broken anchor: {url}')
    require('No deployment' not in page and '未部署' not in page, 'Stale deployment assertion')
    return {'assets': len(record['files_sha256']), 'figures': parser.cards, 'downloads': parser.downloads}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('.'))
    p.add_argument('--rebuilt-figures', type=Path, required=True)
    p.add_argument('--site', type=Path, required=True)
    args = p.parse_args()
    root = args.root.resolve()
    files, protected = verify_manifest(root)
    figures = verify_figures(root, args.rebuilt_figures.resolve())
    site = verify_site(root, args.site.resolve())
    print(json.dumps({'status':'PASS', 'files':files, 'preserved_payloads':protected,
                      'numeric_projections_equal':figures, 'site':site,
                      'scope':'finite public release only; no full historical recomputation'}))


if __name__ == '__main__':
    main()
