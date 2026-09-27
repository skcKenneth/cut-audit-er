"""Six V4 figures from hash-validated public tables; no selector or gold loader."""
from pathlib import Path
import argparse
import json
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.validate_evidence import table,validate,sha
from scripts.legacy_v3 import make_figures as old
from scripts.legacy_v3.schema import load_evidence

METHODS=old.METHODS;COLORS=old.COLORS;MARKERS=old.MARKERS;STYLES=old.STYLES
DATASETS=('wdc','dblp_acm','dblp_unused')
TITLES={'wdc':'WDC: exposed','dblp_acm':'DBLP: exposed','dblp_unused':'DBLP: unused'}

def rows(data,**kw):return [r for r in data if all(r[k]==v for k,v in kw.items())]
def one(data,**kw):
    rr=rows(data,**kw)
    if len(rr)!=1:raise ValueError('Projection row missing or duplicate: '+str(kw))
    return rr[0]

def contract():
    fig,description=old.contract_figure()
    fig.set_size_inches(4.8,2.5)
    for ax in fig.axes:
        box=ax.get_position();ax.set_position([box.x0,.285,box.width,.70])
    fig.texts[0].set_position((.025,.22));fig.texts[1].set_position((.025,.165))
    ax=fig.add_axes([.03,.01,.94,.14]);ax.axis('off');ax.set_xlim(-.02,1.025)
    labels=['Opportunity\nfeasible cuts + budget','Use\ncommitted batches','Incremental value\npaired trajectories']
    for i,label in enumerate(labels):
        x=i*.345
        ax.add_patch(FancyBboxPatch((x,.17),.30,.70,boxstyle='round,pad=.015',facecolor=['#E6F0F7','#FAE9DF','#E4F1EA'][i],edgecolor='#888',lw=.6))
        ax.text(x+.15,.52,label,ha='center',va='center',fontsize=8)
        if i<2:ax.annotate('',xy=(x+.34,.52),xytext=(x+.31,.52),arrowprops={'arrowstyle':'->','lw':.8})
    return fig,{'scope':'Illustrative contract; the three-layer procedure is not a novelty claim',
                'contract':description,'three_layers':labels}

def structure(data):
    fig,axes=plt.subplots(1,2,figsize=(4.8,2.5),gridspec_kw={'width_ratios':[1.25,1]})
    fig.subplots_adjust(left=.25,right=.97,bottom=.27,top=.79,wspace=.40)
    for i,d in enumerate(DATASETS):
        r=one(data,dataset=d)
        if r['components'] is None:
            axes[0].text(0,i,'Unavailable',va='center');axes[1].text(0,i,'Unavailable',va='center');continue
        comp=100*r['exact_components']/r['components']
        error=100*r['covered_fp']/r['initial_fp'] if r['initial_fp'] else None
        axes[0].scatter(comp,i-.10,c='#0072B2',s=32)
        if error is not None:axes[0].scatter(error,i+.10,facecolors='white',edgecolors='#D55E00',marker='s',s=30)
        else:axes[0].text(3,i+.10,'FP denominator = 0',va='center')
        axes[0].text(8,i-.23,f"{r['exact_components']:,}/{r['components']:,}",color='#0072B2',va='center')
        if error is not None:
            axes[0].text(8,i+.23,f"{r['covered_fp']:,}/{r['initial_fp']:,}",color='#A44500',va='center')
        axes[1].barh(i,r['headroom'],height=.42,color='#6B8797')
        axes[1].text(r['headroom'],i,f" {r['headroom']:,}",va='center')
    axes[0].set_yticks(range(3),[TITLES[d] for d in DATASETS]);axes[1].set_yticks([])
    for ax in axes:ax.set_ylim(2.6,-.6);ax.grid(axis='x',alpha=.15)
    axes[0].set_xlim(-5,108);axes[0].set_xticks([0,50,100]);axes[0].set_xlabel('Exact diagnostic\ncoverage (%)')
    axes[1].set_xlabel('Additional-FN\nheadroom');axes[1].margins(x=.35)
    fig.legend(handles=[Line2D([],[],color='#0072B2',marker='o',ls='',label='Components'),Line2D([],[],color='#D55E00',marker='s',mfc='white',ls='',label='Initial FP mass')],loc='upper center',ncol=2)
    fig.text(.5,.025,'Offline gold diagnostics; WDC nonzero-budget optimum is incomplete.',ha='center')
    return fig,data

