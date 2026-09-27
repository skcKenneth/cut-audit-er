"""CPU baseline: train-only character TF-IDF and logistic matching + Platt fit.

No foundation model is downloaded. Uniform training/calibration pair sampling
avoids label-conditioned negative sampling. Entity-disjoint calibration is used;
calibration quality on the deployed candidate-edge distribution is NOT guaranteed.
"""
from __future__ import annotations
import time
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
import networkx as nx
from .scores import PairScores


def calibration_summary(labels, probabilities, n_bins: int=10) -> dict:
    """Descriptive evaluation only; never used to fit or select graph edges.

    Fixed equal-width bins include zero and one; empty bins retain null means.
    Marginal reliability here does not imply adaptive conditional calibration.
    """
    y=np.asarray(labels,dtype=int);p=np.asarray(probabilities,dtype=float)
    if y.shape!=p.shape or y.ndim!=1 or n_bins<1:
        raise ValueError("Calibration arrays must be one-dimensional and aligned")
    if not np.isin(y,(0,1)).all() or not np.isfinite(p).all() or ((p<0)|(p>1)).any():
        raise ValueError("Calibration requires binary labels and finite probabilities")
    bins=np.minimum((p*n_bins).astype(int),n_bins-1)
    rows=[]
    for k in range(n_bins):
        use=bins==k;count=int(use.sum())
        rows.append({"lower":k/n_bins,"upper":(k+1)/n_bins,
                     "upper_inclusive":k==n_bins-1,"count":count,
                     "positive_labels":int(y[use].sum()),
                     "mean_probability":float(p[use].mean()) if count else None,
                     "positive_rate":float(y[use].mean()) if count else None,
                     "brier":float(np.mean((p[use]-y[use])**2)) if count else None})
    return {"pair_count":len(y),"positive_labels":int(y.sum()),
            "negative_labels":int(len(y)-y.sum()),
            "mean_probability":float(p.mean()) if len(y) else None,
            "positive_rate":float(y.mean()) if len(y) else None,
            "brier":float(np.mean((p-y)**2)) if len(y) else None,
            "binning":"equal_width_probability; last upper endpoint inclusive",
            "bins":rows}


MATCHER_VARIANTS=("char4", "char_word6")
FEATURE_NAMES=("char_cosine", "char_cosine_squared", "length_ratio", "token_jaccard")


