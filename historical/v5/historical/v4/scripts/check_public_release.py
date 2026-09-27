"""Check the public V4 allowlist, replay schema, evidence, and local site links."""
from pathlib import Path, PurePosixPath
import argparse
import json
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.validate_evidence import validate

EXCLUDED={'.git','.venv','__pycache__','.pytest_cache','.cache','node_modules','_site','build'}
ROOT_FILES={'README.md','README.zh-Hant.md','README_zh-Hant.md','REPRODUCTION_SCOPE.md',
    'LICENSE','THIRD_PARTY_NOTICES.md','SOURCE_PROVENANCE.json','MANIFEST_SHA256.json',
    'pyproject.toml','requirements-public.txt','.gitignore'}


def allowed_name(name):
    p=PurePosixPath(name)
    if not name or p.is_absolute() or '\\' in name or ':' in name or any(x in ('','..','.') for x in name.split('/')):
        raise ValueError('Unsafe public path')
    parts=p.parts
    if any(x in EXCLUDED or re.match(r'(?i)(?:\.env|credentials?|tokens?|secrets?|human_approval)',x) for x in parts):
        raise ValueError('Excluded public path')
    if len(parts)==1:
        valid=name in ROOT_FILES
    elif parts[0]=='.github':
        valid=len(parts)==3 and parts[1]=='workflows' and p.suffix=='.yml'
    elif parts[0]=='src':
        valid=len(parts)==3 and parts[1]=='cut_audit_er' and p.suffix=='.py'
    elif parts[0] in ('tests','scripts'):
        valid=p.suffix=='.py'
    elif parts[0]=='evidence':
        valid=p.suffix in ('.csv','.json')
    elif parts[0]=='figures':
        valid=p.suffix in ('.pdf','.svg','.png','.json')
    elif parts[0]=='replay':
        valid=len(parts)>2 and parts[1] in ('dblp_exposed','dblp_unused','synthetic') and p.suffix in ('.json','.jsonl','.csv','.npy')
    elif parts[0]=='site':
        valid=p.suffix in ('.html','.css','.js','.svg','.json','.txt') or p.name=='.nojekyll'
    else:
        valid=name in ('configs/review_v4_synthetic.json','research/review_v4/SYNTHETIC_PROTOCOL.md')
    if not valid:raise ValueError('Not in the V4 public allowlist: '+name)
    return name


def payload(root=ROOT):
    root=Path(root).resolve()
    for p in sorted(root.rglob('*')):
        rel=p.relative_to(root)
        if any(x in EXCLUDED for x in rel.parts):continue
        if p.is_symlink():raise ValueError('Public source symlink')
        if p.is_file():
            yield allowed_name(rel.as_posix()),p


def site_links(site):
    site=Path(site).resolve();checked=0
    for path in site.rglob('*.html'):
        html=path.read_text(encoding='utf-8')
        for url in re.findall(r'(?:href|src)=["\']([^"\']+)',html):
            parsed=urlsplit(url)
            if parsed.scheme or parsed.netloc or url.startswith('#'):continue
            relative=unquote(parsed.path)
            target=(site/relative.lstrip('/') if relative.startswith('/') else path.parent/relative).resolve()
            if not target.is_relative_to(site):raise ValueError('Site link escapes artifact')
            if not target.exists():raise ValueError('Broken local site link: '+url)
            checked+=1
    return {'status':'PASS','local_links_checked':checked}


def check(root=ROOT):
    root=Path(root).resolve();files=list(payload(root))
    names={n for n,_ in files}
    if len(names)!=len({n.casefold() for n in names}):raise ValueError('Case-colliding public paths')
    for name,path in files:
        if path.suffix in ('.json','.jsonl','.csv','.md','.html'):
            raw=path.read_bytes()
            if re.search(rb'[A-Za-z]:[\\/](?:Users|Projects|GitHub)',raw):
                raise ValueError('Absolute local path in public data/document: '+name)
    for folder in ('dblp_exposed','dblp_unused'):
        base=root/'replay'/folder
        if not base.exists():continue
        expected={'observable.json','scores.npy','paid_cases.json','evaluator_reference.json','manifest.json'}
        if {p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file()}!=expected:
            raise ValueError('Unlisted DBLP replay asset')
        graph=json.loads((base/'observable.json').read_text(encoding='utf-8'))
        nodes=graph['nodes']
        if len(nodes)!=len(set(nodes)) or any(not re.fullmatch(r'r\d{6}',n) for n in nodes):
            raise ValueError('DBLP record alias contract differs')
        reference=json.loads((base/'evaluator_reference.json').read_text(encoding='utf-8'))['reference']
        if set(reference)!=set(nodes) or any(not re.fullmatch(r'e\d{6}',e) for e in reference.values()):
            raise ValueError('DBLP evaluator alias contract differs')
    synthetic=root/'replay/synthetic'
    if synthetic.exists():
        manifest=json.loads((synthetic/'manifest.json').read_text(encoding='utf-8'))
        expected=set(manifest['files_sha256'])|{'manifest.json'}
        if {p.relative_to(synthetic).as_posix() for p in synthetic.rglob('*') if p.is_file()}!=expected:
            raise ValueError('Unlisted synthetic replay asset')
        from scripts.validate_evidence import sha
        for name,pin in manifest['files_sha256'].items():
            path=(synthetic/name).resolve()
            if not path.is_relative_to(synthetic.resolve()) or sha(path)!=pin:
                raise ValueError('Synthetic public replay asset hash differs')
    report=validate(root/'evidence')
    return {'status':'PASS','allowlisted_files':len(files),'evidence':report,
        'scope':'Allowlist/schema/arithmetic validation; paid-answer replay is a separately logged command'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--site',type=Path);args=p.parse_args()
    print(json.dumps(site_links(args.site) if args.site else check(ROOT)))
