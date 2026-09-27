"""Six V5 figures from strict public aggregate tables only.

No selector, hidden reference, original pair identity or experiment is loaded.
Every plotted projection is saved with the figure and source manifest hash.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch,FancyBboxPatch,Rectangle
from matplotlib.text import Text
from matplotlib.ticker import MaxNLocator
import numpy as np
if __package__ in (None,""):sys.path.insert(0,str(Path(__file__).resolve().parent))
try:from .validate_evidence import validate,table,sha,METHODS,SYNTHETIC,DATASETS,EXCLUSIONS
except ImportError:from validate_evidence import validate,table,sha,METHODS,SYNTHETIC,DATASETS,EXCLUSIONS

ROOT=Path(__file__).resolve().parents[1]
SHORT=dict(zip(METHODS,("BC","Raw","Adaptive","Cov+BC","Bound","Full","Cov single")))
COLORS=dict(zip(METHODS,("#0072B2","#D55E00","#CC79A7","#E69F00","#009E73","#222222","#56B4E9")))
MARKERS=dict(zip(METHODS,("o","s","^","D","v","P","X")))
TITLES={"wdc":"WDC","dblp_acm":"DBLP exposed","dblp_unused":"DBLP 910 (now exposed)","alaska_camera":"ALASKA Camera (conditional)"}
PLOT_NAMES=("fig01_contract","fig02_structure","fig03_natural","fig04_synthetic","fig05_mechanism","fig06_cost")

def rows(data,**filters):return [r for r in data if all(r.get(k)==v for k,v in filters.items())]
def require(ok,text):
    if not ok:raise ValueError(text)
def encoded(value):return (json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+"\n").encode("utf-8")
def style():
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":8,"axes.titlesize":8,"axes.labelsize":8,
        "xtick.labelsize":8,"ytick.labelsize":8,"legend.fontsize":8,"figure.titlesize":9,
        "pdf.fonttype":42,"ps.fonttype":42,"svg.fonttype":"none","svg.hashsalt":"cut-audit-er-v5",
        "axes.spines.top":False,"axes.spines.right":False,"axes.linewidth":.6,"lines.linewidth":1.,
        "savefig.facecolor":"white","figure.facecolor":"white"})

def label(ax,text):ax.text(0,1.05,text,transform=ax.transAxes,ha="left",va="bottom",fontsize=8,fontweight="bold")
def missing(ax,x,y,width=1,height=1):
    ax.add_patch(Rectangle((x-width/2,y-height/2),width,height,facecolor="#f6f6f6",edgecolor="#999",hatch="///",lw=.4))
    ax.text(x,y,"NA",ha="center",va="center",fontsize=8,color="#444")

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
    ax.text(5,-.30,"Gold stays in the offline evaluator.\nCertificates concern the searched proxy pool.",ha="center")
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
    fig.text(.6,.14,"Same answers; FN risk differs",fontsize=8)
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
        ax.set_yticks(range(3),["WDC","DBLP exposed","DBLP 910"]);ax.set_ylim(2.55,-.65)
    headroom={d:next(r for r in selected if r["dataset"]==d)["headroom"] for d in DATASETS}
    annotation=f'Offline FN headroom: WDC {headroom["wdc"]}; DBLP exposed {headroom["dblp_acm"]};\nDBLP 910 (now exposed) {headroom["dblp_unused"]}.'
    fig.text(.5,.205,annotation,ha="center",va="center",fontsize=8)
    fig.text(.5,.055,"Small components: ≤16 nodes and ≤16 edges.\nHatching marks uncovered structure; WDC-wide absence remains unknown.",ha="center",fontsize=8)
    return fig,{"rows":selected,"denominators":"Each panel uses its own component or FP-mass denominator","offline_only":True}

def natural(data,contrasts):
    datasets=(*DATASETS,"alaska_camera");fig,axes=plt.subplots(2,2,figsize=(4.8,4.6))
    fig.subplots_adjust(left=.17,right=.985,bottom=.29,top=.94,hspace=.73,wspace=.57)
    output=[]
    for ax,dataset in zip(axes.flat,datasets):
        rr=[r for r in data if r["dataset"]==dataset];lookup={(r["method"],r["budget"]):r for r in rr}
        values=np.array([[lookup[m,b]["loss"] if lookup[m,b]["status"]=="completed" else np.nan for b in (12,24,48)] for m in METHODS])
        finite=values[np.isfinite(values)];vmax=max(float(finite.max()) if finite.size else 1,1)
        ax.imshow(np.ma.masked_invalid(values),cmap="Greys",vmin=0,vmax=vmax,aspect="auto",interpolation="none")
        for i,m in enumerate(METHODS):
            for j,b in enumerate((12,24,48)):
                value=values[i,j]
                if not np.isfinite(value):missing(ax,j,i)
                else:ax.text(j,i,f'{int(value):,}',ha="center",va="center",fontsize=8,color="white" if value>.55*vmax else "black")
        ax.set_xticks(range(3),["B12","B24","B48"]);ax.set_yticks(range(7),[SHORT[m] for m in METHODS]);ax.tick_params(length=0)
        ax.set_title(TITLES[dataset],pad=6)
        for tick,m in zip(ax.get_yticklabels(),METHODS):tick.set_color(COLORS[m])
        for j,b in enumerate((12,24,48)):
            hits=[r for r in contrasts if r["dataset"]==dataset and r["budget"]==b and r["contrast"]=="full_vs_cut_plan_fixed"]
            for y,field in ((-.27,"delta_loss"),(-.42,"delta_fn")):
                value="NA" if not hits or hits[0]["status"]!="complete" else f'{hits[0][field]:+,}'
                ax.text((j+.5)/3,y,value,ha="center",va="top",transform=ax.transAxes,fontsize=8)
        ax.text(-.06,-.27,"ΔL",ha="right",va="top",transform=ax.transAxes,fontsize=8)
        ax.text(-.06,-.42,"ΔFN",ha="right",va="top",transform=ax.transAxes,fontsize=8)
        output.extend(rr)
    fig.text(.5,.045,"All 84 natural/conditional slots; cells show FP + FN. NA is missing.\nΔL and ΔFN are Full − raw for separately executed budget runs.\nPanel shading uses its own loss range; exact counts are printed.",ha="center",fontsize=8)
    return fig,{"acquisitions":output,"contrasts":[r for r in contrasts if r["phase"] in ("natural","external")],
                "scale":"separate per dataset; numerical annotations are the exact endpoint loss"}

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

def mechanism(batches,opportunities,exclusions):
    fig,axes=plt.subplots(2,2,figsize=(4.8,5.4));fig.subplots_adjust(left=.18,right=.98,bottom=.29,top=.93,wspace=.60,hspace=.93)
    ax=axes[0,0];use=[]
    symbols=("o","s","^")
    for j,d in enumerate(DATASETS):
        for i,m in enumerate(METHODS):
            bb=rows(batches,dataset=d,method=m);den=len(bb);num=sum(b["action_size"]>1 for b in bb)
            use.append({"dataset":d,"method":m,"multi_batches":num,"batches":den})
            if den:ax.scatter(num/den,i+(j-1)*.16,s=17,marker=symbols[j],facecolor="white" if j==1 else COLORS[m],edgecolor=COLORS[m],lw=.7)
    ax.set_yticks(range(7),[SHORT[m] for m in METHODS]);ax.set_ylim(6.6,-.6);ax.set_xlim(-.04,1.04);ax.set_xticks([0,.5,1],["0","50","100"])
    ax.set_xlabel("Multi-edge batches (%)");label(ax,"(a) Actual natural use")
    ax.legend(handles=[Line2D([],[],marker=s,ls="",color="#555",label=t,markersize=4) for s,t in zip(symbols,("WDC","DBLP exposed","DBLP 910"))],
              loc="lower right",fontsize=8,frameon=False,handletextpad=.2,borderpad=0)
    categories=[("wdc","natural"),("dblp_acm","natural"),("dblp_unused","natural"),("synthetic","H0"),("synthetic","H9")]
    names=("WDC","DBLP exp.","DBLP 910","Synth. H0","Synth. H9")
    def matching(d,h,values):return [r for r in values if r["reference"]==h and (r["phase"]=="synthetic" if d=="synthetic" else r["dataset"]==d)]
    ax=axes[0,1];availability=[]
    for i,(d,h) in enumerate(categories):
        rr=matching(d,h,opportunities);counts=[sum(r["affordable_beneficial_multi_witnesses"]>0 for r in rr),
            sum(r["affordable_beneficial_multi_witnesses"]==0 and r["absence_scope"]=="complete_small_graph" for r in rr),
            sum(r["affordable_beneficial_multi_witnesses"]==0 and r["absence_scope"]!="complete_small_graph" for r in rr)]
        availability.append({"dataset_group":d,"reference":h,"counts":counts,"batch_reference_states":len(rr)})
        left=0
        for count,color,hatch in zip(counts,("#009E73","#DDD","#FFF"),(None,None,"///")):
            width=count/len(rr) if rr else 0;ax.barh(i,width,left=left,height=.55,color=color,edgecolor="#666",hatch=hatch,lw=.4);left+=width
        if not rr:ax.text(.5,i,"NA",ha="center",va="center")
    ax.set_yticks(range(5),names);ax.set_ylim(4.6,-.6);ax.set_xlim(0,1);ax.set_xticks([0,.5,1],["0","50","100"])
    ax.set_xlabel("Batch-reference states (%)");label(ax,"(b) Multi-edge witnesses")
    ax.legend(handles=[Rectangle((0,0),1,1,facecolor=c,edgecolor="#666",hatch=h,label=t)
                       for c,h,t in (("#009E73",None,"Observed"),("#DDD",None,"None (complete scope)"),("#FFF","///","Absence unknown"))],
              loc="upper center",bbox_to_anchor=(.5,-.27),frameon=False,handlelength=1.3,handletextpad=.4,borderpad=0)
    ax=axes[1,0];exclusion_projection=[]
    bucket_names=("budget","generation","cap / filter","unscored","not selected","selected")
    bucket_map={"budget_insufficient":0,"generation_missing":1,"cap_excluded":2,"method_filtered":2,"legality_rejected":2,
                "execution_or_scoring_limit":3,"scored_not_selected":4,"baseline_edge_policy":4,"selected":5}
    palette=("#CCC","#E69F00","#CC79A7","#56B4E9","#888","#009E73")
    for i,(d,h) in enumerate(categories):
        rr=[r for r in matching(d,h,exclusions) if r["method"]=="cut_plan_cover_fixed" and r["depth"]>1 and r["beneficial"]]
        cc=[0]*6
        for r in rr:cc[bucket_map[r["first_exclusion"]]]+=r["witness_count"]
        den=sum(cc);left=0;exclusion_projection.append({"dataset_group":d,"reference":h,"counts":dict(zip(bucket_names,cc)),"witnesses":den})
        for n,color in zip(cc,palette):
            width=n/den if den else 0;ax.barh(i,width,left=left,height=.55,color=color,edgecolor="#777",lw=.4);left+=width
        if not den:ax.text(.5,i,"0 witnesses",ha="center",va="center",fontsize=8)
    ax.set_yticks(range(5),names);ax.set_ylim(4.6,-.6);ax.set_xlim(0,1);ax.set_xticks([0,.5,1],["0","50","100"])
    ax.set_xlabel("Beneficial multi-edge witnesses (%)");label(ax,"(c) Full: first recorded exclusion")
    ax=axes[1,1];cert=[]
    for i,m in enumerate(METHODS[3:]):
        rr=rows(batches,method=m);cc=[sum(bool(r["certified_positive_plan"]) for r in rr),sum(bool(r["positive_plan_selected"]) and not r["certified_positive_plan"] for r in rr),sum(not r["positive_plan_selected"] for r in rr)]
        den=len(rr);left=0;cert.append({"method":m,"certified_positive":cc[0],"uncertified_positive":cc[1],"fallback":cc[2],"batches":den})
        for count,color,hatch in zip(cc,("#009E73","#E69F00","#DDD"),(None,"..","///")):
            width=count/den if den else 0;ax.barh(i,width,left=left,height=.5,color=color,edgecolor="#666",lw=.4,hatch=hatch);left+=width
        if not den:ax.text(.5,i,"NA",ha="center",va="center")
    ax.set_yticks(range(4),[SHORT[m] for m in METHODS[3:]]);ax.set_ylim(3.6,-.6);ax.set_xlim(0,1);ax.set_xticks([0,.5,1],["0","50","100"])
    ax.set_xlabel("Recorded batches (%)");label(ax,"(d) What is certified?")
    ax.legend(handles=[Rectangle((0,0),1,1,facecolor=c,edgecolor="#666",hatch=h,label=t)
                       for c,h,t in (("#009E73",None,"Certified positive plan"),("#E69F00","..","Positive, uncertified"),("#DDD","///","Fallback"))],
              loc="upper center",bbox_to_anchor=(.5,-.27),frameon=False,handlelength=1.3,handletextpad=.4,borderpad=0)
    fig.legend(handles=[Rectangle((0,0),1,1,facecolor=c,edgecolor="#777",label=n) for n,c in zip(bucket_names,palette)],
               loc="lower center",bbox_to_anchor=(.5,.05),ncol=3,frameon=False,columnspacing=.9,handletextpad=.35)
    fig.text(.5,.012,"Repeated witnesses; exclusions are descriptive, not causal loss shares.",ha="center",fontsize=8)
    return fig,{"actual_use":use,"availability":availability,"exclusions":exclusion_projection,"certification":cert,
                "exclusion_colours":dict(zip(bucket_names,palette)),"all_exclusion_rows_available_in_public_table":True}

def cost(data):
    selected=[r for r in data if r["phase"] in ("natural","external")];datasets=list(DATASETS)
    if any(r["phase"]=="external" and r["status"]=="completed" for r in selected):datasets.append("alaska_camera")
    fig,axes=plt.subplots(len(datasets),3,figsize=(4.8,1.05*len(datasets)+1.05),squeeze=False)
    fig.subplots_adjust(left=.18,right=.98,bottom=.21,top=.92,wspace=.47,hspace=.65)
    measures=("selector_seconds","worker_wall_seconds","logical_score_accesses")
    for i,d in enumerate(datasets):
        rr=rows(selected,dataset=d)
        observed=[r["loss"] for r in rr if r["status"]=="completed"]
        low,high=(min(observed),max(observed)) if observed else (0,1)
        margin=max(1,(high-low)*.12)
        for j,measure in enumerate(measures):
            ax=axes[i,j]
            for r in rr:
                if r["status"]!="completed" or r[measure] is None:continue
                ax.scatter(r[measure],r["loss"],c=COLORS[r["method"]],marker=MARKERS[r["method"]],s={12:15,24:23,48:32}[r["budget"]],
                           edgecolor="white",linewidth=.25,zorder=3)
            if measure.endswith("seconds"):
                maximum=max((r[measure] for r in rr if r["status"]=="completed" and r[measure] is not None),default=1)
                ax.set_xlim(0,maximum*1.1);ax.xaxis.set_major_locator(MaxNLocator(nbins=3))
            else:ax.set_xscale("symlog",linthresh=1)
            ax.set_ylim(max(0,low-margin),high+margin);ax.yaxis.set_major_locator(MaxNLocator(nbins=3,integer=True))
            ax.grid(alpha=.15,lw=.4)
            if i==0:ax.set_title(("Selector time (s)","Worker wall (s)","Logical score\naccesses")[j])
            if j==0:ax.set_ylabel("FP + FN\n"+{"wdc":"WDC","dblp_acm":"DBLP exposed","dblp_unused":"DBLP 910","alaska_camera":"ALASKA"}[d])
            else:ax.tick_params(labelleft=False)
    handles=[Line2D([],[],marker=MARKERS[m],ls="",color=COLORS[m],label=SHORT[m],markersize=4) for m in METHODS]
    fig.legend(handles=handles,loc="lower center",bbox_to_anchor=(.52,.05),ncol=4,frameon=False,columnspacing=.8,handletextpad=.35)
    plotted=[r for r in selected if r["dataset"] in datasets];not_started=sum(r["phase"]=="external" and r["status"]!="completed" for r in selected)
    fig.text(.5,.015,f'{sum(r["status"]=="completed" for r in plotted)}/{len(plotted)} plotted slots complete; {not_started} conditional slots not completed.\nSizes: B12 / B24 / B48. One timing observation per cell.',ha="center",fontsize=8)
    return fig,{"acquisitions":selected,"measures":list(measures),"no_cross_round_timing_rank":True,"sizes_by_requested_budget":{"12":15,"24":23,"48":32}}

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

def main(evidence,out):
    evidence,out=Path(evidence),Path(out);checked=validate(evidence)
    require(not out.exists(),"Use a fresh figure directory; preserve older figures")
    out.mkdir(parents=True);(out/"data").mkdir();style()
    data={name:table(evidence,name) for name in ("acquisitions","reference_endpoints","coverage","contrasts","batches","opportunity_batches","opportunity_exclusions")}
    specs=[contract(),structure(data["coverage"]),natural(data["acquisitions"],data["contrasts"]),synthetic(data["reference_endpoints"]),
           mechanism(data["batches"],data["opportunity_batches"],data["opportunity_exclusions"]),cost(data["acquisitions"])]
    records=[save(fig,out,name,projection) for name,(fig,projection) in zip(PLOT_NAMES,specs)]
    provenance={"schema":"cut-audit-public-figures-v5","input_manifest_sha256":sha(evidence/"manifest.json"),"validation":checked,
        "renderer_sha256":sha(Path(__file__)),"figures":records,"style":{"minimum_font_pt":8,"width_inches":4.8,"missing":"NA and hatch"},
        "scope":"All empirical plots use public tables; Fig1 is explicitly a constructed schematic"}
    provenance["files_sha256"]={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob("*")) if p.is_file()}
    (out/"figure_provenance.json").write_bytes(encoded(provenance));return provenance

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--evidence",type=Path,default=ROOT/"evidence");p.add_argument("--out",type=Path,default=ROOT/"figures")
    a=p.parse_args();result=main(a.evidence,a.out);print(json.dumps({"status":"PASS","figures":len(result["figures"])}))
