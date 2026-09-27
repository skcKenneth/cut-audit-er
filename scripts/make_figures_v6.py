"""Six V6 figures from hash-checked public scalar tables; no research execution.

Contract, structure, synthetic, and canvas-save helpers adapt the first-party
V5 renderer, preserved at historical/v5/scripts/make_figures.py. All empirical
projections are saved; no private graph, pair, evaluator label, or score is read.
"""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch,FancyBboxPatch,Rectangle
from matplotlib.text import Text
from matplotlib.ticker import MaxNLocator
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
METHODS=('edge_betweenness','cut_plan_fixed','cut_plan_adaptive','cut_plan_cover_bccap',
         'cut_plan_bound_fixed','cut_plan_cover_fixed','cut_plan_cover_singleton')
SYNTHETIC=METHODS[2:]
DATASETS=('wdc','dblp_acm','dblp_unused')
ARMS=(METHODS[1],METHODS[3],METHODS[4],METHODS[5])
SHORT=dict(zip(METHODS,('BC','Raw','Adaptive','Cov+BC','Bound','Full','Cov single')))
COLORS=dict(zip(METHODS,('#0072B2','#D55E00','#CC79A7','#E69F00','#009E73','#222222','#56B4E9')))
MARKERS=dict(zip(METHODS,('o','s','^','D','v','P','X')))
TITLES={'wdc':'WDC','dblp_acm':'DBLP 810','dblp_unused':'DBLP 910'}
PLOT_NAMES=('fig01_contract','fig02_structure','fig03_natural','fig04_realized_gap','fig05_synthetic','fig06_cost')


def require(ok,message):
    if not ok:raise ValueError(message)


def encoded(value):return (json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scalar(value):
    if value=='':return None
    if value in ('True','False'):return value=='True'
    try:return json.loads(value)
    except (ValueError,TypeError):return value


def table(folder,name):
    with (Path(folder)/(name+'.csv')).open(encoding='utf-8-sig',newline='') as stream:
        return [{k:scalar(v) for k,v in row.items()} for row in csv.DictReader(stream)]


def check_manifest(folder):
    folder=Path(folder).resolve();manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8-sig'))
    pins=manifest.get('files_sha256',{})
    require(bool(pins),'Missing evidence pins')
    for name,pin in pins.items():
        parts=Path(name).parts
        require(not Path(name).is_absolute() and all(p not in ('.','..') for p in parts),'Unsafe evidence member')
        path=(folder/name).resolve()
        require(path.is_relative_to(folder) and path.is_file() and sha(path)==pin,'Evidence hash mismatch: '+name)
    return manifest


def style():
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':8,'axes.titlesize':8,'axes.labelsize':8,
        'xtick.labelsize':8,'ytick.labelsize':8,'legend.fontsize':8,'figure.titlesize':9,
        'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none','svg.hashsalt':'cut-audit-er-v6',
        'axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.6,'lines.linewidth':1.,
        'savefig.facecolor':'white','figure.facecolor':'white'})