def outcomes(data):
    fig,axes=plt.subplots(2,3,figsize=(4.8,3.6),gridspec_kw={'height_ratios':[1.2,1]})
    fig.subplots_adjust(left=.13,right=.98,bottom=.25,top=.82,hspace=.62,wspace=.67)
    old.method_legend(fig)
    for j,d in enumerate(DATASETS):
        for mi,m in enumerate(METHODS):
            rr=[one(data,dataset=d,method=m,budget=b) for b in (12,24,48)]
            vals=[r['loss'] if r['status']=='completed' else np.nan for r in rr]
            axes[0,j].plot(np.arange(3)+(mi-1)*.065,vals,color=COLORS[m],marker=MARKERS[m],ls=STYLES[m],markersize=4,mfc='white' if m==METHODS[2] else COLORS[m])
        axes[0,j].set_title(TITLES[d],fontsize=8)
        for idx,m in enumerate((METHODS[2],METHODS[0])):
            differences=[]
            for b in (12,24,48):
                a=one(data,dataset=d,method=METHODS[1],budget=b);c=one(data,dataset=d,method=m,budget=b)
                differences.append(a['loss']-c['loss'] if a['status']==c['status']=='completed' else np.nan)
            axes[1,j].plot(np.arange(3)+(idx-.5)*.08,differences,color=COLORS[m],marker=('D','o')[idx],ls=('--',':')[idx],markersize=4)
        axes[1,j].axhline(0,color='#999',lw=.7)
        if d=='dblp_unused':
            axes[0,j].set_ylim(52,58);axes[0,j].set_yticks([53,55,57])
            axes[1,j].set_ylim(-1,1);axes[1,j].set_yticks([-1,0,1])
        for ax in axes[:,j]:
            ax.set_xticks(range(3),['12','24','48']);ax.grid(alpha=.15)
            ax.ticklabel_format(axis='y',style='plain');ax.yaxis.get_offset_text().set_fontsize(8)
            ax.yaxis.set_major_locator(MaxNLocator(nbins=3,integer=True))
    for ax in axes[:,0]:ax.yaxis.set_major_formatter(FuncFormatter(lambda v,pos:f'{v/1000:g}k' if v else '0'))
    axes[0,0].set_ylabel('FP + FN',labelpad=2);axes[1,0].set_ylabel('Raw loss difference',labelpad=2)
    fig.text(.5,.157,'Independent requested budget',ha='center')
    fig.text(.5,.105,'◆ raw − singleton   ● raw − BC; negative favours raw.',ha='center')
    fig.text(.5,.059,'Small horizontal offsets reveal ties; all 27 endpoints are retained.',ha='center')
    fig.text(.5,.013,'Unused DBLP: same benchmark; nine endpoints remain at loss 55.',ha='center')
    return fig,data

def controlled(data):
    fig,axes=plt.subplots(1,2,figsize=(4.8,3.5))
    fig.subplots_adjust(left=.22,right=.97,bottom=.26,top=.73,wspace=.25)
    keys=[(k,p) for k in (1,2,3) for p in ('uniform','ranked')]
    matrices=[]
    for h in ('H0','H9'):
        a=[]
        for k,p in keys:
            row=[]
            for b in (1,2,3,4,6):
                raw=one(data,k=k,profile=p,reference=h,method=METHODS[1],budget=b)
                single=one(data,k=k,profile=p,reference=h,method=METHODS[2],budget=b)
                row.append(raw['loss']-single['loss'] if raw['status']==single['status']=='completed' else np.nan)
            a.append(row)
        matrices.append(np.array(a))
    maximum=max(1,max(float(np.nanmax(np.abs(a))) if np.isfinite(a).any() else 0 for a in matrices))
    for j,(h,a) in enumerate(zip(('H0','H9'),matrices)):
        im=axes[j].imshow(a,cmap='RdBu_r',vmin=-maximum,vmax=maximum,aspect='auto')
        for y in range(6):
            for x in range(5):
                v=a[y,x]
                if not np.isfinite(v):
                    axes[j].add_patch(Rectangle((x-.5,y-.5),1,1,facecolor='#E0E0E0',edgecolor='#888',hatch='///',lw=.6))
                axes[j].text(x,y,'NA' if not np.isfinite(v) else f'{v:+g}' if v else '0',ha='center',va='center',
                             color='white' if np.isfinite(v) and abs(v)>.65*maximum else '#222',
                             bbox={'facecolor':'#E0E0E0','edgecolor':'none','pad':.5} if not np.isfinite(v) else None)
        axes[j].set_xticks(range(5),['1','2','3','4','6'])
        axes[j].set_yticks(range(6),[f'k={k}  {"U" if p=="uniform" else "R"}' for k,p in keys] if j==0 else [])
        axes[j].set_title(f'{h}: headroom {0 if h=="H0" else 9}')
    fig.text(.5,.968,'Synthetic mechanism: three connected triangles',ha='center',weight='bold')
    schematic=fig.add_axes([.10,.834,.80,.10]);schematic.axis('off')
    positions={f'r{3*g+i}':(g*2.0+(.18 if i==1 else -.18),(1,0,-1)[i])
               for g in range(3) for i in range(3)}
    internal=[];boundary=[]
    for g,label in enumerate('ABC'):
        for i,j in ((0,1),(0,2),(1,2)):
            u,v=f'r{3*g+i}',f'r{3*g+j}';internal.append([u,v])
            schematic.plot([positions[u][0],positions[v][0]],[positions[u][1],positions[v][1]],color='#888',lw=1,zorder=1)
        schematic.text(g*2+.43,0,label,va='center',ha='left',fontsize=8,
                       bbox={'facecolor':'white','edgecolor':'none','pad':1})
    for g in range(2):
        for i in range(3):
            u,v=f'r{3*g+i}',f'r{3*g+3+i}';boundary.append([u,v])
            schematic.plot([positions[u][0],positions[v][0]],[positions[u][1],positions[v][1]],color='#0072B2',lw=.75,alpha=.70,zorder=0)
    for node,(x,y) in positions.items():
        schematic.scatter(x,y,s=17,facecolors='white',edgecolors='#333',linewidths=.65,zorder=3)
    schematic.set_xlim(-.6,4.8);schematic.set_ylim(-1.4,1.4)
    fig.text(.5,.795,'k = 3 shown; keep the first k ordered boundary links.',ha='center')
    fig.text(.5,.169,'Requested budget',ha='center')
    fig.text(.5,.115,'Raw − singleton loss; a negative value would favour raw.',ha='center')
    fig.text(.5,.065,'U/R = uniform/ranked scores. Hatched NA = interrupted, not zero.',ha='center')
    fig.text(.5,.015,'One interrupted acquisition leaves two reference cells missing.',ha='center')
    return fig,{'endpoints':data,'contrast':'raw_minus_singleton','independent_observations':False,
                'illustration':{'scope':'Declared construction, not an additional experiment','k':3,
                                'nodes':list(positions),'internal_edges':internal,'boundary_edges':boundary,
                                'boundary_subset_rule':'Keep indices i=0..k-1 on each adjacent-group boundary.',
                                'reference_H9':'A and C share the evaluation label; visible graph and edge answers are unchanged.'}}

