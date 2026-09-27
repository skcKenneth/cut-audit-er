"""Build the local bilingual V7 evidence page, without hosting paper or private data."""
from __future__ import annotations
import argparse
import csv
import html
import importlib.util
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cut_audit_v6_site',Path(__file__).with_name('build_site_v6.py'))
v6=importlib.util.module_from_spec(spec);spec.loader.exec_module(v6)
sha,blob,require,checked,bilingual=v6.sha,v6.blob,v6.require,v6.checked,v6.bilingual
CSS,JS=v6.CSS,v6.JS
FIGURES=(
('fig01_contract','01 / What is certified?','01 / 證書涵蓋甚麼？','A fixed-state, fixed-pool computed-proxy winner. Expected repair quality is a separate question.','證書核對固定狀態、固定候選池及實作 proxy 的最佳選擇；期望修復品質是另一個問題。'),
('fig02_structure','02 / Structural coverage','02 / 結構覆蓋','Component coverage is distinct from FP-mass coverage. Large-component bond coverage remains unknown.','Component 覆蓋與 FP 錯誤量覆蓋不同；大型 component 的完整 bond 覆蓋仍未知。'),
('fig03_natural','03 / Retained natural contrasts','03 / 保留自然資料對比','The nine Full–Raw loss contrasts are zero. All 63 V5 natural endpoints remain downloadable.','九個 Full–Raw loss 差值均為零；V5 全部 63 個自然資料終點仍可下載。'),
('fig04_realized_gap','04 / Reference-only hindsight','04 / 單份參考的事後差距','Reference-only, single-batch, within-pool values. Positive gaps are locations, not decision-error rates.','單份參考分群、單批次、池內的收益比較；正差距是狀態位置，不是決策錯誤率。'),
('fig05_known_law','05 / Known-law controls','05 / 已知機率律控制','Four constructed controls separate perfect-information value from expected decision gaps; exact marginal scores can still misrank this proxy.','四個構造控制分開完美資訊價值與期望決策差距；即使 pair 邊際概率精確，這個 proxy 仍可能排錯。'),
('fig06_cost','06 / Same pool, complete costs','06 / 同一候選池與完整成本','Compare complete-score demand and recorded scores in the same Full pool. Counts do not establish elapsed-time speedup.','在同一 Full 候選池比較全評分需求與實際評分；次數差額不代表整體加速。'))


def build(root=ROOT,out=None):
    root=Path(root).resolve();out=Path(out).resolve() if out else root/'site'
    require(not out.exists(),'Fresh site directory required')
    evidence,figures=root/'evidence',root/'figures'
    em=checked(evidence);newer=checked(evidence,'v7_manifest.json');fm=checked(figures,'figure_provenance.json')
    require(fm['input_manifest_sha256']==sha(evidence/'manifest.json'),'Figure evidence pin differs')
    require(fm['v7_input_manifest_sha256']==sha(evidence/'v7_manifest.json'),'Figure V7 evidence pin differs')
    require([r['name'] for r in fm['figures']]==[r[0] for r in FIGURES],'Six V7 figure names differ')
    controls=json.loads((evidence/'controls_summary.json').read_text());same=json.loads((evidence/'same_pool_summary.json').read_text())
    require(len(controls['cases'])==4 and same['states']==301,'Fixed V7 evidence inventory differs')
    out.mkdir(parents=True);(out/'figures').mkdir();(out/'tables').mkdir()
    for name,*_ in FIGURES:
        for ext in ('pdf','svg','png'):shutil.copyfile(figures/f'{name}.{ext}',out/'figures'/f'{name}.{ext}')
    shutil.copyfile(figures/'figure_provenance.json',out/'figures/figure_provenance.json')
    for name in set(em['files_sha256'])|set(newer['files_sha256']):
        require(Path(name).name==name and Path(name).suffix in ('.json','.csv'),'Only scalar evidence table exports allowed')
        shutil.copyfile(evidence/name,out/'tables'/name)
    shutil.copyfile(evidence/'manifest.json',out/'tables/manifest.json')
    shutil.copyfile(evidence/'v7_manifest.json',out/'tables/v7_manifest.json')
    history=root/'historical/v5/evidence';checked(history)
    for name in ('acquisitions.csv','reference_endpoints.csv','coverage.csv','batches.csv','failures.csv'):
        shutil.copyfile(history/name,out/'tables'/('v5_'+name))
    cards=[]
    for name,en,zh,description,description_zh in FIGURES:
        links=' · '.join(f'<a href="figures/{name}.{ext}" download>{ext.upper()}</a>' for ext in ('pdf','svg','png'))
        cards.append(f'<article class="figure-card" id="{name}"><div class="figure-copy">'+bilingual(en,zh,'h2')+bilingual(description,description_zh,'p')+
                     f'<div class="figure-links">{links}</div></div><a class="figure-image" href="figures/{name}.svg" target="_blank" rel="noopener">'+
                     f'<img src="figures/{name}.svg" loading="lazy" alt="{html.escape(en)}" data-en="{html.escape(en)}" data-zh="{html.escape(zh)}"></a></article>')
    page='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CUT-AUDIT-ER · V7 mechanism evidence</title><meta name="description" content="Known-law controls, same-pool search accounting and retained verification-only entity-repair evidence."><link rel="stylesheet" href="style.css"></head><body>