def contract():
    fig=plt.figure(figsize=(4.8,2.85));ax=fig.add_axes([.02,.47,.96,.48]);ax.set_xlim(0,10);ax.set_ylim(0,3.8);ax.axis("off")
    blocks=[(.15,2.3,2.0,1.05,"Visible graph\n+ paid answers"),(2.72,2.3,2.1,1.05,"Generate\n+ validate bonds"),
            (5.4,2.3,2.0,1.05,"BC cap /\nbound screening"),(7.93,2.3,1.9,1.05,"Commit batch\n≤ budget")]
    for x,y,w,h,text in blocks:
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=.05",facecolor="#E8EEF2",edgecolor="#64717D",lw=.7))
        ax.text(x+w/2,y+h/2,text,ha="center",va="center",fontsize=8)
    for first,second in zip(blocks,blocks[1:]):
        ax.add_patch(FancyArrowPatch((first[0]+first[2]+.04,2.8),(second[0]-.07,2.8),arrowstyle="-|>",mutation_scale=8,color="#555"))
    branches=[(1.8,"Positive", "Keep + protect edge", "#0072B2"),(5,"Negative, no split","Spend; graph connected","#E69F00"),
              (8.2,"Negative, split","Split; evaluate FP / FN","#009E73")]
    for x,title,detail,color in branches:
        ax.text(x,1.3,title,ha="center",color=color,fontweight="bold");ax.text(x,.76,detail,ha="center")
    ax.plot([.5,9.6],[1.8,1.8],color="#AAA",lw=.6)
    ax.text(5,-.30,"Gold stays in the offline evaluator.\nCertificate: computed proxy maximum in the searched pool.",ha="center")
    gax=fig.add_axes([.03,.14,.54,.27]);gax.set_xlim(-.7,4.8);gax.set_ylim(-.8,.9);gax.axis("off")
    pos={f"r{3*g+i}":(2*g+dx,dy) for g in range(3) for i,(dx,dy) in enumerate(((-.28,.36),(-.28,-.36),(.34,0)))}
    internal=[];boundary=[]
    for g in range(3):
        for i,j in ((0,1),(0,2),(1,2)):
            u,v=f"r{3*g+i}",f"r{3*g+j}";internal.append([u,v]);gax.plot([pos[u][0],pos[v][0]],[pos[u][1],pos[v][1]],color="#777",lw=.8)
    for g in range(2):
        for i in range(3):
            u,v=f"r{3*g+i}",f"r{3*g+3+i}";boundary.append([u,v]);gax.plot([pos[u][0],pos[v][0]],[pos[u][1],pos[v][1]],color="#0072B2",lw=.7,alpha=.6)
    for x,y in pos.values():gax.scatter(x,y,s=17,facecolor="white",edgecolor="#333",lw=.6,zorder=4)
    for g,text in enumerate(("A","B","C")):gax.text(2*g,-.65,text,ha="center")
    fig.text(.6,.365,"Constructed: k = 3 shown",fontsize=8)
    fig.text(.6,.29,"H0: A, B, C distinct",fontsize=8)
    fig.text(.6,.215,"H9: A and C share an entity",fontsize=8)
    fig.text(.6,.14,"Same answers; headroom differs",fontsize=8)
    fig.text(.5,.025,"Constructed illustration, not an additional natural-data experiment.\nKeep the first k links per boundary.",ha="center",fontsize=8)
    return fig,{"scope":"Declared synthetic construction and selector/evaluator contract only","k_shown":3,
        "internal_edges":internal,"boundary_edges":boundary,"H0_groups":["A","B","C"],"H9_groups":["A","B","A"]}

def structure(data):
    selected=[r for r in data if r["phase"]=="natural"]
    fig,axes=plt.subplots(1,2,figsize=(4.8,2.75),sharey=True)
    fig.subplots_adjust(left=.26,right=.97,bottom=.43,top=.87,wspace=.40)
    for col,(num,den,title) in enumerate((("exact_components","components","Components covered"),("covered_fp","initial_fp","FP mass covered"))):
        ax=axes[col]
        for i,dataset in enumerate(DATASETS):
            r=next(r for r in selected if r["dataset"]==dataset);ratio=r[num]/r[den] if r[den] else 0
            ax.barh(i,1,color="#ECECEC",height=.43,edgecolor="#777",hatch="///" if ratio<1 else None,lw=.5)
            ax.barh(i,ratio,color="#0072B2",height=.43,edgecolor="#333",lw=.5)
            ax.text(.5,i-.34,f'{r[num]:,} / {r[den]:,}',ha="center",va="bottom",fontsize=8)
        ax.set_xlim(0,1);ax.set_xticks([0,.5,1],["0","50","100"]);ax.set_xlabel("Coverage (%)");ax.set_title(title)
        ax.set_yticks(range(3),["WDC","DBLP 810","DBLP 910"]);ax.set_ylim(2.55,-.65)
    headroom={d:next(r for r in selected if r["dataset"]==d)["headroom"] for d in DATASETS}
    annotation=f'Offline FN headroom: WDC {headroom["wdc"]}; DBLP 810 {headroom["dblp_acm"]};\nDBLP 910 {headroom["dblp_unused"]}. All graphs are now exposed development data.'
    fig.text(.5,.205,annotation,ha="center",va="center",fontsize=8)
    fig.text(.5,.055,"Small components: ≤16 nodes and ≤16 edges.\nHatching marks unsolved structure, not evidence of absent opportunity.",ha="center",fontsize=8)
    return fig,{"rows":selected,"denominators":"Each panel uses its own component or FP-mass denominator","offline_only":True}

