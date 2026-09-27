"""Six V7 figures from pinned scalar evidence; no fitting or policy execution."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch,FancyArrowPatch
from matplotlib.ticker import MaxNLocator
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cut_audit_v6_render',Path(__file__).with_name('make_figures_v6.py'))
v6=importlib.util.module_from_spec(spec);spec.loader.exec_module(v6)
require,sha,encoded,table,check_manifest=v6.require,v6.sha,v6.encoded,v6.table,v6.check_manifest
PLOT_NAMES=('fig01_contract','fig02_structure','fig03_natural','fig04_realized_gap','fig05_known_law','fig06_cost')
DATASETS=v6.DATASETS


def contract():
    fig=plt.figure(figsize=(4.8,2.20));ax=fig.add_axes([.015,.08,.97,.84]);ax.set_xlim(0,10);ax.set_ylim(0,5);ax.axis('off')
    boxes=[(.1,3.55,2.75,'Visible graph + scores\n+ paid answers'),(3.55,3.55,2.8,'Fixed legal pool\n+ computed proxy'),(7.0,3.55,2.85,'Strict separation\nfrom unscored bounds')]
    for x,y,w,t in boxes:
        ax.add_patch(FancyBboxPatch((x,y),w,1.08,boxstyle='round,pad=.08',fc='#E8EEF2',ec='#64717D',lw=.6))
        ax.text(x+w/2,y+.54,t,ha='center',va='center',fontsize=8)
    for x,y in ((2.97,3.40),(6.48,6.85)):
        ax.add_patch(FancyArrowPatch((x,4.1),(y,4.1),arrowstyle='-|>',mutation_scale=9,color='#555'))
    ax.text(5,2.68,'Certifies the same-pool proxy winner; not expected repair value.',ha='center',fontweight='bold',fontsize=8)
    for x,title,line,col in ((2.5,'Reference-only natural audit','Realized one-batch gap\nExpected decision gap unknown','#0072B2'),
                              (7.5,'Known-law constructed controls','Enumerate legal partitions\nSeparate information / decision gaps','#D55E00')):
        ax.add_patch(FancyBboxPatch((x-2.25,.55),4.5,1.48,boxstyle='round,pad=.07',fc='white',ec=col,lw=.8))
        ax.text(x,1.69,title,ha='center',fontsize=8,color=col,fontweight='bold')
        ax.text(x,1.01,line,ha='center',va='center',fontsize=8)
    fig.text(.5,.025,'Every committed pair is paid; only verified negative edges are deleted.',ha='center',fontsize=8)
    return fig,{'type':'schematic','certificate_scope':'same reached state, same legal searched pool, same computed proxy and ties',
                'no_expected_value_certificate':True,'gold_only_offline':True,'constructive_controls_not_natural':True}


def natural(acquisitions):
    rr=[r for r in acquisitions if r['phase']=='natural'];require(len(rr)==63,'All 63 V5 natural slots required')
    lookup={(r['dataset'],r['method'],r['budget']):r for r in rr}
    fig,axes=plt.subplots(1,3,figsize=(4.8,2.25));fig.subplots_adjust(left=.13,right=.97,bottom=.35,top=.84,wspace=.64)
    contrasts=[]
    for ax,dataset in zip(axes,DATASETS):
        for i,b in enumerate((12,24,48)):
            full=lookup[dataset,'cut_plan_cover_fixed',b]
            for m,dy in (('cut_plan_fixed',-.10),('edge_betweenness',.10)):
                base=lookup[dataset,m,b];delta=full['loss']-base['loss'] if full['status']==base['status']=='completed' else None
                contrasts.append(dict(dataset=dataset,budget=b,control=m,delta_loss=delta))
                if delta is not None: ax.scatter(delta,i+dy,marker=v6.MARKERS[m],s=25,color=v6.COLORS[m],zorder=3)
                else: ax.text(0,i+dy,'NA',ha='center')
        ax.axvline(0,color='#777',lw=.6);ax.set_yticks((0,1,2),('12','24','48'));ax.set_ylim(2.45,-.45)
        ax.set_title(v6.TITLES[dataset]);ax.set_xlabel('')
        values=[r['delta_loss'] for r in contrasts if r['dataset']==dataset and r['delta_loss'] is not None]
        extent=max([1,*map(abs,values)])
        if dataset=='wdc':ax.set_xlim(-10000,5000);ax.set_xticks((-10000,0,5000),('−10k','0','5k'))
        else:ax.set_xlim(-.6,extent+1);ax.set_xticks((0,extent))
    axes[0].set_ylabel('Requested budget')
    fig.legend(handles=[Line2D([],[],marker=v6.MARKERS[m],ls='',color=v6.COLORS[m],label=v6.SHORT[m],markersize=4) for m in ('cut_plan_fixed','edge_betweenness')],
               loc='lower center',bbox_to_anchor=(.5,.12),ncol=2,frameon=False)
    fig.text(.5,.035,'Full − control: Δ(FP + FN); smaller is better. Full − Raw is always zero.\nSeparately executed, dependent budget runs; complete endpoints stay in tables.',ha='center',fontsize=8)
    return fig,{'all_natural_slots':rr,'contrasts':contrasts,'missing_slots':sum(r['status']!='completed' for r in rr),'speedup_claim':False}


def realized_gap(data):
    rr=[r for r in data if r['phase']=='natural'];require(len(rr)==241,'Natural reference audit scope differs')
    complete=[r for r in rr if r['single_batch_oracle_gap'] is not None]
    fig,axes=plt.subplots(1,2,figsize=(4.8,2.80));fig.subplots_adjust(left=.17,right=.97,bottom=.35,top=.86,wspace=.7)
    counts,scatter=axes;groups=[]
    for i,(dataset,color,marker) in enumerate(zip(DATASETS,('#0072B2','#D55E00','#009E73'),('o','s','^'))):
        points=[r for r in complete if r['dataset']==dataset];positive=sum(r['single_batch_oracle_gap']>0 for r in points)
        groups.append(dict(dataset=dataset,planned=sum(r['dataset']==dataset for r in rr),evaluated=len(points),positive=positive))
        counts.barh(i,positive/len(points) if points else 0,color=color,height=.50,edgecolor='#333',lw=.4)
        counts.text(1.03,i,f'{positive}/{len(points)}',va='center',fontsize=8)
        scatter.scatter([r['selected_gain_per_query'] for r in points],[r['best_known_gain_per_query'] for r in points],s=18,color=color,marker=marker,lw=.3,edgecolor='white',alpha=.8)
    counts.set_yticks(range(3),[v6.TITLES[d] for d in DATASETS]);counts.set_ylim(2.65,-.65);counts.set_xlim(0,1.56)
    counts.set_xticks((0,.5,1),('0','50','100'));counts.set_xlabel('Positive gap states (%)');counts.set_title('(a) Count / evaluated',loc='left')
    hi=max([1,*[r['best_known_gain_per_query'] for r in complete]]);lo=min([0,*[r['selected_gain_per_query'] for r in complete]])
    scatter.plot([lo,hi],[lo,hi],ls='--',lw=.6,color='#777');scatter.set_xscale('symlog',linthresh=1);scatter.set_yscale('symlog',linthresh=1)
    scatter.set_xlim(lo-.2,hi*1.2);scatter.set_ylim(lo-.2,hi*1.2)
    ticks=[x for x in (0,1,100,10000) if x<=hi*1.2];labels=['10k' if x==10000 else str(x) for x in ticks];scatter.set_xticks(ticks,labels);scatter.set_yticks(ticks,labels)
    scatter.set_title('(b) Gain per paid query',loc='left');scatter.set_xlabel('Selected');scatter.set_ylabel('Best pool + actual + no-op')
    fig.text(.5,.105,'Reference-only, single batch, within pool: 241 dependent states.\nPositive-gap counts are locations, not decision-error rates.',ha='center',fontsize=8)
    fig.text(.5,.025,'Expected decision gaps unidentified. Symlog axes outside [−1, 1].',ha='center',fontsize=8)
    return fig,{'states':rr,'groups':groups,'scope':'Reference-only, single-batch, within-pool hindsight values',
                'expected_decision_gap_identified':False,'points':len(complete),'missing':len(rr)-len(complete)}


def known_law(summary,actions):
    cases=summary['cases'];require(len(cases)==4,'All four fixed constructed controls required')
    fig,axes=plt.subplots(1,2,figsize=(4.8,2.95));fig.subplots_adjust(left=.135,right=.97,bottom=.41,top=.84,wspace=.85)
    ax=axes[0]
    for i,c in enumerate(cases):
        x=c['expected_decision_gap_float'];y=c['expected_hindsight_gap_float']
        ax.scatter(x,y,s=35,marker=('o','s','^','D')[i],color=('#0072B2','#009E73','#D55E00','#CC79A7')[i],zorder=3)
        ax.annotate(str(i+1),(x,y),xytext=(5,3),textcoords='offset points',fontsize=8)
    xmax=max(1.,max(c['expected_decision_gap_float'] for c in cases)*1.2)
    ymax=max(1.,max(c['expected_hindsight_gap_float'] for c in cases)*1.2)
    ax.plot([0,min(xmax,ymax)],[0,min(xmax,ymax)],ls='--',lw=.6,color='#AAA');ax.set_xlim(-.045,xmax);ax.set_ylim(-.05,ymax)
    ax.set_xlabel('Expected decision gap');ax.set_ylabel('Expected hindsight gap');ax.set_title('(a) Known-law decomposition',loc='left')
    ax.set_xticks((0,.5,1));ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
    ax=axes[1];plotted=[]
    for row,(case,title) in enumerate((('path_aligned','Aligned'),('path_reversal','Reversed'))):
        rows=[r for r in actions if r['case']==case];require(len(rows)==3,'Three path candidates required')
        # Endpoints are named in the fully synthetic table; group equal leaf values.
        rows=sorted(rows,key=lambda r:r['action_id']);leaf,center=rows[0],rows[1]
        for j,(record,which) in enumerate(((leaf,'Leaf'),(center,'Centre'))):
            y=row*2.6+j
            for key,dy,color,marker in (('proxy_float',-.12,'#0072B2','o'),('expected_value_float',.12,'#D55E00','s')):
                ax.scatter(record[key],y+dy,color=color,marker=marker,s=22,zorder=3)
            plotted.append(dict(case=case,action_id=record['action_id'],label=which,proxy_float=record['proxy_float'],expected_value_float=record['expected_value_float']))
    ax.set_yticks((0,1,2.6,3.6),('Aligned leaf','Aligned centre','Reversed leaf','Reversed centre'))
    ax.set_ylim(4.1,-.65);ax.set_xlim(.3,1.35);ax.set_xticks((.5,1));ax.set_xlabel('Gain per paid query');ax.set_title('(b) Exact-marginal paths',loc='left')
    fig.legend(handles=[Line2D([],[],marker=m,ls='',color=c,label=t,markersize=4) for m,c,t in [('o','#0072B2','Proxy'),('s','#D55E00','True expectation')]],
               loc='lower center',bbox_to_anchor=(.5,.175),ncol=2,frameon=False,handletextpad=.35)
    fig.text(.5,.085,'1: 100 edges; 2: aligned path; 3: reversed path; 4: two-edge cut.\nConstructed known laws, not natural-data error rates or representative samples.',ha='center',fontsize=8)
    fig.text(.5,.015,'Singleton path actions need no joint-event independence approximation.',ha='center',fontsize=8)
    return fig,{'cases':cases,'path_actions':plotted,'all_actions':actions,'scope':'Three finite legal-partition laws plus one analytic negative control; not a natural-data experiment'}


def cost(acquisitions,batches,same_pool):
    groups=same_pool['groups'];require({r['phase'] for r in groups}=={'natural','synthetic'},'Both same-pool phases required')
    fig,axes=plt.subplots(1,2,figsize=(4.8,3.0));fig.subplots_adjust(left=.16,right=.96,bottom=.36,top=.85,wspace=.62)
    ax=axes[0]
    for i,phase in enumerate(('natural','synthetic')):
        g=next(r for r in groups if r['phase']==phase)
        for key,dy,color,marker in (('pool_count',-.12,'#777','s'),('scored_count',.12,'#0072B2','o')):
            ax.scatter(g[key],i+dy,color=color,marker=marker,s=26)
            ax.annotate(f"{g[key]:,}",(g[key],i+dy),xytext=(0,-13 if dy>0 else 5),textcoords='offset points',ha='center',fontsize=8)
    ax.set_xscale('log');ax.set_xlim(50,150000);ax.set_xticks((100,1000,10000,100000),('100','1k','10k','100k'))
    ax.set_ylim(1.6,-.6);ax.set_yticks((0,1),('Natural','Synthetic'));ax.set_xlabel('Complete proxy evaluations');ax.set_title('(a) Same states and Full pool',loc='left')
    totals=[];ax=axes[1]
    for i,m in enumerate(v6.ARMS):
        rr=[r for r in acquisitions if r['phase']=='natural' and r['method']==m];require(len(rr)==9,'Fixed natural cost arm incomplete')
        selector=sum(r['selector_seconds'] for r in rr);worker=sum(r['worker_wall_seconds'] for r in rr)
        ax.plot((selector,worker),(i,i),color='#AAA',lw=.8)
        ax.scatter(selector,i,color=v6.COLORS[m],marker='o',s=21);ax.scatter(worker,i,color=v6.COLORS[m],marker='s',facecolor='white',s=25)
        totals.append(dict(method=m,selector_seconds=selector,worker_wall_seconds=worker,logical_score_accesses=sum(r['logical_score_accesses'] for r in rr),
                           full_scores=sum(r['scored_candidate_actions'] for r in batches if r['phase']=='natural' and r['method']==m)))
    ax.set_yticks(range(4),[v6.SHORT[m] for m in v6.ARMS]);ax.set_ylim(3.6,-.6);ax.set_xlim(0,max(r['worker_wall_seconds'] for r in totals)*1.1)
    ax.set_xlabel('V5 time total (seconds)');ax.set_title('(b) V5 natural costs',loc='left');ax.xaxis.set_major_locator(MaxNLocator(nbins=3))
    fig.text(.5,.17,'■ Full pool; ● scored. Time: ● selector; □ worker.',ha='center',fontsize=8)
    fig.text(.5,.055,'Score counts exclude generation, bounds, scans and sorting costs.\nSingle-run timing totals; no robust speedup or nested-time sum.',ha='center',fontsize=8)
    return fig,{'same_pool':same_pool,'contemporaneous_v5_costs':totals,'timer_aggregation':'Separate within-method sums, nested timers not summed','speedup_claim':False}


def main(evidence,out,legacy=None):
    evidence,out=Path(evidence),Path(out);legacy=Path(legacy) if legacy else ROOT/'historical/v5/evidence'
    check_manifest(evidence);check_manifest(legacy)
    newer=json.loads((evidence/'v7_manifest.json').read_text())
    require(bool(newer.get('files_sha256')),'Missing V7 evidence pins')
    for name,pin in newer['files_sha256'].items():
        require(Path(name).name==name and sha(evidence/name)==pin,'V7 evidence hash mismatch: '+name)
    for name in ('same_pool_states.csv','same_pool_summary.json','controls_actions.csv','controls_summary.json'):
        require(name in newer['files_sha256'],'Unpinned V7 table '+name)
    same=json.loads((evidence/'same_pool_summary.json').read_text());controls=json.loads((evidence/'controls_summary.json').read_text())
    require(same['states']==301 and len(table(evidence,'same_pool_states'))==301,'Same-pool inventory differs')
    acquisitions=table(legacy,'acquisitions');batches=table(legacy,'batches')
    require(not out.exists(),'Fresh figure directory required');out.mkdir(parents=True);(out/'data').mkdir()
    v6.style();plt.rcParams['svg.hashsalt']='cut-audit-er-v7'
    specs=[contract(),v6.structure(table(legacy,'coverage')),natural(acquisitions),realized_gap(table(evidence,'evaluation_states')),
           known_law(controls,table(evidence,'controls_actions')),cost(acquisitions,batches,same)]
    records=[v6.save(fig,out,name,projection) for name,(fig,projection) in zip(PLOT_NAMES,specs)]
    result={'schema':'cut-audit-public-figures-v7','input_manifest_sha256':sha(evidence/'manifest.json'),'v7_input_manifest_sha256':sha(evidence/'v7_manifest.json'),'historical_manifest_sha256':sha(legacy/'manifest.json'),
            'renderer_sha256':sha(Path(__file__)),'helper_renderer_sha256':sha(Path(__file__).with_name('make_figures_v6.py')),
            'figures':records,'style':{'minimum_font_pt':8,'width_inches':4.8},'new_natural_experiments':0,
            'scope':'Fixed constructed-law controls and retained natural evidence; expected natural decision gaps unidentified.'}
    result['files_sha256']={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    (out/'figure_provenance.json').write_bytes(encoded(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',type=Path,default=ROOT/'evidence');p.add_argument('--legacy',type=Path,default=ROOT/'historical/v5/evidence');p.add_argument('--out',type=Path,default=ROOT/'figures')
    a=p.parse_args();print(json.dumps({'status':'PASS','figures':len(main(a.evidence,a.out,a.legacy)['figures'])}))
