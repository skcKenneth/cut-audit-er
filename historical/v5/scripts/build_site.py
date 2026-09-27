"""Build a local bilingual result page from the checked public aggregates."""
from pathlib import Path
import argparse
import csv
import html
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_public_release import check, site_links

TITLES = [
 ('Observation limits and the intervention', '觀察限制與方法介入'),
 ('Structure and error-mass coverage', '結構與錯誤量覆蓋'),
 ('All natural-data endpoints', '全部自然資料終點'),
 ('Fixed synthetic ablations', '固定合成消融'),
 ('From candidates to executed actions', '從候選到實際動作'),
 ('Quality and complete computational cost', '品質與完整計算成本')]
STEMS = ['fig01_contract', 'fig02_structure', 'fig03_natural', 'fig04_synthetic', 'fig05_mechanism', 'fig06_cost']

def build(out, root=ROOT):
    root, out = Path(root).resolve(), Path(out).resolve()
    check(root)
    if out.exists(): raise FileExistsError('Use a fresh site output directory')
    out.mkdir(parents=True)
    shutil.copytree(root / 'figures', out / 'figures')
    shutil.copytree(root / 'evidence', out / 'evidence')
    for name in ('README.md', 'README.zh-Hant.md', 'REPRODUCTION_SCOPE.md', 'THIRD_PARTY_NOTICES.md'):
        shutil.copyfile(root / name, out / name)
    manifest = json.loads((root / 'evidence/manifest.json').read_text(encoding='utf-8'))
    counts = manifest['counts']
    cards = []
    for i, (stem, (en, zh)) in enumerate(zip(STEMS, TITLES), 1):
        cards.append(f'''<section class="figure" id="figure-{i}"><h2><span lang="en">{i}. {en}</span><span lang="zh-Hant">{i}. {zh}</span></h2>
        <a href="figures/{stem}.svg" aria-label="Open full-size figure {i}"><img src="figures/{stem}.png" alt="{html.escape(en)} / {zh}" loading="lazy"></a>
        <p class="downloads"><a href="figures/{stem}.pdf">PDF</a><a href="figures/{stem}.svg">SVG</a><a href="figures/{stem}.png">PNG</a></p></section>''')
    links = ''.join(f'<li><a href="evidence/{p.name}">{p.name}</a></li>' for p in sorted((root / 'evidence').glob('*.csv')))
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cut Audit ER — V5 research evidence</title><link rel="stylesheet" href="style.css"></head><body>
<header><div class="top"><a href="#main">CUT AUDIT ER / V5</a><button id="language" type="button">繁體中文</button></div>
<p class="eyebrow"><span lang="en">Research evidence · local release</span><span lang="zh-Hant">研究證據 · 本地交付版本</span></p>
<h1><span lang="en">Which repair opportunities survive candidate generation and scoring?</span><span lang="zh-Hant">哪些修復機會能通過候選生成與評分？</span></h1>
<p class="lead"><span lang="en">A finite study of candidate coverage, proxy-aligned screening and multi-edge repair under paid-query limits.</span><span lang="zh-Hant">在付費查詢限制下，檢驗候選覆蓋、評分篩選與多邊修復的有限研究。</span></p></header>
<main id="main"><section class="note"><h2><span lang="en">Read the evidence with its limits</span><span lang="zh-Hant">連同限制閱讀證據</span></h2>
<p><strong><span lang="en">Outcome: no incremental natural-data quality gain. Full and Raw have identical losses and paid sequences in all nine matched conditions, with added cost. The synthetic counterexample is repaired, but BC and the new singleton control tie it. The prespecified development gate failed: all21ALASKA slots were unstarted, with no download, fit or external acquisition. Research decision: REFRAME; stop this external branch.</span><span lang="zh-Hant">結果：自然資料沒有新增品質收益。完整新法與raw的9組配對loss及付費序列全部相同，成本增加。合成反例雖修正，但與BC及新singleton控制同分。預定開發門檻未通過：ALASKA21格全部未啟動，沒有下載、擬合或外部查詢。研究決策維持REFRAME，停止本輪外部分支。</span></strong></p>
<p><span lang="en">These are separately executed requested-budget runs, not independent samples. Synthetic references H0/H9 share one acquisition trajectory. Observed development graphs and a conditional external branch do not establish universal superiority. Complete native TransClean and GraphCR comparisons remain unavailable.</span><span lang="zh-Hant">這些是分開執行的 requested-budget 運行，並非獨立樣本。合成 H0/H9 共用一次查詢軌跡。已暴露的開發圖與有條件的外部驗證不支持普遍優越性；完整原生 TransClean／GraphCR 比較仍然缺失。</span></p>
<p><span lang="en">Figures and downloads use the same checked tables. All failed and unstarted slots remain visible. The paper and private review package are not part of this public release.</span><span lang="zh-Hant">圖像與下載表使用同一份已核查資料，保留失敗及未啟動槽位。論文全文及私人審查包不屬於這個公開版本。</span></p>__COUNTS__</section>
<nav aria-label="Contents">__NAV__</nav>__FIGURES__
<section id="downloads"><h2><span lang="en">Tables and reproducibility</span><span lang="zh-Hant">表格與可重現性</span></h2>
<p><a href="README.md">English README</a> · <a href="README.zh-Hant.md">中文說明</a> · <a href="REPRODUCTION_SCOPE.md">Reproduction scope</a> · <a href="THIRD_PARTY_NOTICES.md">Sources &amp; licenses</a> · <a href="evidence/manifest.json">Evidence SHA-256 manifest</a></p><ul class="tables">__LINKS__</ul>
<p><span lang="en">The accompanying repository ZIP provides first-party code, tests, synthetic generators and paid-answer DBLP replay. Replay fails on an unrecorded query; evaluator labels cannot supply an answer. WDC remains aggregate-only. No sealed test data are included.</span><span lang="zh-Hant">配套 repository ZIP 包含程式、測試、合成生成器及 DBLP 已付費答案回放。遇到未記錄查詢會失敗，不能從 evaluator gold 補答。WDC 只提供彙總，不包含封存 test。</span></p></section></main>
<footer><span lang="en">Local research artifact. No deployment, acceptance or robust speed superiority is claimed.</span><span lang="zh-Hant">本地研究交付；不宣稱已部署、獲接納或具有穩健速度優勢。</span></footer><script src="app.js"></script></body></html>'''
    summary = f"<p class='counts'>Synthetic {counts['synthetic_completed']}/150 · Development {counts['natural_completed']}/63 · External {counts['external_completed']}/21</p>"
    nav = ''.join(f'<a href="#figure-{i}">{i}</a>' for i in range(1, 7)) + '<a href="#downloads">CSV</a>'
    (out / 'index.html').write_text(page.replace('__COUNTS__', summary).replace('__NAV__', nav).replace('__FIGURES__', ''.join(cards)).replace('__LINKS__', links), encoding='utf-8')
    (out / 'style.css').write_text('''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:#172b3a;background:#f5f7f9;font:17px/1.65 system-ui,sans-serif}header,main,footer{max-width:1140px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;align-items:center;gap:12px}.top a{font-weight:800;text-decoration:none}h1{font-size:clamp(2rem,5vw,3.8rem);line-height:1.15;max-width:1000px}h2{font-size:1.45rem;line-height:1.4}.lead{font-size:1.2rem;max-width:850px}.eyebrow{color:#42617b;text-transform:uppercase;letter-spacing:.08em;font-size:.8rem}button{border:1px solid #657b90;background:white;padding:9px 14px;border-radius:7px;font:inherit;cursor:pointer}a{color:#075da7;text-underline-offset:3px}a:focus,button:focus{outline:3px solid #c27614;outline-offset:4px}nav{display:flex;gap:12px;flex-wrap:wrap;padding:20px 0}nav a{background:white;padding:8px 16px;border:1px solid #c5d2df;border-radius:6px}.note,.figure,#downloads{background:white;border:1px solid #dce3eb;border-radius:12px;padding:24px;margin-bottom:24px}.note{border-left:5px solid #43647e}.counts{font-weight:700}.figure img{width:100%;height:auto;display:block}.downloads{display:flex;gap:18px}.tables{columns:2;overflow-wrap:anywhere}footer{font-size:.88rem;color:#536679}html[lang=en] [lang=zh-Hant],html[lang=zh-Hant] [lang=en]{display:none}@media(max-width:600px){header,main,footer{padding:16px}.note,.figure,#downloads{padding:16px}.tables{columns:1}.top{font-size:.9rem}h2{font-size:1.2rem}}''', encoding='utf-8')
    (out / 'app.js').write_text("document.getElementById('language').addEventListener('click',()=>{const zh=document.documentElement.lang==='en';document.documentElement.lang=zh?'zh-Hant':'en';document.getElementById('language').textContent=zh?'English':'繁體中文';});\n", encoding='utf-8')
    (out / '.nojekyll').write_text('', encoding='ascii')
    return {'status': 'PASS', 'figures': 6, 'evidence_counts': counts, **site_links(out)}

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--out', type=Path, required=True); args = p.parse_args()
    print(json.dumps(build(args.out), indent=2))