def synthetic(data):
    fig,axes=plt.subplots(1,5,figsize=(4.8,3.8),sharey=True)
    fig.subplots_adjust(left=.135,right=.985,bottom=.28,top=.87,wspace=.18)
    groups=[(h,k,p) for h in ("H0","H9") for k in (1,2,3) for p in ("uniform","ranked")]
    lookup={(r["reference"],r["dataset"],r["method"],r["budget"]):r for r in data}
    budgets=(1,2,3,4,6);palette=plt.get_cmap("YlGnBu")
    for ax,method in zip(axes,SYNTHETIC):
        matrix=np.array([[lookup[h,f"k{k}_{p}",method,b]["loss"] if lookup[h,f"k{k}_{p}",method,b]["status"]=="completed" else np.nan
                          for b in budgets] for h,k,p in groups])
        ax.imshow(np.ma.masked_invalid(matrix),cmap=palette,vmin=0,vmax=36,aspect="auto",interpolation="none")
        require(all(int(v) in (0,9,18,27) for v in matrix[np.isfinite(matrix)]),"Unexpected synthetic loss; revise exact-loss key")
        for i in range(len(groups)):
            for j in range(5):
                if not np.isfinite(matrix[i,j]):
                    ax.add_patch(Rectangle((j-.5,i-.5),1,1,facecolor="#EEE",edgecolor="#777",hatch="///",lw=.4))
        ax.set_xticks(np.arange(-.5,5,1),minor=True);ax.set_yticks(np.arange(-.5,12,1),minor=True)
        ax.grid(which="minor",color="white",linewidth=.7);ax.tick_params(which="minor",length=0)
        ax.axhline(5.5,color="white",lw=2);ax.set_title(SHORT[method],color=COLORS[method]);ax.set_xticks(range(5),budgets)
        ax.set_yticks(range(12),[f'{h}: {k}{"U" if p=="uniform" else "R"}' for h,k,p in groups]);ax.tick_params(length=0)
    fig.text(.5,.21,"Requested budgets: 1, 2, 3, 4, 6",ha="center",fontsize=8)
    handles=[Rectangle((0,0),1,1,facecolor=palette(v/36),edgecolor="#777",label=str(v)) for v in (0,9,18,27)]
    handles.append(Rectangle((0,0),1,1,facecolor="#EEE",edgecolor="#777",hatch="///",label="NA"))
    fig.legend(handles=handles,loc="lower center",bbox_to_anchor=(.5,.07),ncol=5,title="Exact endpoint FP + FN",title_fontsize=8,frameon=False)
    fig.text(.5,.015,"All 300 reference endpoints (150 acquisitions). U/R = uniform/ranked scores.\nH0/H9 reuse each paid trace; these paired evaluations are dependent.",ha="center",fontsize=8)
    return fig,{"endpoints":data,"quantity":"FP+FN","global_colour_range":[0,36],"independent_reference_evaluations":False}

