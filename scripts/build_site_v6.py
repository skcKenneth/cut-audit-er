"""Build an offline bilingual V6 evidence site; no deployment or manuscript."""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import hashlib
import html
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
FIGURES=(
 ('fig01_contract','01 / Observation and action','01 / 觀察與動作',
  'The same edge answers can coexist with different FN risk. A proxy certificate concerns only the searched action pool.',
  '相同的邊回答可對應不同 FN 風險。Proxy 證書只涵蓋當次搜尋的動作池。'),
 ('fig02_structure','02 / Coverage that matters','02 / 結構與錯誤量覆蓋',
  'Component coverage and FP-mass coverage answer different questions. Large unresolved components remain visible.',
  'Component 覆蓋與 FP 錯誤量覆蓋回答不同問題；大型未解 component 不會被隱藏。'),
 ('fig03_natural','03 / Every natural endpoint','03 / 全部自然資料終點',
  'All 63 V5 runs are retained. Full matches Raw in all nine cohort–budget conditions; the new external branch did not run.',
  '保留 V5 全部 63 格。Full 與 Raw 在九個 cohort／預算條件同分；本輪外部分支未執行。'),
 ('fig04_realized_gap','04 / What the selected batch leaves','04 / 選中批次與已知可得收益',
  'All prescribed state groups are shown. These are hindsight one-batch values, not expected regret or population failure rates.',
  '展示所有預定狀態組。這是事後單批次收益比較，並非預期 regret 或母體失敗率。'),
 ('fig05_synthetic','05 / Controlled, explicitly synthetic','05 / 明確標示的合成對照',
  'The 300 dependent reference outcomes reuse 150 acquisitions. H0/H9 do not represent independent natural datasets.',
  '300 組相依參考評估重用 150 次 acquisition；H0/H9 不是獨立自然資料集。'),
 ('fig06_cost','06 / Complete cost, separate units','06 / 完整成本，各自計量',
  'Four contemporaneous arms expose score counts, logical accesses and measured time. Nested timers are not added together.',
  '同輪四臂分開呈現評分次數、logical accesses 及時間；巢狀 timers 不相加。'))


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def blob(value):return (json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8')
def require(ok,message):
    if not ok:raise ValueError(message)


def checked(folder,manifest='manifest.json'):
    folder=Path(folder).resolve();data=json.loads((folder/manifest).read_text(encoding='utf-8-sig'))
    pins=data.get('files_sha256',{});require(bool(pins),'Missing asset hashes')
    for name,pin in pins.items():
        path=(folder/name).resolve()
        require(path.is_relative_to(folder) and path.is_file() and sha(path)==pin,'Asset hash mismatch: '+name)
    return data


def bilingual(en,zh,tag='span',attrs=''):
    return f'<{tag} {attrs} data-en="{html.escape(en,quote=True)}" data-zh="{html.escape(zh,quote=True)}">{html.escape(en)}</{tag}>'


def build(root=ROOT,out=None):
    root=Path(root).resolve();out=Path(out).resolve() if out else root/'site'
    require(not out.exists(),'Fresh site directory required')
    evidence=root/'evidence';figures=root/'figures'
    checked(evidence);provenance=checked(figures,'figure_provenance.json')
    require(provenance['input_manifest_sha256']==sha(evidence/'manifest.json'),'Figures refer to different V6 evidence')
    require([r['name'] for r in provenance['figures']]==[r[0] for r in FIGURES],'Six V6 figures required')
    summary=json.loads((evidence/'summary.json').read_text(encoding='utf-8'))
    with (evidence/'evaluation_states.csv').open(encoding='utf-8',newline='') as stream:states=list(csv.DictReader(stream))
    completed=[r for r in states if r['single_batch_oracle_gap']!='']
    counts={phase:{'slots':sum(r['phase']==phase for r in states),
                   'evaluated':sum(r['phase']==phase for r in completed),
                   'partial_lower_bounds':sum(r['phase']==phase and r.get('gap_scope','').startswith('lower_bound') for r in completed),
                   'positive':sum(r['phase']==phase and float(r['single_batch_oracle_gap'])>0 for r in completed)}
            for phase in ('natural','synthetic')}
    require(len(states)==361 and summary['physical_states']==301,'Public inventory differs')
    out.mkdir(parents=True);(out/'figures').mkdir();(out/'tables').mkdir()
    for name,*_ in FIGURES:
        for ext in ('svg','pdf','png'):shutil.copyfile(figures/f'{name}.{ext}',out/'figures'/f'{name}.{ext}')
    shutil.copyfile(figures/'figure_provenance.json',out/'figures/figure_provenance.json')
    require((evidence/'external_endpoints.csv').is_file() and (evidence/'external_status.json').is_file(),
            'Public external branch status evidence required')
    with (evidence/'external_endpoints.csv').open(encoding='utf-8-sig',newline='') as stream:external_rows=list(csv.DictReader(stream))
    require(len(external_rows)==21 and all(r['status']=='not_started_download_blocked' for r in external_rows),
            'The external-branch statement differs from recorded slots')
    for filename in ('visible_states.csv','evaluation_states.csv','candidate_value_histogram.csv','summary.json','manifest.json',
                     'external_endpoints.csv','external_status.json'):
        shutil.copyfile(evidence/filename,out/'tables'/filename)
    historical=root/'historical/v5/evidence';checked(historical)
    for filename in ('acquisitions.csv','reference_endpoints.csv','coverage.csv','batches.csv','failures.csv'):
        shutil.copyfile(historical/filename,out/'tables'/('v5_'+filename))
    cards=[]
    for name,title,zh_title,description,zh_description in FIGURES:
        links=' · '.join(f'<a href="figures/{name}.{ext}" download>{ext.upper()}</a>' for ext in ('svg','pdf','png'))
        cards.append(f'<article class="figure-card" id="{name}"><div class="figure-copy">'
            +bilingual(title,zh_title,'h2')+bilingual(description,zh_description,'p')
            +f'<div class="figure-links">{links}</div></div><a class="figure-image" href="figures/{name}.svg" target="_blank" rel="noopener">'
            +f'<img src="figures/{name}.svg" alt="{html.escape(title)}" data-en="{html.escape(title)}" data-zh="{html.escape(zh_title)}" loading="lazy"></a></article>')
    stats=''.join(f'<div><strong>{value}</strong>'+bilingual(en,zh,'span')+'</div>' for value,en,zh in (
        (summary['physical_states'],'saved physical states','已保存實際狀態'),
        (len(states),'dependent reference slots','相依參考格'),
        (len(states)-len(completed),'unevaluated reference slots','未完成參考格'),
        (0,'new paid queries','新增付費查詢')))
    evidence_rows=''.join('<tr>'+bilingual('Natural' if phase=='natural' else 'Synthetic','自然資料' if phase=='natural' else '合成資料','th')
        +f"<td>{c['positive']}</td><td>{c['evaluated']}</td><td>{c['partial_lower_bounds']}</td><td>{c['slots']}</td></tr>" for phase,c in counts.items())
    download_rows=[('visible_states.csv','Visible-state audit','可見狀態審核'),('evaluation_states.csv','Reference-state audit','參考分群評估'),
        ('candidate_value_histogram.csv','Candidate value counts','候選收益計數'),('v5_acquisitions.csv','All V5 acquisitions / missing slots','V5 全部 acquisition／缺失格'),
        ('v5_reference_endpoints.csv','Synthetic reference outcomes','合成參考結果'),('v5_coverage.csv','Structural coverage','結構覆蓋'),
        ('v5_batches.csv','Batch telemetry and costs','批次記錄與成本'),('v5_failures.csv','Historical failures / missing cases','歷史失敗／缺失案例')]
    download_rows.append(('external_endpoints.csv','All 21 V6 external missing slots','V6 外部全部 21 個缺失格'))
    downloads=''.join('<li>'+bilingual(en,zh,'a',f'href="tables/{filename}" download')+'</li>' for filename,en,zh in download_rows)
    page='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="CUT-AUDIT-ER V6: public evidence for certified proxy search and realized single-batch repair values.">
<title>CUT-AUDIT-ER · V6 mechanism study</title><link rel="stylesheet" href="style.css"></head><body>
<a class="skip" href="#main" data-en="Skip to evidence" data-zh="跳到證據">Skip to evidence</a><header><a class="brand" href="#">CUT / AUDIT / ER</a>
<button id="language" type="button" aria-label="Switch language" aria-pressed="false">繁體中文</button></header><main id="main">
<section class="hero"><p class="eyebrow" data-en="V6 · RESEARCH EVIDENCE" data-zh="V6 · 研究證據">V6 · RESEARCH EVIDENCE</p>'''
    page+='<h1>'+bilingual('Certified search.','已認證的搜尋，','span','class="title-line"')
    page+=bilingual('Realized repair value.','實際修復的收益。','span','class="title-line"')+'</h1>'
    page+=bilingual('What can a verified proxy optimum tell us—and what remains outside its guarantee?','已核查的 proxy 最佳選擇能說明甚麼？哪些結論仍不在保證範圍？','p','class="lead"')
    page+=bilingual('A bounded, verification-only entity-repair study. Existing experiments stay frozen; V6 adds an offline mechanism audit.','有限預算、只刪除已驗證負邊的 entity repair 研究。保留既有實驗，V6 新增離線機制審核。','p')
    page+='<div class="status">'+bilingual('REFRAME · Local package, not deployed or submitted. Publication-level contribution remains unestablished.','REFRAME · 本地交付，未部署、未投稿；出版級貢獻仍未確立。','p')+'</div><div class="stats">'+stats+'</div></section>'
    page+='<section class="reading"><div>'+bilingual('Read the evidence in order','建議按次序閱讀','h2')
    page+=bilingual('First separate observation limits and structural coverage. Then inspect every endpoint, the realized batch gaps, the controlled examples, and all cost units.','先分清觀察限制與結構覆蓋，再看全部終點、單批次事後差距、受控例子及完整成本。','p')
    page+=bilingual('Tap a figure to open its vector version. The source tables retain all declared groups and missing cases.','按圖可開啟向量版；來源表保留所有預定組別及缺失案例。','p')+'</div><aside>'
    page+=bilingual('Prospective external branch: blocked','前瞻外部分支：受阻','h2')
    page+=bilingual('The official ALASKA Camera link has expired. All 21 V6 slots are unstarted; no dataset archive was acquired, and no fit or external repair run occurred. V5’s separate failed progression gate is preserved.','ALASKA Camera 官方分享連結已過期。V6 的 21 格全部未啟動，未取得資料 archive，亦未進行擬合或外部修復運行；V5 的原有失敗門檻紀錄保留。','p')
    page+=bilingual('Official provider issue #2 ↗','官方來源 issue #2 ↗','a',
                    'href="https://github.com/merialdo/research.alaska/issues/2" rel="noopener"')+'</aside></section>'
    page+='<section class="audit-summary">'+bilingual('Hindsight gap counts','事後差距計數','h2')
    page+='<table><thead><tr>'+''.join(bilingual(en,zh,'th') for en,zh in [('Reference type','參考類別'),('Positive gap','正差距'),('Evaluated','已評估'),('Of these: lower bounds','其中：下界'),('Planned','預定')])+'</tr></thead><tbody>'+evidence_rows+'</tbody></table>'
    page+=bilingual('Counts describe Full-reached states. Repeated budgets, shared histories and H0/H9 are dependent. A positive realized gap does not establish miscalibration or expected regret.','計數只描述 Full 到達的狀態。預算、共用歷史及 H0/H9 相依；正的已實現差距不代表已證明誤校準或預期 regret。','p')+'</section>'
    page+='<section aria-label="Six evidence figures">'+''.join(cards)+'</section><section class="downloads">'
    page+=bilingual('Inspect and reproduce','檢查與重現','h2')+'<ul>'+downloads+'</ul>'
    page+=bilingual('The repository package includes code, finite tests, plotting and permitted saved-answer replays. Public aggregates cannot revalidate private WDC pair identities or recreate every historical experiment.','Repository 包含程式、有限測試、製圖及可再散發的已付費回答回放。公開彙總不能重新核對私人 WDC pair 身分或重做全部歷史實驗。','p')
    page+='<pre><code>python -m pytest -q tests\npython -m scripts.review_v6.validate_evidence --evidence evidence\npython scripts/make_figures_v6.py --out figures_rebuilt</code></pre>'
    page+=bilingual('The manuscript and private review archive are separate local deliverables; they are not hosted here.','論文及私人審查包另作本地交付；此頁不提供全文。','p')+'</section></main>'
    page+='<footer><p>CUT-AUDIT-ER · V6 · '+bilingual('Evidence first; no acceptance claim.','以證據為先；不宣稱已達接收標準。')+'</p></footer><script src="app.js"></script></body></html>'
    (out/'index.html').write_text(page,encoding='utf-8',newline='\n')
    (out/'style.css').write_text(CSS,encoding='utf-8',newline='\n')
    (out/'app.js').write_text(JS,encoding='utf-8',newline='\n')
    result={'schema':'cut-audit-v6-site-build','local_only':True,'deployed':False,
        'input_manifest_sha256':sha(evidence/'manifest.json'),'figure_manifest_sha256':sha(figures/'figure_provenance.json'),
        'figures':6,'reference_counts':counts,'manuscript_included':False,
        'files_sha256':{p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file()}}
    (out/'site_manifest.json').write_bytes(blob(result));return result


CSS='''*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f5f6f3;color:#19272d;font:16px/1.65 system-ui,-apple-system,"Segoe UI","Noto Sans TC",sans-serif}a{color:#006894;text-underline-offset:3px}header{max-width:1120px;margin:auto;display:flex;align-items:center;justify-content:space-between;padding:22px 30px;border-bottom:1px solid #d5deda}.brand{text-decoration:none;color:#203b47;font-size:14px;letter-spacing:.16em;font-weight:750}button{background:#fff;border:1px solid #617a83;border-radius:30px;padding:9px 18px;color:#173b4b;font:inherit;cursor:pointer}button:hover{background:#e9f0f1}button:focus-visible,a:focus-visible{outline:3px solid #d55e00;outline-offset:4px}main{max-width:1120px;margin:auto;padding:0 30px}h1{font-size:clamp(32px,5vw,62px);line-height:1.12;max-width:820px;letter-spacing:-.03em;margin:20px 0;text-wrap:balance}h2{font-size:22px;line-height:1.3;margin:0 0 15px;font-weight:650}p{margin:0 0 15px}.hero{padding:55px 0 30px}.eyebrow{color:#326273;font-size:12px;letter-spacing:.17em;font-weight:750}.lead{font-size:22px;max-width:810px;line-height:1.45}.hero>p:not(.eyebrow){max-width:850px}.status{margin:26px 0;border-left:4px solid #b96125;background:#fff8eb;padding:12px 18px;font-size:14px}.status p{margin:0}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin-top:32px;padding-bottom:24px;border-bottom:1px solid #cbd5d1}.stats strong{display:block;font-size:38px;line-height:1.2;font-weight:600;color:#006894}.stats span{font-size:13px;color:#4e5d62}.reading{display:grid;grid-template-columns:1.2fr 1fr;gap:45px;margin:28px 0 40px}.reading aside{padding:20px;background:#e9efed;border-radius:8px;font-size:14px}.reading aside h2{font-size:18px}.audit-summary{padding:25px 28px;background:#fff;border:1px solid #d8e0dc;border-radius:8px;margin-bottom:38px}.audit-summary p{font-size:14px;margin-top:15px;max-width:950px}table{border-collapse:collapse;width:100%;font-size:15px;text-align:left}th,td{padding:10px;border-bottom:1px solid #d8e0dc}thead th{font-size:13px;color:#50666f}.figure-card{background:#fff;border:1px solid #d9e2de;border-radius:10px;display:grid;grid-template-columns:minmax(230px,.67fr) minmax(0,1.1fr);align-items:center;gap:25px;padding:26px;margin:0 0 24px;box-shadow:0 3px 15px #223b4810}.figure-copy h2{font-size:21px}.figure-copy p{font-size:15px;color:#465a63}.figure-links{font-size:13px;font-weight:600}.figure-image{display:block;min-width:0}.figure-image img{display:block;width:100%;height:auto}.downloads{padding:38px 0}.downloads ul{display:grid;grid-template-columns:1fr 1fr;gap:8px 20px;padding-left:20px}.downloads p{max-width:970px}pre{overflow:auto;background:#182f3a;color:#edf4f3;padding:22px;border-radius:8px;font:13px/1.7 ui-monospace,Consolas,monospace}footer{border-top:1px solid #ccd8d2;padding:25px 30px;text-align:center;font-size:13px;color:#52666e}.skip{position:absolute;left:15px;top:-100px;background:#fff;padding:10px;z-index:10}.skip:focus{top:10px}@media(max-width:720px){header{padding:17px 20px}main{padding:0 20px}.hero{padding-top:34px}.lead{font-size:19px}.stats{grid-template-columns:repeat(2,1fr);gap:20px}.reading{grid-template-columns:1fr;gap:20px;margin-top:12px}.figure-card{grid-template-columns:1fr;padding:18px;gap:10px}.figure-copy h2{font-size:20px}.figure-copy p{font-size:14px}.audit-summary{padding:18px 12px}table{font-size:13px}th,td{padding:8px 5px}.downloads ul{grid-template-columns:1fr}.brand{font-size:12px;letter-spacing:.08em}button{font-size:13px;padding:8px 13px}}@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
'''
CSS+='h1 .title-line{display:block}\n'
JS='''(()=>{"use strict";const button=document.getElementById("language");let lang="en";try{lang=localStorage.getItem("cut-audit-er-language")==="zh"?"zh":"en"}catch(e){}function apply(){document.documentElement.lang=lang==="zh"?"zh-Hant":"en";document.querySelectorAll("[data-en][data-zh]").forEach(el=>{const value=el.dataset[lang];if(el.tagName==="IMG"){el.alt=value}else{el.textContent=value}});button.textContent=lang==="zh"?"English":"繁體中文";button.setAttribute("aria-label",lang==="zh"?"Switch to English":"切換至繁體中文");button.setAttribute("aria-pressed",String(lang==="zh"));try{localStorage.setItem("cut-audit-er-language",lang)}catch(e){}}button.addEventListener("click",()=>{lang=lang==="en"?"zh":"en";apply()});apply()})();
'''


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--out',type=Path)
    args=parser.parse_args();print(json.dumps({'status':'PASS','figures':build(args.root,args.out)['figures']}))
