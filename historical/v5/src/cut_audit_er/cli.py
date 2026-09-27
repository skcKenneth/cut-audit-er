from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from .experiment import run_experiment,metadata,save_runs
from .synthetic import synthetic_records
from .data import load_csv,entity_splits,split_manifest
from .matcher import PairMatcher, MATCHER_VARIANTS
from .audit import run_audit
from .policies import METHODS, DEFAULT_METHODS
from .guard import require_approval

def main():
    p=argparse.ArgumentParser(description="CUT-AUDIT-ER research starter")
    p.add_argument("--root",type=Path,default=Path.cwd())
    s=p.add_subparsers(dest="command",required=True)
    a=s.add_parser("smoke");a.add_argument("--out",type=Path,default=Path("outputs/smoke"))
    a=s.add_parser("experiment");a.add_argument("--config",type=Path,required=True);a.add_argument("--out",type=Path,required=True)
    a=s.add_parser("make-demo-csv");a.add_argument("--out",type=Path,default=Path("data/processed/synthetic_records.csv"));a.add_argument("--seed",type=int,default=7)
    a=s.add_parser("csv");a.add_argument("--input",type=Path,required=True);a.add_argument("--out",type=Path,required=True)
    a.add_argument("--seed",type=int,default=7);a.add_argument("--budget",type=int,default=12)
    a.add_argument("--threshold",type=float,default=.6);a.add_argument("--top-k",type=int,default=10)
    a.add_argument("--matcher-variant",choices=MATCHER_VARIANTS,default="char4")
    a.add_argument("--noise",type=float,default=0.0)
    a.add_argument("--fn-weight",type=float,default=1.0)
    a.add_argument("--max-width",type=int,choices=(1,2),default=2)
    a.add_argument("--shortlist",type=int,default=24)
    a.add_argument("--phase",choices=("development","test"),default="development")
    a.add_argument("--methods",nargs="+",choices=METHODS,default=list(DEFAULT_METHODS))
    a.add_argument("--data-kind",choices=("synthetic","semisynthetic","real"),required=True)
    a.add_argument("--provenance",type=Path,help="Required for real/semisynthetic datasets")
    args=p.parse_args();root=args.root.resolve()
    if args.command=="smoke":
        cfg=json.loads((root/"configs/smoke.json").read_text());runs=run_experiment(root,cfg,args.out)
        print(f"Wrote {len(runs)} synthetic smoke runs to {args.out}")
    elif args.command=="experiment":
        cfg=json.loads(args.config.read_text());runs=run_experiment(root,cfg,args.out)
        print(f"Wrote {len(runs)} runs to {args.out}")
    elif args.command=="make-demo-csv":
        args.out.parent.mkdir(parents=True,exist_ok=True)
        if args.out.exists(): raise FileExistsError(args.out)
        synthetic_records(args.seed).to_csv(args.out,index=False)
        print(f"Wrote synthetic text records to {args.out}")
    else:
        digest=hashlib.sha256(args.input.read_bytes()).hexdigest()
        config={"seed":args.seed,"budget":args.budget,"threshold":args.threshold,"top_k":args.top_k,
                "phase":args.phase,"methods":args.methods,"data_kind":args.data_kind,
                "oracle_noise":args.noise,"fn_weight":args.fn_weight,
                "max_width":args.max_width,"shortlist":args.shortlist,"matcher_variant":args.matcher_variant}
        if args.phase=="test": require_approval(root,digest,config)
        if args.data_kind!="synthetic" and (args.provenance is None or not args.provenance.exists()):
            raise ValueError("Real/semisynthetic data require a provenance JSON file")
        provenance=json.loads(args.provenance.read_text()) if args.provenance else {"kind":"synthetic"}
        if args.data_kind!="synthetic":
            for key in ("source_url","license","original_sha256","transformations"):
                if not provenance.get(key): raise ValueError(f"Provenance missing {key}")
        df=load_csv(args.input)
        if len(df)>4000: raise ValueError("Starter CSV pipeline caps total records at 4000; implement sparse scoring before scaling")
        splits=entity_splits(df,args.seed)
        for name in ("train","calibration",args.phase):
            if len(splits[name])>1500: raise ValueError(f"{name} split exceeds dense-scoring cap of 1500")
        matcher=PairMatcher(args.seed,matcher_variant=args.matcher_variant).fit(splits["train"],splits["calibration"])
        target=splits[args.phase]
        g,ps,diag=matcher.graph_for(target,args.threshold,args.top_k)
        truth=dict(zip(target.record_id,target.entity_id));runs=[]
        for method in args.methods:
            r=run_audit(g,ps,truth,method,args.budget,args.seed,args.noise,args.fn_weight,
                        args.max_width,args.shortlist,match_threshold=args.threshold)
            r.update(dataset=args.input.stem,regime="observed_matcher_errors");runs.append(r)
        meta=metadata(root,config)|{"phase":args.phase,"data_kind":args.data_kind,
              "input_sha256":digest,"provenance":provenance,"splits":split_manifest(splits),"matcher_diagnostics":diag}
        save_runs(args.out,runs,meta)
        print(f"Wrote {len(runs)} {args.data_kind} {args.phase} runs to {args.out}")

if __name__=="__main__": main()