def save(fig,out,name,projection):
    fig.canvas.draw()
    # Log locators allocate out-of-range ticks that Matplotlib omits when
    # drawing. Hide their unused Text objects explicitly before the bounds
    # check so invisible off-axis tick labels are not reported as clipping.
    for ax in fig.axes:
        for axis,limits in ((ax.xaxis,ax.get_xlim()),(ax.yaxis,ax.get_ylim())):
            low,high=sorted(limits)
            for tick in axis.get_major_ticks()+axis.get_minor_ticks():
                if not low<=tick.get_loc()<=high:
                    tick.label1.set_visible(False);tick.label2.set_visible(False)
    fig.canvas.draw()
    texts=[t for t in fig.findobj(Text) if t.get_visible() and t.get_text()]
    fonts=[t.get_fontsize() for t in texts]
    require(not fonts or min(fonts)>=8,"Figure text below8pt")
    renderer=fig.canvas.get_renderer();canvas=fig.bbox
    for t in texts:
        box=t.get_window_extent(renderer)
        require(box.x0>=canvas.x0-1 and box.x1<=canvas.x1+1 and box.y0>=canvas.y0-1 and box.y1<=canvas.y1+1,
                "Text outside figure canvas: "+t.get_text())
    for ext in ("pdf","svg","png"):
        metadata={"Creator":"CUT-AUDIT-ER deterministic public-table renderer"}
        if ext=="pdf":metadata.update(CreationDate=None,ModDate=None)
        if ext=="svg":metadata.update(Date=None)
        fig.savefig(out/(name+"."+ext),dpi=240,metadata=metadata)
    path=out/"data"/(name+".json");path.write_bytes(encoded(projection))
    result={"name":name,"width_inches":fig.get_figwidth(),"height_inches":fig.get_figheight(),"minimum_font_pt":min(fonts),"text_bounds_within_canvas":True,
        "files_sha256":{name+"."+ext:sha(out/(name+"."+ext)) for ext in ("pdf","svg","png")},"projection_sha256":sha(path)}
    plt.close(fig);return result


def natural(acquisitions):
    rr=[r for r in acquisitions if r['phase']=='natural']
    require(len(rr)==63,'All 63 existing natural slots required')
    lookup={(r['dataset'],r['method'],r['budget']):r for r in rr}
    require(len(lookup)==63,'Duplicate natural endpoint')
    fig,axes=plt.subplots(2,2,figsize=(4.8,4.55))
    fig.subplots_adjust(left=.185,right=.975,top=.94,bottom=.24,wspace=.77,hspace=.68)
    for ax,dataset in zip(axes.flat,DATASETS):
        values=np.array([[lookup[dataset,m,b]['loss'] if lookup[dataset,m,b]['status']=='completed'
                          else np.nan for b in (12,24,48)] for m in METHODS])
        finite=values[np.isfinite(values)]
        low,high=(float(min(finite)),float(max(finite))) if len(finite) else (0.,1.)
        norm=Normalize(low,high if high>low else low+1)
        ax.imshow(np.ma.masked_invalid(values),cmap='Blues',norm=norm,aspect='auto')
        for i in range(7):
            for j in range(3):
                value=values[i,j]
                ax.text(j,i,str(int(value)) if np.isfinite(value) else 'NA',ha='center',va='center',
                        color='white' if np.isfinite(value) and norm(value)>.58 else '#222',fontsize=8)
        ax.set_yticks(range(7),[SHORT[m] for m in METHODS]);ax.set_xticks(range(3),[12,24,48])
        ax.set_title(TITLES[dataset]);ax.set_xlabel('Requested budget');ax.tick_params(length=0)
    ax=axes.flat[3];contrasts=[]
    for i,(dataset,budget) in enumerate((d,b) for d in DATASETS for b in (12,24,48)):
        full=lookup[dataset,'cut_plan_cover_fixed',budget]
        for control,offset,color,marker in (('cut_plan_fixed',-.12,COLORS['cut_plan_fixed'],'s'),
                                             ('edge_betweenness',.12,COLORS['edge_betweenness'],'o')):
            base=lookup[dataset,control,budget]
            delta=full['loss']-base['loss'] if full['status']==base['status']=='completed' else None
            contrasts.append({'dataset':dataset,'budget':budget,'control':control,'delta_loss':delta})
            if delta is not None:ax.scatter(delta,i+offset,s=20,marker=marker,color=color,edgecolor='white',lw=.25,zorder=3)
    ax.axvline(0,color='#777',lw=.65);ax.set_ylim(8.6,-.6)
    ax.set_yticks(range(9),[f'{d} {b}' for d in ('WDC','D810','D910') for b in (12,24,48)])
    ax.set_xlim(-10000,5000);ax.set_xticks([-10000,0,5000],['−10k','0','5k'])
    ax.set_title('Full − control');ax.set_xlabel('Δ(FP + FN)')
    fig.legend(handles=[Line2D([],[],marker=m,ls='',color=c,label=l,markersize=4)
                       for m,c,l in [('s',COLORS['cut_plan_fixed'],'Raw'),('o',COLORS['edge_betweenness'],'BC')]],
              loc='lower center',bbox_to_anchor=(.5,.126),ncol=2,frameon=False,handletextpad=.3,columnspacing=.7)
    fig.text(.5,.060,'All 63 V5 natural endpoints; cells give exact FP + FN.\n'
             'Panel-specific colour scales; related budget runs are dependent.',ha='center',fontsize=8)
    fig.text(.5,.015,'V6 Camera: 21 unstarted slots; official download expired. No outcome panel.',ha='center',fontsize=8)
    return fig,{'acquisitions':rr,'contrasts':contrasts,'heatmap_scales':'separate per cohort',
                'external_status':'not_started_download_blocked','external_slots':21}