class PairMatcher:
    def __init__(self,seed: int=7,max_pairs: int=50000,matcher_variant: str="char4"):
        if matcher_variant not in MATCHER_VARIANTS:
            raise ValueError(f"Unknown matcher variant: {matcher_variant}")
        self.matcher_variant=matcher_variant
        self.feature_names=FEATURE_NAMES+(("word_cosine", "word_cosine_squared") if matcher_variant=="char_word6" else ())
        self.word_vectorizer=(TfidfVectorizer(analyzer="word",ngram_range=(1,2),max_features=20000,
            token_pattern=r"(?u)\b\w+\b",lowercase=True,norm="l2",use_idf=True,
            smooth_idf=True,sublinear_tf=False) if matcher_variant=="char_word6" else None)
        self.seed=seed;self.max_pairs=max_pairs
        self.vectorizer=TfidfVectorizer(analyzer="char_wb",ngram_range=(2,4),max_features=20000)
        self.model=LogisticRegression(max_iter=1000,random_state=seed)
        self.calibrator=LogisticRegression(max_iter=1000,random_state=seed)
        self.fit_ids=set();self.calibration_ids=set();self.fitted_entities=set()
        self.sample_diagnostics={};self.fit_diagnostics={}

    def _features(self,df: pd.DataFrame):
        # Only text is used: no IDs, sources, or entity labels become features.
        x=self.vectorizer.transform(df.text)
        sim=(x@x.T).toarray()
        n=len(df);i,j=np.triu_indices(n,1)
        lengths=np.array([len(s) for s in df.text],dtype=float)
        ratio=np.minimum(lengths[i],lengths[j])/np.maximum(lengths[i],lengths[j])
        tokens=[set(s.lower().split()) for s in df.text]
        jac=np.array([len(tokens[a]&tokens[b])/max(1,len(tokens[a]|tokens[b])) for a,b in zip(i,j)])
        f=np.column_stack((sim[i,j],sim[i,j]**2,ratio,jac))
        if self.word_vectorizer is not None:
            words=self.word_vectorizer.transform(df.text)
            word_sim=(words@words.T).toarray()
            f=np.column_stack((f,word_sim[i,j],word_sim[i,j]**2))
        # Blocking stays character-only to isolate the matcher feature change.
        return f,i,j,sim

    def _sample(self,f,i,j,df,offset):
        rng=np.random.default_rng(self.seed+offset)
        rows=np.arange(len(f))
        if len(rows)>self.max_pairs:
            rows=np.sort(rng.choice(rows,self.max_pairs,replace=False))
        y=(df.entity_id.to_numpy()[i[rows]]==df.entity_id.to_numpy()[j[rows]]).astype(int)
        stage={1:"train",2:"calibration"}.get(offset,str(offset))
        self.sample_diagnostics[stage]={"sampling":"uniform_without_replacement_unordered_pairs",
            "available_pairs":len(f),"sampled_pair_labels":len(y),
            "positive_labels":int(y.sum()),"negative_labels":int(len(y)-y.sum()),
            "sample_seed":self.seed+offset,"max_pairs":self.max_pairs}
        if np.unique(y).size<2:
            raise ValueError("Pair sample contains one class; enlarge a PREDECLARED training/calibration sample")
        return f[rows],y

    def fit(self,train: pd.DataFrame,calibration: pd.DataFrame):
        start=time.perf_counter()
        if set(train.entity_id)&set(calibration.entity_id) or set(train.record_id)&set(calibration.record_id):
            raise ValueError("Training/calibration overlap")
        self.fitted_entities=set(train.entity_id)|set(calibration.entity_id)
        self.fit_ids=set(train.record_id);self.calibration_ids=set(calibration.record_id)
        self.sample_diagnostics={}
        t=time.perf_counter();self.vectorizer.fit(train.text)
        timing={"vectorizer_fit_seconds":time.perf_counter()-t}
        if self.word_vectorizer is not None:
            t=time.perf_counter();self.word_vectorizer.fit(train.text)
            timing["word_vectorizer_fit_seconds"]=time.perf_counter()-t
        t=time.perf_counter();f,i,j,_=self._features(train)
        timing["train_feature_seconds"]=time.perf_counter()-t
        x,y=self._sample(f,i,j,train,1)
        t=time.perf_counter();self.model.fit(x,y)
        timing["matcher_fit_seconds"]=time.perf_counter()-t
        t=time.perf_counter();f,i,j,_=self._features(calibration)
        timing["calibration_feature_seconds"]=time.perf_counter()-t
        x,y=self._sample(f,i,j,calibration,2)
        t=time.perf_counter();raw=self.model.decision_function(x).reshape(-1,1)
        timing["calibration_scoring_seconds"]=time.perf_counter()-t
        t=time.perf_counter();self.calibrator.fit(raw,y)
        timing["calibrator_fit_seconds"]=time.perf_counter()-t
        timing["fit_total_seconds"]=time.perf_counter()-start
        self.fit_diagnostics={"matcher_variant":self.matcher_variant,"feature_names":list(self.feature_names),
            "blocking_representation":"train_fitted_character_tfidf_unchanged",
            "word_vocabulary_size":len(self.word_vectorizer.vocabulary_) if self.word_vectorizer is not None else 0,
            "training":dict(self.sample_diagnostics["train"]),
            "calibration":dict(self.sample_diagnostics["calibration"]),
            "shared_supervised_pair_labels":sum(d["sampled_pair_labels"] for d in self.sample_diagnostics.values()),
            "label_cost_scope":"shared offline training/calibration labels, separate from repair oracle budget",
            "timing":timing}
        return self

    def graph_for(self,records: pd.DataFrame,threshold: float=.6,top_k: int=10):
        start=time.perf_counter()
        if set(records.entity_id)&self.fitted_entities:
            raise ValueError("Evaluation entities overlap fitted entities")
        if set(records.record_id)&(self.fit_ids|self.calibration_ids):
            raise ValueError("Evaluation records overlap fitted records")
        if not 0<=threshold<=1 or top_k<1 or len(records)>1500:
            raise ValueError("Bad threshold/top_k or >1500 records: implement sparse scoring before scaling")
        t=time.perf_counter();f,i,j,sim=self._features(records)
        timing={"feature_seconds":time.perf_counter()-t}
        t=time.perf_counter()
        prob=self.calibrator.predict_proba(self.model.decision_function(f).reshape(-1,1))[:,1]
        timing["pair_scoring_seconds"]=time.perf_counter()-t
        t=time.perf_counter()
        n=len(records);p=np.eye(n);p[i,j]=p[j,i]=prob
        ids=tuple(records.record_id.astype(str));g=nx.Graph();g.add_nodes_from(ids)
        np.fill_diagonal(sim,-1)
        candidate=set()
        for a in range(n):
            for b in np.argsort(-sim[a],kind="stable")[:min(top_k,n-1)]:
                candidate.add(tuple(sorted((a,int(b)))))
        for a,b in sorted(candidate):
            if p[a,b]>=threshold:
                g.add_edge(ids[a],ids[b],p=float(p[a,b]))
        timing["graph_construction_seconds"]=time.perf_counter()-t
        # Evaluation only: these labels are not passed into the selector.
        t=time.perf_counter()
        y=np.array([records.entity_id.iloc[a]==records.entity_id.iloc[b] for a,b in sorted(candidate)],int)
        pp=np.array([p[a,b] for a,b in sorted(candidate)])
        positives=sum((records.entity_id.value_counts()*(records.entity_id.value_counts()-1)//2))
        all_y=(records.entity_id.to_numpy()[i]==records.entity_id.to_numpy()[j]).astype(int)
        retained=pp>=threshold;tp=int(y[retained].sum());predicted=int(retained.sum())
        candidate_positives=int(y.sum())
        diag={"matcher_variant":self.matcher_variant,"feature_names":list(self.feature_names),
              "candidate_pairs":len(candidate),"scored_all_pairs":len(prob),
              "blocking_pair_recall":float(y.sum()/positives) if positives else 1.,
              "candidate_brier":float(brier_score_loss(y,pp)) if len(y) else None,
              "threshold":threshold,"top_k":top_k,
              "shared_matcher_fit":self.fit_diagnostics,
              "all_pair_calibration":calibration_summary(all_y,prob),
              "candidate_calibration":calibration_summary(y,pp),
              "candidate_threshold_metrics":{"tp":tp,"fp":predicted-tp,
                  "fn_within_candidates":candidate_positives-tp,
                  "precision":tp/predicted if predicted else 1.,
                  "recall_within_candidates":tp/candidate_positives if candidate_positives else 1.,
                  "recall_all_true_pairs":tp/int(positives) if positives else 1.},
              "initial_graph_shape":{"nodes":len(g),"edges":g.number_of_edges(),
                  "components":nx.number_connected_components(g),
                  "largest_component":max(map(len,nx.connected_components(g)),default=0),
                  "isolates":nx.number_of_isolates(g)}}
        timing["evaluation_diagnostics_seconds"]=time.perf_counter()-t
        timing["graph_for_total_seconds"]=time.perf_counter()-start
        diag["timing"]=timing
        return g,PairScores(ids,p),diag