def use(data):
    fig,axes=plt.subplots(1,3,figsize=(4.8,3.0),sharey=True)
    fig.subplots_adjust(left=.20,right=.97,bottom=.23,top=.74,wspace=.22)
    projection=[]
    for j,d in enumerate(DATASETS):
        for i,(b,m) in enumerate((b,m) for b in (12,24,48) for m in METHODS[1:]):
            rr=rows(data,dataset=d,method=m,budget=b)
            capped=sum(r['capped'] or 0 for r in rr);multi=sum(r['capped_multi'] or 0 for r in rr)
            executed=len(rr);multi_executed=sum(int(r['committed_action_size'])>1 for r in rr)
            x=multi/capped if capped else None;y=multi_executed/executed if executed else None
            if x is not None:axes[j].scatter(x,i-.1,c='#777',s=25,marker='o')
            if y is not None:axes[j].scatter(y,i+.1,c=COLORS[m],s=27,marker='D')
            if x is None and y is None:axes[j].text(.03,i,'NA',va='center')
            projection.append({'dataset':d,'method':m,'budget':b,'capped_multi':multi,'capped_total':capped,'committed_multi':multi_executed,'committed_total':executed})
        axes[j].set_title(TITLES[d],fontsize=8);axes[j].set_xlim(-.07,1.07);axes[j].set_xticks([0,.5,1],['0','50','100']);axes[j].grid(axis='x',alpha=.15);axes[j].set_xlabel('Width > 1 (%)')
    axes[0].set_yticks(range(6),[f'B{b} {old.SHORT[m]}' for b in (12,24,48) for m in METHODS[1:]])
    axes[0].set_ylim(5.7,-.7)
    fig.legend(handles=[Line2D([],[],color='#777',marker='o',ls='',label='Capped candidate occurrences'),Line2D([],[],color='#D55E00',marker='D',ls='',label='Committed batches')],loc='upper center',ncol=1)
    fig.text(.5,.04,'Separate denominators; zero executed multi-edge batches remain visible.',ha='center')
    return fig,projection

def main(evidence,out):
    evidence,out=Path(evidence),Path(out);validation=validate(evidence);out.mkdir(parents=True,exist_ok=True);(out/'data').mkdir(exist_ok=True)
    old.setup_style();plt.rcParams['svg.hashsalt']='cut-audit-er-v4'
    legacy=load_evidence(evidence/'legacy_v3');records=[]
    event_fig,event_data=old.events_figure(legacy);event_fig.set_size_inches(4.8,4.3)
    specs=[('fig01_contract',contract()),('fig02_structure',structure(table(evidence,'coverage'))),
           ('fig03_outcomes',outcomes(table(evidence,'natural_endpoints'))),('fig04_events',(event_fig,event_data)),
           ('fig05_controlled',controlled(table(evidence,'synthetic_endpoints'))),('fig06_use',use(table(evidence,'natural_batches')))]
    for name,(fig,projection) in specs:
        records.append(old.save(fig,out,name,projection,['evidence/manifest.json'],'V4 fixed study; see figure-specific public projection'))
    provenance={'schema':'cut-audit-figures-v4','input_manifest_sha256':sha(evidence/'manifest.json'),'validation':validation,'figures':records}
    (out/'figure_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'PASS','figures':len(records)}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence',type=Path,default=ROOT/'evidence');p.add_argument('--out',type=Path,default=ROOT/'figures');a=p.parse_args();main(a.evidence,a.out)