def evaluation_groups(data):
    groups=[(d,'natural',TITLES[d]) for d in DATASETS]
    groups += [(f'k{k}_{p}',h,f'{h} k{k} '+('U' if p=='uniform' else 'R'))
               for h in ('H0','H9') for k in (1,2,3) for p in ('uniform','ranked')]
    result=[]
    for dataset,reference,label in groups:
        rr=[r for r in data if r['dataset']==dataset and r['reference']==reference]
        complete=[r for r in rr if r['single_batch_oracle_gap'] is not None]
        positive=sum(r['single_batch_oracle_gap']>0 for r in complete)
        partial=sum(r.get('gap_scope','').startswith('lower_bound') for r in complete)
        result.append({'dataset':dataset,'reference':reference,'label':label,'planned':len(rr),
                       'evaluated':len(complete),'positive':positive,'partial_lower_bounds':partial,
                       'unknown':len(rr)-len(complete)})
    return result


def realized_gap(data):
    groups=evaluation_groups(data)
    require(len(data)==361 and all(g['planned'] for g in groups),'Complete 361 reference-slot inventory required')
    fig=plt.figure(figsize=(4.8,4.75))
    grid=fig.add_gridspec(2,2,left=.225,right=.975,top=.94,bottom=.33,wspace=.67,hspace=.72,width_ratios=[1.03,1])
    counts=fig.add_subplot(grid[:,0])
    for i,g in enumerate(groups):
        ratio=g['positive']/g['evaluated'] if g['evaluated'] else 0.
        counts.barh(i,ratio,height=.6,color='#009E73',edgecolor='#222',lw=.4)
        suffix=(' *' if g['unknown'] else '')+(' †' if g['partial_lower_bounds'] else '')
        counts.text(1.05,i,f"{g['positive']}/{g['evaluated']}"+suffix,ha='left',va='center',fontsize=8)
    counts.set_yticks(range(len(groups)),[g['label'] for g in groups]);counts.set_ylim(len(groups)-.4,-.8)
    counts.set_xlim(0,1.55);counts.set_xticks([0,.5,1],['0','50','100'])
    counts.set_xlabel('States with positive gap (%)');counts.set_title('(a) All fixed groups',loc='left')
    counts.axhline(2.5,color='#AAA',lw=.7);counts.axhline(8.5,color='#AAA',lw=.7)
    selected=[r for r in data if r['single_batch_oracle_gap'] is not None]
    symbols=('o','s','^');natural_colors=('#0072B2','#D55E00','#009E73')
    for index,phase in enumerate(('natural','synthetic')):
        ax=fig.add_subplot(grid[index,1]);rr=[r for r in selected if r['phase']==phase]
        if phase=='natural':
            series=[(d,TITLES[d],c,m) for d,c,m in zip(DATASETS,natural_colors,symbols)]
            for d,title,color,marker in series:
                points=[r for r in rr if r['dataset']==d]
                ax.scatter([r['selected_gain_per_query'] for r in points],[r['best_known_gain_per_query'] for r in points],
                           s=20,color=color,marker=marker,lw=.35,edgecolor='white',label=title,alpha=.85)
        else:
            for h,color,marker in [('H0','#0072B2','o'),('H9','#D55E00','^')]:
                points=[r for r in rr if r['reference']==h]
                ax.scatter([r['selected_gain_per_query'] for r in points],[r['best_known_gain_per_query'] for r in points],
                           s=22,color=color,marker=marker,lw=.35,edgecolor='white',label=h,alpha=.8)
        values=[v for r in rr for v in (r['selected_gain_per_query'],r['best_known_gain_per_query'])]
        lo=min([0,*values]);hi=max([1,*values]);margin=.08*(hi-lo)
        ax.plot([lo,hi],[lo,hi],ls='--',color='#777',lw=.7,zorder=1)
        if phase=='natural':
            ax.set_xscale('symlog',linthresh=1);ax.set_yscale('symlog',linthresh=1)
            limits=(lo-max(.1,.08*abs(lo)),hi+margin)
            ax.set_xlim(*limits);ax.set_ylim(*limits)
            ticks=[0.]+[float(10**power) for power in range(int(np.floor(np.log10(max(1,limits[1]))))+1)]
            if limits[0]<=-1:
                ticks.extend(-float(10**power) for power in range(int(np.floor(np.log10(abs(limits[0]))))+1))
            ticks=sorted(ticks)
            labels=[f'{int(value/1000)}k' if abs(value)>=1000 else str(int(value)) for value in ticks]
            ax.set_xticks(ticks,labels);ax.set_yticks(ticks,labels)
        else:
            ax.set_xlim(lo-margin,hi+margin);ax.set_ylim(lo-margin,hi+margin)
            ax.xaxis.set_major_locator(MaxNLocator(nbins=3));ax.yaxis.set_major_locator(MaxNLocator(nbins=3))
        ax.set_xlabel('Selected gain / query');ax.set_ylabel('Best known gain / query')
        ax.set_title('(b) Natural states' if phase=='natural' else '(c) Synthetic states',loc='left')
        if phase=='natural':
            handles,labels=ax.get_legend_handles_labels()
            fig.legend(handles,labels,loc='lower center',bbox_to_anchor=(.5,.165),ncol=3,
                       fontsize=8,frameon=False,handletextpad=.15,columnspacing=.7)
        else:
            ax.legend(loc='upper left',fontsize=8,frameon=False,handletextpad=.15,borderpad=0,labelspacing=.15)
    fig.text(.5,.105,'All Full-reached states; overlapping points remain in data.\n'
             'Counts: positive / evaluated; * missing, † lower bounds; U/R = recipes.',ha='center',fontsize=8)
    fig.text(.5,.025,'Natural axes: symlog outside [−1,1]; no-action value 0 included.\n'
             'Realized, dependent comparisons: not expected regret or population rates.',ha='center',fontsize=8)
    return fig,{'states':data,'groups':groups,'points_plotted':len(selected),
                'gap_scope':'Clairvoyant realized single batch, per paid query; never expected regret',
                'natural_axis_scale':'symlog, linear threshold 1; exact values remain in public table',
                'missing_states':len(data)-len(selected),'complete_inventory_retained':True}