<a class="skip" href="#main" data-en="Skip to evidence" data-zh="跳到證據">Skip to evidence</a><header><a class="brand" href="#">CUT / AUDIT / ER</a><button id="language" type="button" aria-label="Switch language" aria-pressed="false">繁體中文</button></header><main id="main">
<section class="hero"><p class="eyebrow" data-en="V7 · MECHANISM EVIDENCE" data-zh="V7 · 機制證據">V7 · MECHANISM EVIDENCE</p>'''
    page+='<h1>'+bilingual('Certified search.','已認證的搜尋。','span','class="title-line"')+bilingual('Known-law controls.','已知機率律的控制。','span','class="title-line"')+'</h1>'
    page+=bilingual('Separate what search can certify from what outcomes can identify.','分清搜尋能認證甚麼，以及結果能識別甚麼。','p','class="lead"')
    page+=bilingual('Verification-only entity repair: paid pair queries, fixed batches, and deletion of verified negative edges only. V7 adds four constructed controls and reconciles saved Full candidate pools; no natural repair run is repeated.','Verification-only entity repair：逐 pair 付費、固定批次，只刪除已驗證負邊。V7 新增四個構造控制並核對保存的 Full 候選池；沒有重跑自然資料修復。','p')
    page+='<div class="status">'+bilingual('REFRAME · Local research package. No deployment, submission, acceptance or general superiority claim.','REFRAME · 本地研究交付；未部署、未投稿，不宣稱已獲接收或普遍優越。','p')+'</div><div class="stats">'
    for value,en,zh in ((4,'fixed constructed controls','固定構造控制'),(20,'finite legal worlds','有限合法分群世界'),(301,'retained reached states','保留的實際到達狀態'),(0,'new natural acquisitions','新增自然資料 acquisition')):
        page+=f'<div><strong>{value}</strong>'+bilingual(en,zh,'span')+'</div>'
    page+='</div></section><section class="reading"><div>'+bilingual('What changed in V7','V7 實際增加了甚麼','h2')
    page+=bilingual('A Bayes-optimal negative control has frequent positive hindsight gaps. A separate tree control has exact pair marginals but a verifiable expected ranking reversal. The latter does not explain the natural-data gaps.','一個期望最佳的負控制仍常出現正的事後差距；另一個樹控制在 pair 邊際概率精確時，仍有可核查的期望排序倒轉。後者不能因此解釋自然資料的差距。','p')
    page+=bilingual('The same-pool audit checks saved candidate identities, scores, strict bounds, tie rules and fallback. Complete-score counts and measured runtime remain separate.','同池審核核對已保存候選身分、分數、嚴格上界、平手及 fallback；完整評分次數與實測時間分開。','p')+'</div><aside>'
    page+=bilingual('Limits remain visible','限制完整保留','h2')+bilingual('Natural conditional probability laws are unidentified. Controls are constructed examples, not new benchmark evidence. The V6 Camera branch remains blocked at its expired official source; no replacement dataset is used.','自然資料的條件機率律未識別。控制是構造例，不是新增 benchmark 證據。V6 Camera 分支仍保留官方來源過期的阻擋紀錄；沒有更換資料集。','p')+'</aside></section>'
    page+='<section class="audit-summary">'+bilingual('Four fixed controls','四個固定控制','h2')+'<table><thead><tr>'
    for en,zh in (('Control','控制'),('Expected hindsight gap','期望事後差距'),('Expected decision gap','期望決策差距')):page+=bilingual(en,zh,'th')
    page+='</tr></thead><tbody>'
    labels={'bayes_null_100':('100 independent edges','100 條獨立邊'),'path_aligned':('Aligned path','排序一致 path'),'path_reversal':('Reversed path','排序倒轉 path'),'two_edge_batch':('Two-edge batch','兩邊批次')}
    for row in controls['cases']:
        en,zh=labels[row['case']];page+='<tr>'+bilingual(en,zh,'th')+f"<td>{row['expected_hindsight_gap_float']:.6g}</td><td>{row['expected_decision_gap_float']:.6g}</td></tr>"
    page+='</tbody></table>'+bilingual('Known-law, initial single-batch gain per paid query. The 100-edge case is analytic; the other controls enumerate 8 + 8 + 4 legal worlds. No Monte Carlo, seed search, new selector or natural-data refit.','已知機率律下的初始單批次每次付費收益。100 邊例採解析計算，其餘列舉 8 + 8 + 4 個合法世界；沒有 Monte Carlo、seed 搜尋、新 selector 或自然資料重擬合。','p')+'</section>'
    page+='<section aria-label="Six evidence figures">'+''.join(cards)+'</section><section class="downloads">'+bilingual('Inspect the source evidence','檢查來源證據','h2')+'<ul>'
    downloads=[('controls_summary.json','Exact control summary','控制精確摘要'),('controls_actions.csv','All constructed candidate values','全部構造候選收益'),('controls_worlds.csv','Enumerated legal worlds','列舉合法世界'),
               ('same_pool_states.csv','All same-pool state counts','同池全部狀態計數'),('same_pool_summary.json','Same-pool scope and totals','同池範圍及加總'),
               ('evaluation_states.csv','Retained reference-only values','保留單份參考的收益'),('visible_states.csv','Retained visible audits','保留可見狀態審核'),
               ('v5_acquisitions.csv','All V5 endpoints','V5 全部終點'),('v5_batches.csv','V5 batch cost telemetry','V5 批次成本'),('v5_failures.csv','Historical failures and missing slots','歷史失敗與缺失'),('external_endpoints.csv','V6 external missing slots','V6 外部缺失格')]
    for name,en,zh in downloads:
        if (out/'tables'/name).exists():page+='<li>'+bilingual(en,zh,'a',f'href="tables/{name}" download')+'</li>'
    page+='</ul>'+bilingual('All six figures use the included, hash-checked tables. Public WDC aggregates do not independently revalidate pair identities. Full historical recomputation still needs the declared external assets.','六圖皆使用包內經 hash 核對的表格。公開 WDC 彙總不能獨立核對 pair 身分；完整歷史重算仍依賴列明的外部資產。','p')
    page+='<pre><code>python -m pytest -q tests\npython scripts/make_figures_v7.py --out figures_rebuilt\npython scripts/build_site_v7.py --out site_rebuilt</code></pre>'
    page+=bilingual('The paper and private review material are delivered separately. This page contains no manuscript, credentials, tracking or private data.','論文與私人審查材料分開交付；此頁不含論文全文、憑證、追蹤或私人資料。','p')+'</section></main><footer><p>CUT-AUDIT-ER · V7 · '+bilingual('Evidence before claims.','先核證據，再作主張。')+'</p></footer><script src="app.js"></script></body></html>'
    (out/'index.html').write_text(page,encoding='utf-8',newline='\n');(out/'style.css').write_text(CSS,encoding='utf-8',newline='\n');(out/'app.js').write_text(JS,encoding='utf-8',newline='\n')
    result={'schema':'cut-audit-v7-site-build','local_only':True,'deployed':False,'figures':6,'manuscript_included':False,
            'input_manifest_sha256':sha(evidence/'manifest.json'),'v7_input_manifest_sha256':sha(evidence/'v7_manifest.json'),'figure_manifest_sha256':sha(figures/'figure_provenance.json'),
            'files_sha256':{p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file()}}
    (out/'site_manifest.json').write_bytes(blob(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--out',type=Path)
    a=p.parse_args();print(json.dumps({'status':'PASS','figures':build(a.root,a.out)['figures']}))