def cost(acquisitions,batches):
    rr=[r for r in acquisitions if r['phase']=='natural' and r['method'] in ARMS]
    require(len(rr)==36,'Four fixed arms across all nine natural conditions required')
    totals=[]
    for method in ARMS:
        arm=[r for r in rr if r['method']==method]
        bb=[b for b in batches if b['phase']=='natural' and b['method']==method]
        totals.append({'method':method,'slots':len(arm),'completed':sum(r['status']=='completed' for r in arm),
                       'full_scores':sum(b['scored_candidate_actions'] or 0 for b in bb),
                       **{key:sum(r[key] or 0 for r in arm) for key in ('logical_score_accesses','selector_seconds','worker_wall_seconds')},
                       'numeric_scan_seconds':sum(b['numeric_preprocessing_seconds'] or 0 for b in bb),
                       'enumeration_seconds':sum(b['enumeration_seconds'] or 0 for b in bb),
                       'nested_timers_not_summed':True})
    fig,axes=plt.subplots(2,2,figsize=(4.8,3.45))
    fig.subplots_adjust(left=.17,right=.97,top=.9,bottom=.27,wspace=.68,hspace=.68)
    measures=[('full_scores','(a) Full proxy scores',1),('logical_score_accesses','(b) Logical accesses (M)',1e6),
              ('selector_seconds','(c) Selector time (s)',1),('worker_wall_seconds','(d) Worker wall (s)',1)]
    for ax,(key,title,unit) in zip(axes.flat,measures):
        vals=[r[key]/unit for r in totals]
        for i,(row,value) in enumerate(zip(totals,vals)):
            ax.barh(i,value,height=.55,color=COLORS[row['method']],edgecolor='#333',lw=.4,
                    hatch=('','//','..','xx')[i])
            text=f'{value:,.0f}' if key=='full_scores' else f'{value:.2f}'
            ax.text(value+max(vals)*.03,i,text,ha='left',va='center',fontsize=8)
        ax.set_yticks(range(4),[SHORT[m] for m in ARMS]);ax.set_ylim(3.7,-.7)
        ax.set_xlim(0,max(vals)*1.6 if max(vals)>0 else 1)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=3));ax.set_title(title,loc='left')
    fig.text(.5,.12,'Sums over the same nine V5 natural conditions, one run per cell.\n'
             'Full score counts, logical accesses and time are distinct costs.',ha='center',fontsize=8)
    fig.text(.5,.03,'Timers are not stacked; nested components cannot be added.\n'
             'No repeated-timing or robust speed-ratio claim.',ha='center',fontsize=8)
    return fig,{'acquisitions':rr,'totals':totals,'aggregation':'Within-method sums of the same nine contemporaneous cells',
                'four_arms':list(ARMS),'missing_slots':sum(r['status']!='completed' for r in rr)}


def main(evidence,out,legacy=None):
    evidence,out=Path(evidence),Path(out);legacy=Path(legacy) if legacy else ROOT/'historical/v5/evidence'
    check_manifest(evidence);check_manifest(legacy)
    visible=table(evidence,'visible_states');evaluation=table(evidence,'evaluation_states')
    require(len(visible)==301 and len({r['state'] for r in visible})==301,'Physical-state inventory differs')
    require(len(evaluation)==361,'Reference inventory differs')
    acquisitions=table(legacy,'acquisitions');refs=table(legacy,'reference_endpoints')
    require(len(refs)==300,'All 300 synthetic reference outcomes required')
    require(not out.exists(),'Use a fresh figure directory; preserve prior renders')
    out.mkdir(parents=True);(out/'data').mkdir();style()
    specs=[contract(),structure(table(legacy,'coverage')),natural(acquisitions),realized_gap(evaluation),
           synthetic(refs),cost(acquisitions,table(legacy,'batches'))]
    records=[save(fig,out,name,projection) for name,(fig,projection) in zip(PLOT_NAMES,specs)]
    provenance={'schema':'cut-audit-public-figures-v6','input_manifest_sha256':sha(evidence/'manifest.json'),
        'historical_manifest_sha256':sha(legacy/'manifest.json'),'renderer_sha256':sha(Path(__file__)),
        'figures':records,'style':{'minimum_font_pt':8,'width_inches':4.8,'synthetic_is_natural':False},
        'scope':'Public scalar evidence; contract diagram is a construction; no private pair identity validation',
        'external_status':'Official Camera download expired; no new external outcomes'}
    provenance['files_sha256']={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    (out/'figure_provenance.json').write_bytes(encoded(provenance));return provenance


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,default=ROOT/'evidence')
    parser.add_argument('--legacy',type=Path,default=ROOT/'historical/v5/evidence')
    parser.add_argument('--out',type=Path,default=ROOT/'figures')
    args=parser.parse_args();result=main(args.evidence,args.out,args.legacy)
    print(json.dumps({'status':'PASS','figures':len(result['figures'])}))
